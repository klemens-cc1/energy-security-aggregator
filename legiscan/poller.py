"""
LegiScan polling loop — Slice 1.1

Run modes:
  python -m legiscan.poller backfill   # one-time dataset download for all states
  python -m legiscan.poller delta      # weekly delta: check changed bills, summarize, queue
"""

import base64
import io
import json
import logging
import sys
import zipfile

from dotenv import load_dotenv
load_dotenv()

from .client import LegiScanClient
from .db import (
    init_db, upsert_bill,
    get_dataset_hash, upsert_dataset,
    get_doc_hash, upsert_doc,
    queue_bill, get_pending_queue,
    find_changed_energy_bills,
    upsert_watched_bill, get_watched_bill_hash, get_all_watched_bills,
)
from .filter import (
    SEARCH_KEYWORDS, keyword_tags, has_negative_signal,
)
from .summarizer import summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# All 50 states + DC
ALL_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID",
    "IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS",
    "MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK",
    "OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV",
    "WI","WY","DC",
]

# LegiScan numeric state_id → abbreviation (static mapping from LegiScan docs)
STATE_ID_TO_ABBR = {
     0:"US", 1:"AL", 2:"AK", 3:"AZ", 4:"AR", 5:"CA", 6:"CO", 7:"CT",
     8:"DE", 9:"FL",10:"GA",11:"HI",12:"ID",13:"IL",14:"IN",15:"IA",
    16:"KS",17:"KY",18:"LA",19:"ME",20:"MD",21:"MA",22:"MI",23:"MN",
    24:"MS",25:"MO",26:"MT",27:"NE",28:"NV",29:"NH",30:"NJ",31:"NM",
    32:"NY",33:"NC",34:"ND",35:"OH",36:"OK",37:"OR",38:"PA",39:"RI",
    40:"SC",41:"SD",42:"TN",43:"TX",44:"UT",45:"VT",46:"VA",47:"WA",
    48:"WV",49:"WI",50:"WY",51:"DC",52:"US",
}

CONFIDENCE_MIN = 0.7  # below this routes to human review


def backfill(client: LegiScanClient):
    """
    Download dataset ZIPs for all current sessions.
    Uses dataset_hash to skip sessions that haven't changed since last run.
    ~1,000 API calls for full national history.
    """
    log.info("=== BACKFILL: downloading session datasets ===")
    dataset_list = client.get_dataset_list()
    log.info(f"Found {len(dataset_list)} sessions across all states")

    downloaded = skipped = 0

    # Only download sessions that started in 2024 or later — no need for full history
    current_sessions = [e for e in dataset_list if e.get("year_start", 0) >= 2023]
    log.info(f"Filtered to {len(current_sessions)} current sessions (2023+)")

    for entry in current_sessions:
        session_id   = entry["session_id"]
        state        = STATE_ID_TO_ABBR.get(entry.get("state_id", -1), "??")
        session_name = entry.get("session_name", "")
        new_hash     = entry["dataset_hash"]
        access_key   = entry.get("access_key", "")

        cached_hash = get_dataset_hash(session_id)
        if cached_hash == new_hash:
            skipped += 1
            continue

        log.info(f"  Downloading {state} — {session_name} (session {session_id})")
        try:
            dataset = client.get_dataset(access_key, session_id)
            zip_b64 = dataset.get("zip", "")
            if zip_b64:
                _ingest_dataset_zip(zip_b64, state, session_id)
            upsert_dataset(session_id, state, session_name, new_hash, access_key)
            downloaded += 1
        except Exception as e:
            log.error(f"  Failed {state} session {session_id}: {e}")

    log.info(f"Backfill complete — {downloaded} downloaded, {skipped} skipped (hash match)")


def _ingest_dataset_zip(zip_b64: str, state: str, session_id: int):
    """Unpack a base64-encoded dataset ZIP and bulk-insert bill stubs into SQLite."""
    raw = base64.b64decode(zip_b64)
    count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            try:
                data = json.loads(zf.read(name))
                if "bill" not in data:
                    continue
                bill = data["bill"]
                upsert_bill(
                    bill_id     = bill["bill_id"],
                    state       = state,
                    session_id  = session_id,
                    bill_number = bill.get("bill_number", ""),
                    title       = bill.get("title", ""),
                    change_hash = bill.get("change_hash", ""),
                    status_id   = bill.get("status", 0),
                    last_action = bill.get("last_action", ""),
                    url         = bill.get("url", ""),
                )
                count += 1
            except Exception:
                pass
    log.info(f"    Ingested {count} bills from {state} session {session_id}")


