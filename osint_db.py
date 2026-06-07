#!/usr/bin/env python3
"""SQLite schema and helpers for the OSINT energy security dashboard."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH = os.environ.get("OSINT_DB_PATH", "osint.db")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open an OSINT SQLite connection with row dict access and FK checks."""
    path = Path(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | os.PathLike[str] | None = None) -> None:
    """Create dashboard tables and indexes if they do not already exist."""
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT,
                type TEXT NOT NULL,
                name TEXT,
                state TEXT,
                county TEXT,
                lat REAL,
                lng REAL,
                geometry_wkt TEXT,
                capacity_mw REAL,
                fuel_type TEXT,
                operator TEXT,
                owner TEXT,
                status TEXT,
                voltage_kv REAL,
                metadata_json TEXT DEFAULT '{}',
                foreign_link_flag INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_assets_type_state ON assets(type, state);
            CREATE INDEX IF NOT EXISTS idx_assets_location ON assets(lat, lng);
            CREATE INDEX IF NOT EXISTS idx_assets_operator ON assets(operator);

            CREATE TABLE IF NOT EXISTS grid_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iso TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                metric TEXT NOT NULL,
                fuel TEXT,
                value REAL NOT NULL,
                unit TEXT,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(iso, timestamp, metric, fuel)
            );

            CREATE INDEX IF NOT EXISTS idx_grid_current ON grid_snapshots(iso, metric, timestamp);

            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT,
                type TEXT,
                date TEXT,
                state TEXT,
                county TEXT,
                operator TEXT,
                commodity TEXT,
                lat REAL,
                lng REAL,
                fatalities INTEGER,
                injuries INTEGER,
                cost_usd REAL,
                description TEXT,
                metadata_json TEXT DEFAULT '{}',
                updated_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_incidents_source_date ON incidents(source, date);
            CREATE INDEX IF NOT EXISTS idx_incidents_location ON incidents(lat, lng);
            CREATE INDEX IF NOT EXISTS idx_incidents_state_type ON incidents(state, type);

            CREATE TABLE IF NOT EXISTS grid_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iso TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                metric TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                value REAL,
                threshold REAL,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()


def _json_dumps(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True, default=str)


def upsert_asset(conn: sqlite3.Connection, asset: dict[str, Any]) -> None:
    """Insert or update a normalized infrastructure asset row."""
    values = {
        "id": asset["id"],
        "source": asset.get("source", "manual"),
        "source_id": asset.get("source_id"),
        "type": asset["type"],
        "name": asset.get("name"),
        "state": asset.get("state"),
        "county": asset.get("county"),
        "lat": asset.get("lat"),
        "lng": asset.get("lng"),
        "geometry_wkt": asset.get("geometry_wkt"),
        "capacity_mw": asset.get("capacity_mw"),
        "fuel_type": asset.get("fuel_type"),
        "operator": asset.get("operator"),
        "owner": asset.get("owner"),
        "status": asset.get("status"),
        "voltage_kv": asset.get("voltage_kv"),
        "metadata_json": _json_dumps(asset.get("metadata")),
        "foreign_link_flag": int(bool(asset.get("foreign_link_flag", False))),
        "updated_at": asset.get("updated_at") or utc_now_iso(),
    }
    columns = ", ".join(values)
    placeholders = ", ".join(f":{key}" for key in values)
    update_cols = ", ".join(
        f"{key}=excluded.{key}" for key in values if key not in {"id", "created_at"}
    )
    conn.execute(
        f"""
        INSERT INTO assets ({columns}) VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {update_cols}
        """,
        values,
    )


def insert_grid_snapshots(
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, Any]],
) -> int:
    """Insert grid telemetry rows, ignoring exact duplicate samples."""
    count = 0
    for row in rows:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO grid_snapshots
                (iso, timestamp, metric, fuel, value, unit, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["iso"],
                row["timestamp"],
                row["metric"],
                row.get("fuel"),
                row["value"],
                row.get("unit"),
                _json_dumps(row.get("metadata")),
            ),
        )
        count += cursor.rowcount if cursor.rowcount > 0 else 0
    return count


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
