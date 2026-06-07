"""
Minimal review server for the LegiScan bill queue.
Run: python -m legiscan.review_server
Then open: http://localhost:8765/legiscan/review.html
"""

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv
load_dotenv()

from .client import LegiScanClient
from .db import (
    get_conn, init_db,
    set_review_status, update_summary,
    upsert_bill, upsert_watched_bill, queue_bill,
    get_watched_bill_hash,
)
from .filter import has_negative_signal, keyword_tags
from .summarizer import summarize

PORT = int(os.environ.get("REVIEW_PORT", 8765))
HERE = Path(__file__).parent

# Topic presets → list of search queries (each is one getSearch call)
TOPIC_QUERIES = {
    "data_centers": [
        "data center load",
        "data center power",
        "datacenter",
        "colocation facility",
    ],
    "nuclear": [
        "nuclear reactor",
        "small modular reactor",
        "nuclear power plant",
    ],
    "solar_wind": [
        "solar energy",
        "wind energy",
        "offshore wind",
        "renewable energy standard",
    ],
    "transmission": [
        "transmission line",
        "interconnection queue",
        "grid reliability",
    ],
    "storage": [
        "energy storage",
        "battery storage",
        "long duration storage",
    ],
    "ev_charging": [
        "electric vehicle charging",
        "vehicle to grid",
    ],
}

# LegiScan year param: 1=all sessions, 2=current, 3=current+prior
YEAR_MAP = {"1": 3, "2": 3, "3": 1}  # UI "past N years" → API year param

# One active fetch job at a time
_fetch_lock = threading.Lock()
_fetch_status: dict = {"state": "idle"}


def _run_fetch(state: str, topic: str, years: str, custom_query: str):
    global _fetch_status

    queries = []
    if topic == "custom" and custom_query:
        queries = [custom_query]
    else:
        queries = TOPIC_QUERIES.get(topic, [])

    if not queries:
        _fetch_status = {"state": "error", "message": "No queries for topic"}
        return

    year_param = YEAR_MAP.get(years, 3)
    client = LegiScanClient()

    seen: dict[int, dict] = {}  # bill_id → best hit (highest relevance)
    _fetch_status = {
        "state": "searching",
        "query_done": 0,
        "query_total": len(queries),
        "hits": 0,
    }

    for q in queries:
        try:
            results = client.get_search(q, state, year=year_param)
        except Exception as e:
            _fetch_status["message"] = f"Search failed: {e}"
            continue
        for r in results:
            bid = r.get("bill_id")
            if bid and (bid not in seen or r.get("relevance", 0) > seen[bid].get("relevance", 0)):
                seen[bid] = r
        _fetch_status["query_done"] += 1
        _fetch_status["hits"] = len(seen)

    if not seen:
        _fetch_status = {"state": "done", "new": 0, "skipped": 0, "total_hits": 0}
        return

    _fetch_status = {
        "state": "fetching",
        "bill_done": 0,
        "bill_total": len(seen),
        "summarized": 0,
    }

    new_count = skipped = 0

    for bill_id, hit in seen.items():
        stored_hash  = get_watched_bill_hash(bill_id)
        live_hash    = hit.get("change_hash", "")

        if stored_hash and stored_hash == live_hash:
            skipped += 1
            _fetch_status["bill_done"] += 1
            continue

        try:
            bill = client.get_bill(bill_id)
        except Exception as e:
            _fetch_status["bill_done"] += 1
            continue

        bill_number = bill.get("bill_number", "")
        title       = bill.get("title", "")
        description = bill.get("description", "") or title
        url         = bill.get("url", "")
        session_id  = bill.get("session", {}).get("session_id")
        change_hash = bill.get("change_hash", live_hash)

        upsert_bill(bill_id, state, session_id, bill_number, title,
                    change_hash, bill.get("status", 0),
                    bill.get("last_action", ""), url, description=description)
        upsert_watched_bill(bill_id, state, bill_number, 0, change_hash)

        if has_negative_signal(f"{title} {description}"):
            skipped += 1
            _fetch_status["bill_done"] += 1
            continue

        text   = _fetch_bill_text(client, bill)
        result = summarize(state, bill_number, title, text or description)

        if result is None:
            tags = keyword_tags(f"{title} {description}")
            queue_bill(bill_id, state, bill_number, title,
                       description[:300], tags, 0.5, url)
        else:
            queue_bill(
                bill_id=bill_id, state=state, bill_number=bill_number,
                title=title, summary=result["summary"],
                tags=result["tags"], confidence=result["confidence"], url=url,
            )
            _fetch_status["summarized"] += 1

        new_count += 1
        _fetch_status["bill_done"] += 1

    _fetch_status = {
        "state": "done",
        "new": new_count,
        "skipped": skipped,
        "total_hits": len(seen),
    }


