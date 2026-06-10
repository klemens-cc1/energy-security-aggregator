#!/usr/bin/env python3
"""Fetch EIA-860 power plant records and push to the curator asset ingest endpoint.

Uses the EIA v2 operating-generator-capacity endpoint (monthly, latest period)
to get every operational US generator with lat/lng. Deduplicates to one record
per plant (aggregates capacity; picks dominant fuel = highest nameplate-MW fuel).

Run locally:
    EIA_API_KEY=... CURATOR_URL=https://your-app.onrender.com INGEST_API_KEY=... python push_assets.py

Trigger manually via the assets-refresh GitHub Actions workflow (weekly on Sundays).

Exit codes:
    0 — success
    1 — partial failure (some pages failed; rows still pushed where available)
    2 — fatal (missing env vars, all pages failed, or curator push failed)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EIA_BASE   = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
PAGE_SIZE  = 5000
MIN_CAP_MW = 1.0

FUEL_NAMES: dict[str, str] = {
    "NG":  "Natural Gas",
    "COL": "Coal",
    "BIT": "Bituminous Coal",
    "SUB": "Subbituminous Coal",
    "LIG": "Lignite Coal",
    "NUC": "Nuclear",
    "WAT": "Hydro",
    "SUN": "Solar",
    "WND": "Wind",
    "GEO": "Geothermal",
    "WOO": "Wood / Wood Waste",
    "WDS": "Wood / Wood Waste Solids",
    "WDL": "Wood Liquids",
    "MSW": "Municipal Solid Waste",
    "LFG": "Landfill Gas",
    "BLQ": "Black Liquor",
    "AB":  "Agricultural Byproduct",
    "OBG": "Other Biomass Gas",
    "OBL": "Other Biomass Liquids",
    "OBS": "Other Biomass Solids",
    "DFO": "Distillate Fuel Oil",
    "RFO": "Residual Fuel Oil",
    "JF":  "Jet Fuel",
    "KER": "Kerosene",
    "PC":  "Petroleum Coke",
    "OG":  "Other Gas",
    "PG":  "Propane",
    "SGC": "Syngas / Coal",
    "SGP": "Syngas / Petroleum",
    "OTH": "Other",
    "TDF": "Tire-Derived Fuel",
    "WH":  "Waste Heat",
    "PUR": "Purchased Steam",
    "MWH": "Battery / Storage",
    "H2":  "Hydrogen",
}


def _eia_get(api_key: str, period: str, offset: int) -> dict[str, Any]:
    params = [
        ("api_key",              api_key),
        ("data[0]",              "nameplate-capacity-mw"),
        ("data[1]",              "net-summer-capacity-mw"),
        ("data[2]",              "latitude"),
        ("data[3]",              "longitude"),
        ("data[4]",              "county"),
        ("facets[status][]",     "OP"),
        ("frequency",            "monthly"),
        ("start",                period),
        ("end",                  period),
        ("sort[0][column]",      "nameplate-capacity-mw"),
        ("sort[0][direction]",   "desc"),
        ("length",               PAGE_SIZE),
        ("offset",               offset),
    ]
    qs = "&".join(
        f"{urllib.parse.quote(str(k), safe='[]')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in params
    )
    url = f"{EIA_BASE}?{qs}"
    log.debug("EIA GET offset=%d period=%s", offset, period)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def latest_period(api_key: str) -> str:
    """Return the most recent available period string (YYYY-MM)."""
    now = datetime.now(timezone.utc)
    # EIA typically lags 1-2 months; walk back from last month
    for delta in range(0, 4):
        month = now.month - 1 - delta
        year  = now.year
        while month <= 0:
            month += 12
            year  -= 1
        candidate = f"{year}-{month:02d}"
        try:
            params = [
                ("api_key",   api_key),
                ("data[0]",   "nameplate-capacity-mw"),
                ("facets[status][]", "OP"),
                ("frequency", "monthly"),
                ("start",     candidate),
                ("end",       candidate),
                ("length",    1),
            ]
            qs = "&".join(
                f"{urllib.parse.quote(str(k), safe='[]')}={urllib.parse.quote(str(v), safe='')}"
                for k, v in params
            )
            req = urllib.request.Request(
                f"{EIA_BASE}?{qs}", headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            if body.get("response", {}).get("data"):
                log.info("Using period: %s", candidate)
                return candidate
        except Exception:
            pass
    return f"{now.year}-{max(1, now.month - 2):02d}"


def fetch_all_generators(api_key: str, period: str) -> tuple[dict[str, dict], int]:
    """Return (plantid → aggregated record, exit_code).

    Each generator row is accumulated into its plant: total nameplate capacity
    is summed; the dominant fuel = fuel with highest nameplate-MW contribution.
    """
    plants: dict[str, dict[str, Any]] = {}
    offset    = 0
    total     = None
    exit_code = 0

    while True:
        try:
            body = _eia_get(api_key, period, offset)
        except Exception as exc:
            log.warning("EIA page offset=%d failed: %s", offset, exc)
            exit_code = 1
            break

        response = body.get("response", {})
        if total is None:
            total = int(response.get("total", 0))
            log.info("Total generator records for %s: %d", period, total)

        records = response.get("data", [])
        if not records:
            break

        for rec in records:
            plant_id = str(rec.get("plantid") or "").strip()
            if not plant_id:
                continue

            lat_raw = rec.get("latitude")
            lng_raw = rec.get("longitude")
            try:
                lat = float(lat_raw) if lat_raw else None
                lng = float(lng_raw) if lng_raw else None
            except (TypeError, ValueError):
                lat = lng = None
            if lat is None or lng is None:
                continue

            raw_cap = rec.get("nameplate-capacity-mw")
            try:
                cap = float(raw_cap) if raw_cap is not None else 0.0
            except (TypeError, ValueError):
                cap = 0.0
            if cap < MIN_CAP_MW:
                continue

            fuel_code = str(rec.get("energy_source_code") or "").strip()
            fuel_name = FUEL_NAMES.get(fuel_code, fuel_code) or fuel_code

            if plant_id not in plants:
                plants[plant_id] = {
                    "id":          f"eia860_{plant_id}",
                    "source":      "eia860",
                    "source_id":   plant_id,
                    "type":        "power_plant",
                    "name":        str(rec.get("plantName") or "Unknown Plant"),
                    "state":       str(rec.get("stateid") or "").upper()[:2] or None,
                    "county":      rec.get("county") or None,
                    "lat":         lat,
                    "lng":         lng,
                    "capacity_mw": 0.0,
                    "fuel_type":   None,
                    "_dom_cap":    0.0,  # cap of dominant fuel (internal)
                    "operator":    rec.get("entityName") or None,
                    "status":      "operational",
                    "metadata":    {
                        "balancing_authority": rec.get("balancing_authority_code") or None,
                        "sector":              rec.get("sectorName") or None,
                        "period":              period,
                    },
                }

            plant = plants[plant_id]
            plant["capacity_mw"] = round(plant["capacity_mw"] + cap, 2)

            if cap > plant["_dom_cap"]:
                plant["_dom_cap"]  = cap
                plant["fuel_type"] = fuel_name

        offset += PAGE_SIZE
        log.info("Processed offset %d / %d → %d unique plants",
                 offset, total or "?", len(plants))

        if total is not None and offset >= total:
            break

    return plants, exit_code


def push_assets(curator_url: str, ingest_key: str, assets: list[dict]) -> None:
    batch_size    = 500
    total_upserted = 0

    for i in range(0, len(assets), batch_size):
        batch   = assets[i : i + batch_size]
        payload = json.dumps({"assets": batch}, default=str).encode()
        req = urllib.request.Request(
            url=f"{curator_url}/api/osint/assets/ingest",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key":    ingest_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
        upserted = body.get("upserted", 0)
        total_upserted += upserted
        log.info("Batch %d–%d: %d upserted", i + 1, i + len(batch), upserted)

    log.info("Done. Total upserted: %d", total_upserted)


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

    period = latest_period(api_key)
    log.info("Fetching EIA-860 generators for period %s…", period)

    plants_dict, exit_code = fetch_all_generators(api_key, period)

    if not plants_dict:
        log.error("No plants fetched — check EIA_API_KEY and API availability")
        return 2

    # Strip internal-only keys before sending
    assets = [
        {k: v for k, v in plant.items() if not k.startswith("_")}
        for plant in plants_dict.values()
        if plant.get("capacity_mw", 0) >= MIN_CAP_MW
    ]
    log.info("Pushing %d unique plants to curator…", len(assets))

    try:
        push_assets(curator_url, ingest_key, assets)
    except Exception as exc:
        log.error("Push failed: %s", exc)
        return 2

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