def delta(client: LegiScanClient):
    """
    Weekly delta loop — local SQL discovery + getMasterListRaw change detection.

    Phase 1: getMasterListRaw × 50 states (50 API calls) — get current change hashes
    Phase 2: local SQL keyword filter on bills table (0 API calls) — find energy candidates
    Phase 3: getBill only for candidates whose hash changed (small N API calls)
    Phase 4: getBillText + summarize for survivors
    Phase C-lite: re-check watched bills for status changes
    """
    log.info("=== DELTA: fetching master lists ===")

    # Build a map of bill_id → current change_hash from LegiScan
    live_hashes: dict[int, str] = {}
    for state in ALL_STATES:
        try:
            master = client.get_master_list_raw(state)
        except Exception as e:
            log.warning(f"getMasterListRaw failed {state}: {e}")
            continue
        for key, entry in master.items():
            if key == "session":
                continue
            bid = entry.get("bill_id")
            if bid:
                live_hashes[bid] = entry.get("change_hash", "")

    log.info(f"Live hashes: {len(live_hashes)} bills across all states")

    # ── Phase 2: local keyword discovery ──────────────────────────────────────
    log.info("=== DELTA: local keyword filter ===")
    candidates: dict[int, dict] = {}

    matches = find_changed_energy_bills(ALL_STATES, SEARCH_KEYWORDS)
    for row in matches:
        bill_id     = row["bill_id"]
        state       = row["state"]
        live_hash   = live_hashes.get(bill_id)
        stored_hash = row["change_hash"]

        # Only process if bill changed since last fetch OR never watched
        if live_hash and live_hash == stored_hash:
            if get_watched_bill_hash(bill_id) == stored_hash:
                continue

        if bill_id not in candidates:
            candidates[bill_id] = {
                "state":       state,
                "change_hash": live_hash or stored_hash,
                "title":       row["title"] or "",
                "description": row["description"] or "",
                "url":         row["url"] or "",
            }

    log.info(f"Local filter: {len(candidates)} candidates")

    # ── Phase 3 & 4: getBill + summarize ──────────────────────────────────────
    log.info("=== DELTA: fetching + summarizing ===")
    fetched = summarized = 0

    for bill_id, data in candidates.items():
        state       = data["state"]
        change_hash = data["change_hash"]

        if get_watched_bill_hash(bill_id) == change_hash:
            continue

        try:
            bill = client.get_bill(bill_id)
        except Exception as e:
            log.warning(f"getBill failed bill_id={bill_id}: {e}")
            continue

        fetched += 1
        bill_number = bill.get("bill_number", "")
        title       = bill.get("title", "")
        description = bill.get("description", "") or title
        url         = bill.get("url", "")
        session_id  = bill.get("session", {}).get("session_id")

        upsert_bill(bill_id, state, session_id, bill_number, title,
                    change_hash, bill.get("status", 0),
                    bill.get("last_action", ""), url,
                    description=description)
        upsert_watched_bill(bill_id, state, bill_number, 0, change_hash)

        if has_negative_signal(f"{title} {description}"):
            log.debug(f"  NEGATIVE SIGNAL skipped: {state} {bill_number}")
            continue

        text   = _get_bill_text(client, bill)
        result = summarize(state, bill_number, title, text or description)

        if result is None:
            tags = keyword_tags(f"{title} {description}")
            queue_bill(bill_id, state, bill_number, title,
                       description[:300], tags, 0.5, url)
            continue

        summarized += 1
        queue_bill(
            bill_id     = bill_id,
            state       = state,
            bill_number = bill_number,
            title       = title,
            summary     = result["summary"],
            tags        = result["tags"],
            confidence  = result["confidence"],
            url         = url,
        )
        if result["confidence"] < CONFIDENCE_MIN:
            log.info(f"  LOW CONF ({result['confidence']:.2f}): {state} {bill_number}")

    # ── Phase C-lite: watched bills not caught by local filter ────────────────
    watch_updated = 0
    for watched in get_all_watched_bills():
        bill_id  = watched["bill_id"]
        if bill_id in candidates:
            continue
        live_hash = live_hashes.get(bill_id)
        if live_hash and live_hash != watched["change_hash"]:
            watch_updated += 1
            candidates[bill_id] = {"state": watched["state"], "change_hash": live_hash}

    pending = len(get_pending_queue())
    log.info(
        f"Delta complete — {len(candidates)} candidates, {fetched} fetched, "
        f"{summarized} summarized, {watch_updated} watchlist updates, "
        f"{pending} total pending review"
    )


def _get_bill_text(client: LegiScanClient, bill: dict) -> str | None:
    """
    Fetch and decode the first non-PDF document for a bill.
    Skips PDFs (returns None so caller falls back to description).
    Skips download if doc_hash unchanged (cached).
    """
    documents = bill.get("texts") or bill.get("documents") or []
    if not documents:
        return None

    for doc in documents:
        mime = (doc.get("mime") or doc.get("mime_type") or "").lower()
        if "pdf" in mime:
            continue

        doc_id   = doc.get("doc_id")
        doc_hash = doc.get("doc_hash", "")

        if not doc_id:
            continue

        if get_doc_hash(doc_id) == doc_hash:
            return None  # unchanged — caller falls back to description

        try:
            text_obj = client.get_bill_text(doc_id)
            encoded  = text_obj.get("doc", "")
            if not encoded:
                continue
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            # Sanity check: if >30% replacement chars it's still binary garbage
            if decoded.count("�") / max(len(decoded), 1) > 0.3:
                log.debug(f"  doc_id={doc_id} looks like binary after decode — skipping")
                continue
            upsert_doc(doc_id, bill["bill_id"], doc_hash, "")
            return decoded
        except Exception as e:
            log.warning(f"getBillText failed doc_id={doc_id}: {e}")
            continue

    return None


def run(mode: str):
    init_db()
    client = LegiScanClient()

    if mode == "backfill":
        backfill(client)
    elif mode == "delta":
        delta(client)
    else:
        print(f"Unknown mode: {mode}. Use 'backfill' or 'delta'.")
        sys.exit(1)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "delta"
    run(mode)