def _fetch_bill_text(client: LegiScanClient, bill: dict):
    from .db import get_doc_hash, upsert_doc
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
            if decoded.count("") / max(len(decoded), 1) > 0.3:
                continue
            upsert_doc(doc_id, bill["bill_id"], doc_hash, "")
            return decoded
        except Exception:
            continue
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _localhost_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        try:
            p = urlparse(origin)
        except ValueError:
            p = None
        if p and p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1"):
            return origin
        return f"http://localhost:{PORT}"

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", self._localhost_origin())
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._localhost_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/legiscan/api/queue":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM queue ORDER BY confidence DESC, state, created_at"
                ).fetchall()
            self._send(200, "application/json", json.dumps([dict(r) for r in rows]))
            return

        if path == "/legiscan/api/fetch/status":
            self._send(200, "application/json", json.dumps(_fetch_status))
            return

        if path == "/legiscan/api/stats":
            from .export import get_export_stats
            from collections import Counter, defaultdict
            with get_conn() as conn:
                rows = conn.execute("SELECT * FROM queue").fetchall()
            bills = [dict(r) for r in rows]
            total    = len(bills)
            pending  = sum(1 for b in bills if b["review_status"] == "pending")
            approved = sum(1 for b in bills if b["review_status"] == "approved")
            rejected = sum(1 for b in bills if b["review_status"] == "rejected")

            by_state = defaultdict(lambda: {"state":"","pending":0,"approved":0,"rejected":0})
            for b in bills:
                s = b["state"]
                by_state[s]["state"] = s
                by_state[s][b["review_status"]] = by_state[s].get(b["review_status"], 0) + 1
            by_state_list = sorted(by_state.values(), key=lambda x: -(x.get("pending",0)+x.get("approved",0)))

            tag_counter: Counter = Counter()
            for b in bills:
                for t in (b["tags"] or "").split(","):
                    if t.strip():
                        tag_counter[t.strip()] += 1
            by_tag = tag_counter.most_common()

            exp = get_export_stats()
            data = {
                "total": total, "pending": pending,
                "approved": approved, "rejected": rejected,
                "by_state": by_state_list, "by_tag": by_tag,
                "in_pipeline": exp["in_pipeline"],
            }
            self._send(200, "application/json", json.dumps(data))
            return

        if path == "/legiscan/api/topics":
            self._send(200, "application/json", json.dumps(list(TOPIC_QUERIES.keys())))
            return

        if path in ("/legiscan/review.html", "/"):
            file_path = HERE / "review.html"
        else:
            try:
                candidate = (HERE / Path(path.lstrip("/"))).resolve()
                if not candidate.is_relative_to(HERE.resolve()):
                    self._send(403, "text/plain", "Forbidden")
                    return
                file_path = candidate
            except Exception:
                self._send(400, "text/plain", "Bad request")
                return
        if file_path.exists() and file_path.is_file():
            ct = "text/html" if file_path.suffix == ".html" else "text/plain"
            self._send(200, ct, file_path.read_bytes())
        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        path   = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if path == "/legiscan/api/review":
            set_review_status(body["id"], body["status"])
            if body.get("summary"):
                update_summary(body["id"], body["summary"])
            self._send(200, "application/json", '{"ok":true}')
            return

        if path == "/legiscan/api/export":
            from .export import export_approved
            try:
                result = export_approved()
                self._send(200, "application/json", json.dumps(result))
            except Exception as e:
                self._send(500, "application/json", json.dumps({"error": str(e)}))
            return

        if path == "/legiscan/api/fetch":
            if not _fetch_lock.acquire(blocking=False):
                self._send(409, "application/json", '{"error":"fetch already running"}')
                return
            state        = body.get("state", "AL")
            topic        = body.get("topic", "data_centers")
            years        = str(body.get("years", "2"))
            custom_query = body.get("custom_query", "")
            t = threading.Thread(
                target=_run_fetch_wrapper,
                args=(state, topic, years, custom_query),
                daemon=True,
            )
            t.start()
            self._send(200, "application/json", '{"ok":true}')
            return

        self._send(404, "text/plain", "Not found")


def _run_fetch_wrapper(state, topic, years, custom_query):
    try:
        _run_fetch(state, topic, years, custom_query)
    finally:
        _fetch_lock.release()


def run():
    init_db()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Review server at http://localhost:{PORT}/legiscan/review.html")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
