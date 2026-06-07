#!/usr/bin/env python3
"""Flask API for the OSINT Energy Security Dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, jsonify, request


def _qint(key: str, default: int, max_val: int | None = None) -> int:
    try:
        n = int(request.args.get(key, default))
    except (ValueError, TypeError):
        n = default
    return min(n, max_val) if max_val is not None else n

from osint_db import get_conn, init_db

app = Flask(__name__)


@app.after_request
def add_cors_headers(response: Any) -> Any:
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    return response


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _asset_feature(row: dict[str, Any]) -> dict[str, Any]:
    properties = dict(row)
    metadata = _parse_json(properties.pop("metadata_json", None))
    lat = properties.pop("lat", None)
    lng = properties.pop("lng", None)
    geometry_wkt = properties.get("geometry_wkt")
    geometry = None
    if lat is not None and lng is not None:
        geometry = {"type": "Point", "coordinates": [lng, lat]}
    return {
        "type": "Feature",
        "id": row["id"],
        "geometry": geometry,
        "properties": {**properties, "metadata": metadata, "geometry_wkt": geometry_wkt},
    }


@app.before_request
def ensure_db() -> None:
    init_db()


@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok", "db": os.environ.get("OSINT_DB_PATH", "osint.db")})


@app.get("/api/assets")
def assets() -> Any:
    asset_type = request.args.get("type")
    state = request.args.get("state")
    limit = _qint("limit", 5000, 25000)

    where = []
    params: list[Any] = []
    if asset_type:
        where.append("type = ?")
        params.append(asset_type)
    if state:
        where.append("state = ?")
        params.append(state.upper())
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
        SELECT * FROM assets
        {clause}
        ORDER BY type, name
        LIMIT ?
    """
    params.append(limit)
    with get_conn() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    return jsonify({"type": "FeatureCollection", "features": [_asset_feature(row) for row in rows]})


@app.get("/api/assets/types")
def asset_types() -> Any:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT type, COUNT(*) as count FROM assets GROUP BY type ORDER BY count DESC"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/grid/current")
def grid_current() -> Any:
    with get_conn() as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT iso, metric, fuel, MAX(timestamp) AS timestamp
                FROM grid_snapshots
                GROUP BY iso, metric, fuel
            )
            SELECT g.iso, g.timestamp, g.metric, g.fuel, g.value, g.unit, g.metadata_json
            FROM grid_snapshots g
            JOIN latest l
              ON g.iso = l.iso
             AND g.metric = l.metric
             AND COALESCE(g.fuel, '') = COALESCE(l.fuel, '')
             AND g.timestamp = l.timestamp
            ORDER BY g.iso, g.metric, g.fuel
            """
        ).fetchall()
    payload: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        item["metadata"] = _parse_json(item.pop("metadata_json", None))
        payload.setdefault(item.pop("iso"), []).append(item)
    return jsonify(payload)


@app.get("/api/incidents")
def incidents() -> Any:
    days = _qint("days", 30)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM incidents
            WHERE date IS NULL OR date >= ?
            ORDER BY date DESC
            LIMIT 1000
            """,
            (since,),
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/news")
def news() -> Any:
    limit = _qint("limit", 20, 100)
    db_path = os.environ.get("DB_PATH", "articles.db")
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, title, url, feed_name, category, published_at, created_at
                FROM articles
                ORDER BY COALESCE(published_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return jsonify([dict(row) for row in rows])
    except Exception as exc:
        return jsonify({"error": str(exc), "articles": []}), 503


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
