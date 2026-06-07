"""
50-state data center bill fetch.
Run: python fetch_national.py
Pulls data center-related bills for all 50 states and queues them for review.
"""

import base64
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Make legiscan importable as a package
sys.path.insert(0, str(Path(__file__).parent))

from legiscan.client import LegiScanClient
from legiscan.db import (
    init_db, get_watched_bill_hash,
    upsert_bill, upsert_watched_bill, queue_bill, get_doc_hash, upsert_doc,
)
from legiscan.filter import has_negative_signal, keyword_tags
from legiscan.summarizer import summarize

ALL_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
]

DC_QUERIES = [
    "data center load",
    "data center power",
    "datacenter",
    "colocation facility",
    "qualified data center",      # tax exemption bill language
    "large load customer",        # utility-rate / interconnection bills
    "data center tax",            # restrictive tax bills
    "hyperscale",                 # large-scale facility bills
    "data center security",       # national security angle
]

# LegiScan year=3 → current + prior sessions
YEAR_PARAM = 3


def fetch_bill_text(client, bill):
    documents = bill.get("texts") or bill.get("documents") or []
    for doc in documents:
        mime = (doc.get("mime") or doc.get("mime_type") or "").lower()
        if "pdf" in mime:
            continue
        doc_id   = doc.get("doc_id")
        doc_hash = doc.get("doc_hash", "")
        if not doc_id:
            continue
        if get_doc_hash(doc_id) == doc_hash:
            return None
        try:
            text_obj = client.get_bill_text(doc_id)
            encoded  = text_obj.get("doc", "")
            if not encoded:
                continue
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            if decoded.count("\x00") / max(len(decoded), 1) > 0.3:
                continue
            upsert_doc(doc_id, bill["bill_id"], doc_hash, "")
            return decoded
        except Exception:
            continue
    return None


def fetch_state(client, state, totals):
    seen = {}
    for q in DC_QUERIES:
        try:
            results = client.get_search(q, state, year=YEAR_PARAM)
        except Exception as e:
            print(f"    search '{q}' failed: {e}", flush=True)
            continue
        for r in results:
            bid = r.get("bill_id")
            if bid and (bid not in seen or r.get("relevance", 0) > seen[bid].get("relevance", 0)):
                seen[bid] = r

    new = skipped = 0
    for bill_id, hit in seen.items():
        stored_hash = get_watched_bill_hash(bill_id)
        live_hash   = hit.get("change_hash", "")
        if stored_hash and stored_hash == live_hash:
            skipped += 1
            continue
        try:
            bill = client.get_bill(bill_id)
        except Exception as e:
            print(f"    getBill {bill_id} failed: {e}", flush=True)
            continue

        bill_number = bill.get("bill_number", "")
        title       = bill.get("title", "")
        description = bill.get("description", "") or title
        url         = bill.get("url", "")
        session_id  = bill.get("session", {}).get("session_id")
        change_hash = bill.get("change_hash", live_hash)
        status_id   = bill.get("status", 0)
        last_action = bill.get("last_action", "")

        upsert_bill(bill_id, state, session_id, bill_number, title,
                    change_hash, status_id, last_action, url, description=description)
        upsert_watched_bill(bill_id, state, bill_number, 0, change_hash)

        if has_negative_signal(f"{title} {description}"):
            skipped += 1
            continue

        # Skip Groq summarization and bill text download — analysis script
        # handles LLM classification separately with a smaller model.
        tags = keyword_tags(f"{title} {description}")
        queue_bill(bill_id, state, bill_number, title,
                   description[:300], tags, 0.5, url)
        new += 1

    totals["new"]     += new
    totals["skipped"] += skipped
    totals["hits"]    += len(seen)
    return new, skipped, len(seen)


def main():
    init_db()
    client = LegiScanClient()
    totals = {"new": 0, "skipped": 0, "hits": 0}

    for i, state in enumerate(ALL_STATES, 1):
        print(f"[{i:02d}/50] {state} ...", end=" ", flush=True)
        t0 = time.time()
        new, skipped, hits = fetch_state(client, state, totals)
        elapsed = time.time() - t0
        print(f"{hits} hits  {new} new  {skipped} skipped  ({elapsed:.0f}s)", flush=True)

    print(f"\nDone. Total: {totals['hits']} hits, {totals['new']} new queued, {totals['skipped']} skipped")


if __name__ == "__main__":
    main()
