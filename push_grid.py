#!/usr/bin/env python3
"""Fetch current ISO fuel-mix data and push it to the curator dashboard API.

Designed to be run by the grid-refresh GitHub Actions workflow, but works
locally too:

    CURATOR_URL=https://your-app.onrender.com INGEST_API_KEY=... python push_grid.py

Exit codes:
    0 — success
    1 — fetch error (gridstatus unavailable for one or more ISOs; rows still pushed)
    2 — push error (curator API unreachable or rejected the request)
"""
from __future__ import annotations

import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    curator_url = os.environ.get("CURATOR_URL", "").rstrip("/")
    ingest_key  = os.environ.get("INGEST_API_KEY", "")

    if not curator_url:
        log.error("CURATOR_URL env var is required")
        return 2
    if not ingest_key:
        log.error("INGEST_API_KEY env var is required")
        return 2

    # Import here so the script fails fast if gridstatus is not installed
    try:
        from fetch_grid import fetch_all
    except ImportError as exc:
        log.error("Could not import fetch_grid: %s — is gridstatus installed?", exc)
        return 2

    log.info("Fetching ISO fuel-mix snapshots…")
    rows = fetch_all()

    if not rows:
        log.warning("No rows returned from any ISO — check gridstatus connectivity")
        return 1

    log.info("Fetched %s rows across all ISOs", len(rows))

    # Serialize: convert any non-JSON-safe values (e.g. numpy floats) before sending
    payload = json.dumps({"rows": rows}, default=str)

    try:
        import urllib.request

        req = urllib.request.Request(
            url=f"{curator_url}/api/osint/grid/ingest",
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "X-API-Key":    ingest_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())

        inserted = body.get("inserted", "?")
        log.info("Curator accepted %s rows", inserted)
        return 0

    except Exception as exc:
        log.error("Push to curator failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
