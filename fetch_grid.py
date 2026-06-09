#!/usr/bin/env python3
"""Fetch current ISO fuel-mix telemetry with gridstatus and store it in osint.db."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from osint_db import get_conn, init_db, insert_grid_snapshots

log = logging.getLogger(__name__)

ISO_CLASSES = {
    "ERCOT": ("gridstatus", "Ercot"),
    "PJM":   ("gridstatus", "PJM"),
    "CAISO": ("gridstatus", "CAISO"),
    "MISO":  ("gridstatus", "MISO"),
    "NYISO": ("gridstatus", "NYISO"),
    "ISONE": ("gridstatus", "ISONE"),
    "SPP":   ("gridstatus", "SPP"),
}

# Map gridstatus internal names to EIA/NERC BA codes (unified keyspace)
ISO_TO_BA = {
    "ERCOT": "ERCO",
    "PJM":   "PJM",
    "CAISO": "CISO",
    "MISO":  "MISO",
    "NYISO": "NYIS",
    "ISONE": "ISNE",
    "SPP":   "SWPP",
}


def _load_iso(class_name: str) -> Any:
    import importlib

    module = importlib.import_module("gridstatus")
    return getattr(module, class_name)()


def _normalize_timestamp(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _fuel_rows_from_dataframe(iso: str, data: Any, fetched_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if data is None:
        return rows

    if hasattr(data, "reset_index"):
        frame = data.reset_index()
        records = frame.to_dict("records")
    elif isinstance(data, list):
        records = data
    else:
        records = [data]

    for record in records:
        if not isinstance(record, dict):
            continue
        timestamp = _normalize_timestamp(
            record.get("Time") or record.get("Interval Start") or record.get("timestamp"),
            fetched_at,
        )
        for key, value in record.items():
            if key in {"Time", "Interval Start", "Interval End", "timestamp", "index"}:
                continue
            if value is None or value == "":
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "region":      ISO_TO_BA.get(iso, iso),
                    "region_type": "iso",
                    "source":      "gridstatus",
                    "timestamp":   timestamp,
                    "metric":      "fuel_mix_mw",
                    "fuel":        str(key).strip(),
                    "value":       numeric,
                    "unit":        "MW",
                    "metadata":    {"fetched_at": fetched_at},
                }
            )
    return rows


def fetch_iso_fuel_mix(iso: str) -> list[dict[str, Any]]:
    """Fetch and normalize current fuel mix for one ISO."""
    _, class_name = ISO_CLASSES[iso]
    fetched_at = datetime.now(timezone.utc).isoformat()
    client = _load_iso(class_name)
    data = client.get_fuel_mix()
    return _fuel_rows_from_dataframe(iso, data, fetched_at)


def fetch_all(selected: list[str] | None = None) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    isos = selected or list(ISO_CLASSES)
    for iso in isos:
        try:
            rows = fetch_iso_fuel_mix(iso)
            all_rows.extend(rows)
            log.info("%s: normalized %s fuel-mix rows", iso, len(rows))
        except Exception as exc:
            log.warning("%s: fuel-mix fetch failed: %s", iso, exc)
    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path; defaults to OSINT_DB_PATH or osint.db")
    parser.add_argument("--iso", action="append", choices=sorted(ISO_CLASSES), help="Limit to one ISO; repeatable")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db(args.db)
    rows = fetch_all(args.iso)
    with get_conn(args.db) as conn:
        inserted = insert_grid_snapshots(conn, rows)
        conn.commit()
    log.info("Inserted %s grid snapshot rows", inserted)


if __name__ == "__main__":
    main()
