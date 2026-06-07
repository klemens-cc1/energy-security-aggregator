"""
Seed LegiScan bills from the datacenterpolicy.com dataset.

For each state bill in .datacenterpolicy_raw.json that isn't already in our
queue, searches LegiScan by bill number to find the matching bill_id, then
fetches full metadata and adds it to the queue.

Run: python seed_from_dcp.py
"""

import io
import json
import re
import sys
import time
from pathlib import Path

# Force UTF-8 output to avoid cp1252 errors on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from legiscan.client import LegiScanClient
from legiscan.db import init_db, get_conn, upsert_bill, upsert_watched_bill, queue_bill
from legiscan.filter import has_negative_signal, keyword_tags

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Massachussetts": "MA", "Michigan": "MI", "Michgan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Pennslyvania": "PA", "Rhode Island": "RI", "Rhode Isaland": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "South Dokota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}


def norm(code: str) -> str:
    # Normalize unicode spaces and dashes before stripping
    code = code.replace(" ", " ").replace(" ", " ")
    return re.sub(r"[\s\-.]", "", code).upper()


def is_real_bill(code: str) -> bool:
    """Filter out statutes, regulations, and placeholder entries."""
    code = code.strip()
    if not code or code.lower() in ("n/a", "n/a as of yet", "tbd"):
        return False
    # Real bill codes start with letters and contain digits (e.g. HB123, SB 51, AB 222)
    return bool(re.match(r"^[A-Za-z]{1,4}[\s\-.]?\d", code))


def load_missing() -> list[dict]:
    """Return DCP state bills not already in our queue."""
    dcp = json.loads(Path(".datacenterpolicy_raw.json").read_text(encoding="utf-8"))
    state_bills = [d for d in dcp if d["level_of_government"] == "State"]

    with get_conn() as conn:
        rows = conn.execute("SELECT state, bill_number FROM queue").fetchall()
    in_queue = {(r["state"], norm(r["bill_number"])) for r in rows}

    missing = []
    for d in state_bills:
        abbr = STATE_ABBR.get(d["state"])
        if not abbr:
            continue
        if not is_real_bill(d["bill_code"]):
            continue
        if (abbr, norm(d["bill_code"])) not in in_queue:
            missing.append({**d, "abbr": abbr})
    return missing


def strip_session_prefix(code: str) -> str:
    """Colorado uses HB25-1233 style — strip the 2-digit session year to get HB1233."""
    return re.sub(r"^([A-Za-z]+)\d{2}-", r"\1", code)


def find_bill_in_legiscan(client: LegiScanClient, abbr: str, bill_code: str) -> dict | None:
    """Search LegiScan for a specific bill by state + bill number."""
    # Build list of search terms to try: original + session-stripped variant
    search_terms = [bill_code]
    stripped = strip_session_prefix(bill_code)
    if stripped != bill_code:
        search_terms.append(stripped)

    targets = {norm(t) for t in search_terms}

    for query in search_terms:
        for year_param in (3, 1):
            try:
                results = client.get_search(query, abbr, year=year_param)
            except Exception as e:
                print(f"    search error: {e}")
                return None
            for r in results:
                if norm(r.get("bill_number", "")) in targets:
                    return r
    return None


def main():
    init_db()
    client = LegiScanClient()

    missing = load_missing()
    print(f"Bills in DCP not in our queue: {len(missing)}")

    added = skipped = not_found = 0

    for i, d in enumerate(missing, 1):
        abbr      = d["abbr"]
        bill_code = d["bill_code"]
        print(f"[{i:03d}/{len(missing)}] {abbr} {bill_code} ...", end=" ", flush=True)

        hit = find_bill_in_legiscan(client, abbr, bill_code)
        if not hit:
            print("not found in LegiScan")
            not_found += 1
            continue

        bill_id = hit.get("bill_id")
        if not bill_id:
            print("no bill_id")
            not_found += 1
            continue

        try:
            bill = client.get_bill(bill_id)
        except Exception as e:
            print(f"getBill failed: {e}")
            not_found += 1
            continue

        bill_number = bill.get("bill_number", bill_code)
        title       = bill.get("title", d.get("name", ""))
        description = bill.get("description", "") or title
        url         = bill.get("url", d.get("source_info", ""))
        session_id  = bill.get("session", {}).get("session_id")
        change_hash = bill.get("change_hash", "")
        status_id   = bill.get("status", 0)
        last_action = bill.get("last_action", "")

        upsert_bill(bill_id, abbr, session_id, bill_number, title,
                    change_hash, status_id, last_action, url, description=description)
        upsert_watched_bill(bill_id, abbr, bill_number, 0, change_hash)

        # Use their mechanism as seed tags where we have no description signal
        dcp_tags = [m.strip() for m in (d.get("key_mechanism") or "").split(",") if m.strip()]
        our_tags = keyword_tags(f"{title} {description}")
        tags = list(dict.fromkeys(our_tags + dcp_tags))  # merge, deduplicate

        queue_bill(bill_id, abbr, bill_number, title,
                   description[:300], tags, 0.6, url)

        print(f"queued ({d.get('status', '')})")
        added += 1
        time.sleep(0.1)  # gentle rate limiting

    print(f"\nDone: {added} added, {skipped} skipped, {not_found} not found in LegiScan")


if __name__ == "__main__":
    main()
