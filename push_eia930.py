#!/usr/bin/env python3
"""Fetch EIA-930 Hourly Electric Grid Monitor data and push to the curator ingest endpoint.

Covers all ~60+ Lower-48 balancing authorities including the Southeast/Georgia
regions not served by organized ISO markets (and thus absent from gridstatus).

Run via eia930-refresh GitHub Actions workflow (30 * * * *), or locally:

    EIA_API_KEY=... CURATOR_URL=https://your-app.onrender.com INGEST_API_KEY=... python push_eia930.py

Exit codes:
    0 — success
    1 — partial fetch failure (some rows still pushed)
    2 — fatal (missing env vars or curator push failed)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EIA_BASE = "https://api.eia.gov/v2/electricity/rto"

# EIA fuel-type codes → display names (matches gridstatus fuel names where possible)
FUEL_DISPLAY = {
    "COL": "Coal",
    "NG":  "Natural Gas",
    "NUC": "Nuclear",
    "OIL": "Oil",
    "OTH": "Other",
    "SUN": "Solar",
    "WAT": "Hydro",
    "WND": "Wind",
    "GEO": "Geothermal",
    "BIO": "Biomass",
    "PS":  "Pumped Storage",
    "UNK": "Unknown",
}

# EIA region-data type codes → metric names in the unified vocabulary
REGION_METRIC = {
    "D":  "demand_mwh",
    "DF": "demand_forecast_mwh",
    "NG": "net_gen_mwh",
    "TI": "interchange_mwh",
}


def _eia_get(path: str, params: list[tuple]) -> dict:
    query = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}"
        for k, v in params
    )
    url = f"{EIA_BASE}/{path}?{query}"
    log.debug("EIA GET %s", url)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _period_to_iso(period: str) -> str:
    """Convert EIA period 'YYYY-MM-DDThh' to a full ISO 8601 UTC timestamp."""
    try:
        dt = datetime.strptime(period, "%Y-%m-%dT%H")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return period + ":00:00+00:00"


def fetch_fuel_mix(api_key: str, start: str, end: str) -> list[dict]:
    """Fetch fuel-type-data for all BAs in [start, end] (hour-precision window)."""
    params = [
        ("api_key",            api_key),
        ("frequency",          "hourly"),
        ("data[0]",            "value"),
        ("start",              start),
        ("end",                end),
        ("sort[0][column]",    "period"),
        ("sort[0][direction]", "desc"),
        ("length",             10000),
    ]
    result = _eia_get("fuel-type-data/data", params)
    records = result.get("response", {}).get("data", [])

    rows = []
    for rec in records:
        raw_value = rec.get("value")
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        fueltype = rec.get("fueltype", "")
        rows.append({
            "region":      rec["respondent"],
            "region_type": "ba",
            "source":      "eia930",
            "timestamp":   _period_to_iso(rec["period"]),
            "metric":      "fuel_mix_mwh",
            "fuel":        FUEL_DISPLAY.get(fueltype, fueltype),
            "value":       value,
            "unit":        "MWh",
        })
    return rows


def fetch_region_data(api_key: str, start: str, end: str) -> list[dict]:
    """Fetch demand, net generation, and interchange for all BAs."""
    params = [
        ("api_key",            api_key),
        ("frequency",          "hourly"),
        ("data[0]",            "value"),
        ("start",              start),
        ("end",                end),
        ("sort[0][column]",    "period"),
        ("sort[0][direction]", "desc"),
        ("length",             10000),
    ]
    result = _eia_get("region-data/data", params)
    records = result.get("response", {}).get("data", [])

    rows = []
    for rec in records:
        rtype = rec.get("type", "")
        metric = REGION_METRIC.get(rtype)
        if not metric:
            continue
        raw_value = rec.get("value")
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        rows.append({
            "region":      rec["respondent"],
            "region_type": "ba",
            "source":      "eia930",
            "timestamp":   _period_to_iso(rec["period"]),
            "metric":      metric,
            "fuel":        "",
            "value":       value,
            "unit":        "MWh",
        })
    return rows


def main() -> int:
    api_key     = os.environ.get("EIA_API_KEY", "")
    curator_url = os.environ.get("CURATOR_URL", "").rstrip("/")
    ingest_key  = os.environ.get("INGEST_API_KEY", "")

    if not api_key:
        log.error("EIA_API_KEY env var is required")
        return 2
    if not curator_url:
        log.error("CURATOR_URL env var is required")
        return 2
    if not ingest_key:
        log.error("INGEST_API_KEY env var is required")
        return 2

    # Fetch the past 2 hours so we catch the most recent complete hour even
    # when EIA reporting lags by 60-90 minutes.
    now   = datetime.now(timezone.utc)
    end   = now.strftime("%Y-%m-%dT%H")
    start = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H")

    log.info("Fetching EIA-930 data for %s – %s UTC", start, end)

    rows: list[dict] = []
    exit_code = 0

    try:
        fuel_rows = fetch_fuel_mix(api_key, start, end)
        rows.extend(fuel_rows)
        log.info("Fuel-mix: %d rows", len(fuel_rows))
    except Exception as exc:
        log.warning("Fuel-mix fetch failed: %s", exc)
        exit_code = 1

    try:
        region_rows = fetch_region_data(api_key, start, end)
        rows.extend(region_rows)
        log.info("Region-data: %d rows", len(region_rows))
    except Exception as exc:
        log.warning("Region-data fetch failed: %s", exc)
        exit_code = 1

    if not rows:
        log.warning("No EIA-930 rows fetched — check EIA_API_KEY and API availability")
        return 1

    log.info("Pushing %d total rows to curator", len(rows))
    payload = json.dumps({"rows": rows}, default=str)

    try:
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
        log.info("Curator accepted %s rows", body.get("inserted", "?"))
        return exit_code
    except Exception as exc:
        log.error("Push to curator failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
