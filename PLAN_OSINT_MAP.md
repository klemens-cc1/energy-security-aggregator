# OSINT Energy Security Map — Plan

Status: design agreed, not yet built. Date: 2026-06-08.

## 1. Repo and project context

Two GitHub repos, kept separate:

- **aggregator** (`klemens-cc1/energy-security-aggregator`, local `c:\Users\wells\VSprojects26\energy-security-aggregator`): data-fetch and data-push scripts, GitHub Actions crons. Holds `push_grid.py`, `fetch_grid.py`, `.github/workflows/grid-refresh.yml`, the datacenter pipeline (`datacenter_merge.R`, `echo_phase4.R`), the LegiScan bill pipeline (`legiscan/`), `feeds.yaml`, `aggregator.py`.
- **curator** (`klemens-cc1/cits-newsletter-curator`, local `c:\Users\wells\VSprojects26\cits-newsletter-curator`): the Flask app hosted on Render (Gunicorn -> Flask -> Flask-SQLAlchemy -> psycopg2/PostgreSQL). Hosts the dashboard and the API. Key files: `app.py` (`create_app()`, `db.create_all()`, `_init_db()` retry, `_run_migrations()`), `osint_models.py`, `osint_routes.py` (Blueprint `osint_bp`, routes under `/api/osint/*` and `/dashboard`), `templates/dashboard.html`, `models.py` (existing `Article` table), `routes.py` (existing, untouched).

Data flow already built: gridstatus runs in aggregator GH Actions -> `push_grid.py` -> `POST /api/osint/grid/ingest` (auth via `INGEST_API_KEY` header `X-API-Key`) -> PostgreSQL `osint_grid_snapshots` -> `GET /api/osint/grid/current` -> dashboard. CISA/NRC RSS feeds flow into the `Article` table, surfaced via `/api/osint/news`.

Resources available: active EIA v2 API key (`.env` `EIA_API_KEY`). Render free tier (ephemeral filesystem, so SQLite does not persist; PostgreSQL is the store).

## 2. Concept (reframed)

The dashboard is a **compiler**, not an analysis engine. It fuses authoritative existing datasets onto one geographic canvas, liveuamap-style, with a policy layer no other energy OSINT site has. Charts display data; they never infer, score, or predict. Do not build ML, scoring, anomaly detection, prediction, a data warehouse, or generic ETL.

Reference model: liveuamap.com (time-ordered, geolocated, sourced event markers with a feed synced to the map). The delta vs liveuamap: add physical infrastructure base layers and a policy layer, plus cross-references between the three.

### Three planes on one map

1. **Infrastructure** (static-ish base layers, refreshed weekly/monthly): power plants, substations, transmission lines, pipelines, datacenters, terminals.
2. **Live events** (time-ordered feed synced to map, near-real-time/hourly): grid alerts, incidents, advisories, outages, disturbances.
3. **Policy** (the differentiator, daily): bills, dockets, siting decisions, incentives, tied to geography.

The product value is the **intersection** of the planes. Example walk: ISO grid alert (plane 2) -> toggle datacenter layer to see load clusters driving it (plane 1) -> side panel surfaces state bills responding to datacenter load (plane 3).

Killer queries the policy plane unlocks (all lean on assets already owned): datacenter load vs grid constraint vs legislative response; interconnection-reform rhetoric (LegiScan bills) vs reality (LBNL queue backlog); incident -> regulatory aftermath; foreign ownership (`foreign_link_flag` on assets) + FOCI legislation.

## 3. Four design decisions (agreed)

1. **Policy plane**: scaffold the toggle, panel, and data contract, but leave it DARK — no live cross-links until the user supplies a clean, accurate legislative dataset. Do NOT link the existing merged datacenter "chimera" dataset into the policy plane.
2. **Feed**: fully automatic from official sources, no human review gate. Source authority is the verification.
3. **Datacenter layer**: consume the published datacenter ATLAS dataset read-only as a swappable layer. Keep projects separate. The user may later build a clean, sourced Georgia-only layer; keep the layer swappable so it can drop in without touching anything else.
4. **Live-grid backbone: HYBRID** (detail in section 6).

## 4. Dataset inventory (authoritative sources only; clear provenance per layer)

Plane 1 — Infrastructure:
- Power plants/generators: EIA-860 + 860M (bulk).
- Substations, transmission lines, pipelines, terminals: EIA US Energy Atlas (cleanest single source) + HIFLD (bulk geo layers).
- Datacenters: existing atlas output (read-only, swappable).
- Interconnection queue: LBNL "Queued Up" (annual).
- Nuclear plants: NRC.

Plane 2 — Live events:
- ISO fuel mix/load/prices: gridstatus (already wired).
- Hourly demand/generation/interchange by balancing authority: EIA Hourly Electric Grid Monitor / EIA-930 v2 API (key in hand).
- Electric disturbances: DOE OE-417.
- Grid emergency alerts: NERC EEA / ISO conservation appeals.
- Pipeline incidents: PHMSA (planned `fetch_phmsa.py`).
- Nuclear events: NRC RSS (in feeds.yaml).
- ICS/cyber advisories: CISA RSS (in feeds.yaml).
- Weather threats: NWS/NOAA CAP alerts.
- Outages: poweroutage.us-style aggregate.

Plane 3 — Policy:
- State legislation: LegiScan pipeline (exists).
- Federal rulemaking: Regulations.gov API.
- Federal bills: Congress.gov API.
- FERC dockets: FERC eLibrary.
- Datacenter incentives/policy: existing data.

## 5. Phasing

- **P0 Foundation** (mostly done): map shell, layer registry, feed↔map sync. Missing primitive: a synced time-ordered feed as a first-class component (current dashboard only has a news strip).
- **P1 Infrastructure plane**: seed EIA Atlas geo layers, EIA-860, datacenter atlas as a layer, LBNL queue. (`fetch_eia860.py`, `fetch_hifld.py`, `seed_assets_from_dc.py`, scoped to layers.)
- **P2 Live event feed**: unify temporal sources into one geolocated, deduplicated, time-ordered stream synced to map. EIA-930 backbone first, gridstatus overlay. Add PHMSA, DOE OE-417, NERC, NWS alongside existing RSS.
- **P3 Policy plane** (dark until clean data): geocode LegiScan output to states; render togglable plane with bill detail + cross-links to infra/events; add Regulations.gov + Congress.gov.
- **P4 Intersection panels + d3 contextual charts**: region/state panels tying all three planes; charts display authoritative data only.
- **P5 Polish**: timeline scrubber (replay last 30 days), provenance UI, shareable/embeddable views.

Scope guardrails: US-only; no ML/scoring/prediction; no data warehouse/generic ETL; no manual feed curation.

## 6. Live-grid backbone: hybrid design (P2 detail)

### Rationale

- **gridstatus** pulls each ISO's own operational feeds. Covers only the 7 organized markets (ERCOT, PJM, CAISO, MISO, NYISO, ISONE, SPP), ~2/3 of US load. High fidelity: 5-min fuel mix, nodal/zonal LMP prices, load. Heavier dependency (lib pinned `gridstatus==0.31.0`, breaks when ISO endpoints change). No API key.
- **EIA-930** (Hourly Electric Grid Monitor, v2 API) serves data every US balancing authority reports to EIA. Covers ALL ~60+ Lower-48 BAs including the Southeast (Georgia/Southern Co., TVA, Florida) and non-CAISO West, which gridstatus cannot see. Lower fidelity: hourly only, ~1hr+ lag, data preliminary/revised, broad fuel categories, no prices. Single stable REST API + one key.
- Decisive factor: gridstatus alone leaves the entire Southeast (incl. Georgia, which the user cares about) as a dead zone. EIA-930 closes it.

### Hybrid

EIA-930 = national backbone (every BA, the base-map pulse). gridstatus = high-fidelity overlay for the 7 ISOs. Both already available; additive.

### Key insight enabling a clean merge

The 7 ISOs ARE balancing authorities in EIA's taxonomy: ERCOT=`ERCO`, CAISO=`CISO`, PJM=`PJM`, MISO=`MISO`, NYISO=`NYIS`, ISO-NE=`ISNE`, SPP=`SWPP`. Unify on a single `region` = BA-code key plus a `source` discriminator. For those 7 regions both an hourly EIA-930 row and a 5-min gridstatus row are held.

### Unified row shape (data contract)

Both `push_grid.py` (gridstatus) and a new `push_eia930.py` emit this identical shape; the frontend never learns which backend produced a row.

```jsonc
{
  "region":      "ERCO",                       // BA code — canonical key
  "region_type": "iso",                        // "iso" | "ba"  (styling/grouping hint)
  "source":      "gridstatus",                 // "gridstatus" | "eia930"
  "timestamp":   "2026-06-08T14:00:00+00:00",  // ISO8601 UTC
  "metric":      "fuel_mix_mw",                // shared vocabulary (below)
  "fuel":        "Natural Gas",                // canonical fuel; "" for non-fuel metrics
  "value":       41234.5,
  "unit":        "MW",
  "metadata":    {}                            // source-specific extras
}
```

### Shared metric vocabulary

| metric | fuel field | source(s) | meaning |
|---|---|---|---|
| `demand` | `''` | both | actual demand (MW) |
| `demand_forecast` | `''` | EIA-930 | day-ahead forecast (MW) |
| `net_generation` | `''` | both | total net generation (MW) |
| `interchange` | `''` | both | net total interchange (+ = export) |
| `interchange_directional` | `''` | EIA-930 | BA->neighbor flow; `metadata={"neighbor":"SWPP"}` for map arrows |
| `fuel_mix_mw` | populated | both | generation by fuel |
| `lmp` | `''` | gridstatus | price $/MWh; `metadata={"location":"HB_HOUSTON"}` |

### Fuel normalization (both sources -> one legend)

Normalize into the dashboard's existing `FUEL_COLORS` canonical set (Natural Gas, Coal, Nuclear, Wind, Solar, Hydro, Battery, Other, Oil).

```
EIA-930 codes:  COL->Coal  NG->Natural Gas  NUC->Nuclear  OIL->Oil
                WAT->Hydro  SUN->Solar  WND->Wind  OTH->Other
gridstatus:     ISO-native names -> same canonical set
```

### Storage: evolve `osint_grid_snapshots` (do NOT add a sibling table)

Current schema (in `osint_models.py`, `OsintGridSnapshot`):
```
id PK; iso String(16) NOT NULL; timestamp DateTime NOT NULL; metric String(64) NOT NULL;
fuel String(64) NOT NULL default ''; value Float NOT NULL; unit String(16); metadata_json Text NOT NULL '{}';
created_at DateTime NOT NULL. UniqueConstraint(iso, timestamp, metric, fuel) name uq_osint_grid_snapshot.
```
Note: `fuel` is NOT NULL default '' deliberately, because PostgreSQL treats NULL != NULL in unique indexes (NULL fuels would not collide). Keep this.

Evolved schema:
```
osint_grid_snapshots
  id            PK
  region        String(16)  NOT NULL        # renamed from iso
  region_type   String(8)   NOT NULL ''      # 'iso' | 'ba'   (new)
  source        String(16)  NOT NULL ''      # 'gridstatus' | 'eia930'  (new)
  timestamp     DateTime    NOT NULL
  metric        String(64)  NOT NULL
  fuel          String(64)  NOT NULL ''
  value         Float       NOT NULL
  unit          String(16)
  metadata_json Text        NOT NULL '{}'
  created_at    DateTime    NOT NULL
  UNIQUE(region, source, timestamp, metric, fuel)   # source added so both feeds coexist
```

### Ingest endpoint — backward compatible

`/api/osint/grid/ingest` accepts the new fields with a shim so existing `push_grid.py` keeps working during transition:
```
if row has "iso" and no "region":  region = iso; source = source or "gridstatus"; region_type = "iso"
```
The dialect-aware upsert (PostgreSQL `INSERT ... ON CONFLICT (...) DO NOTHING`; SQLite `INSERT OR IGNORE`) gains `source` and `region_type` in the column list and the conflict target.

### Query endpoint — filters for two UI surfaces

`/api/osint/grid/current` gains optional filters; same unified shape grouped by `region`:
| Call | Serves |
|---|---|
| `?source=eia930` | national pulse — every BA, for the choropleth base layer |
| `?region=ERCO` | everything for ERCOT (both sources); detail panel prefers `gridstatus` rows |
| `?metric=interchange_directional` | flow arrows |

The base-map pulse uses EIA-930 (national); the ISO detail panel uses gridstatus. The frontend wants both, for different surfaces — so the API exposes both, tagged by `source`, rather than picking one server-side.

### Region geometry (static asset, not a DB table)

EIA-930 is keyed by BA code, so the map needs BA territory polygons. EIA/HIFLD publish balancing-authority boundary shapefiles -> convert once to a static `ba_regions.geojson` keyed by BA code, served as a frontend asset for the national choropleth/pulse.

### Refresh

New workflow `eia930-refresh.yml` in aggregator, hourly cron offset from the gridstatus one (e.g. `30 * * * *`), runs a new `push_eia930.py` that hits the EIA v2 API with `EIA_API_KEY` and POSTs to the same `/api/osint/grid/ingest` with `source=eia930`. Reuses `INGEST_API_KEY`. No new auth. EIA-930 v2 endpoints to pull: `region-data` (demand D, demand forecast DF, net generation NG, total interchange TI), `fuel-type-data` (net generation by energy source), `interchange-data` (BA-to-BA flows).

## 7. Open sub-decisions (settle before coding P2 backbone)

1. **`iso` -> `region` rename**: table is new with little/no data, so a clean rename now is cheap (one migration: add `region`/`region_type`/`source`, backfill `region` from `iso`, drop `iso`, swap the unique constraint). Recommended: rename now. Alternative is to keep the column named `iso` holding BA codes (misleading). UNDECIDED.
2. **Retention**: EIA-930 adds ~800 rows/hour (~19k/day) on top of gridstatus; compounds on free-tier Postgres. The `current` query only needs the latest snapshot per region/metric/fuel. Proposed policy: periodic prune keeping raw hourly for 30–90 days. UNDECIDED whether in scope now or deferred.

## 8. External review reconciliation (2026-06-08)

An external LLM review was run against stale context (the dev-only standalone SQLite scaffolding `osint_db.py` + `dashboard_api.py` reading `articles.db`, and `ROADMAP_OSINT.md`) — not the production curator path (`osint_models.py`/`osint_routes.py`, PostgreSQL) or this plan. Triage below.

### Adopt into v1

- **Native GeoJSON for non-point geometry (P1-critical).** Current `OsintAsset.to_geojson_feature()` / standalone `_asset_feature()` only emit a `Point` when lat/lng exist and dump WKT into properties otherwise. Transmission lines and pipelines require native `LineString`/`MultiLineString` (polygons for some substations/terminals). Contract: store/materialize canonical geometry as GeoJSON, return valid GeoJSON geometry for all types, add a `geometry_type` field, never require the browser to parse WKT. Add display-simplified geometry for heavy line layers.
- **Assets API scale filters.** Add `bbox=minLng,minLat,maxLng,maxLat`, `limit`, `offset` (or cursor), `fields=basic|detail`, `updated_since=ISO-8601`. Needed when substations/lines land (tens of thousands of features).
- **Unique index `(source, source_id)`** on `osint_assets` where `source_id` is not null — prevents two ingest scripts minting different canonical IDs for the same source record.
- **Controlled vocabularies** for `asset.type` {power_plant, substation, transmission_line, pipeline, lng_terminal, data_center, nuclear_plant} and `status`. Fuel + metric vocab already defined (section 6). Keep raw source values in `metadata_json`.
- **Provenance fields** — add `source_url` and `source_updated_at` to assets/incidents (source, source_id, created_at already present).
- **Foreign-ownership posture** — keep `foreign_link_flag` stored but do NOT render an alarming auto-badge in v1; treat as review-gated, display only confirmed. Consistent with the dark policy plane (decision 1).
- **Enforce ISO-8601 UTC on all ingest timestamps** (already in the grid contract; extend to incidents/assets). Production columns are typed `DateTime` in PostgreSQL so `MAX(timestamp)` is chronological; lexicographic risk only exists in the dev-only SQLite scaffolding.

### Bug found

- Incidents "recent" endpoints use `WHERE date IS NULL OR date >= :since` (`osint_routes.py`, `dashboard_api.py`) → undated incidents appear in the recent window forever. Fix: exclude NULL dates from the recent window. Low urgency (no incidents ingested yet).

### Backlog (post-v1, P4–P5)

Source-freshness panel (last successful ingest per source; high trust value, low cost — do early in P4); provenance "why am I seeing this?" drawer on the detail panel; precomputed state/county/ISO summary endpoints; user watchlist (operators/states/types) highlighting; data-quality badges (exact/approx location, stale, unverified, source conflict).

### Already solved (reviewer stale context)

- News split: production `/api/osint/news` already reads the `Article` table — no `osint.db`/`articles.db` split. The split exists only in the dev-only standalone files.
- Null-fuel dedup: production `OsintGridSnapshot.fuel` is already `NOT NULL default ''` (the exact fix suggested).
- grid_snapshots too generic: P2 contract already adds `region`/`source`/`region_type`; LMP interval/location go in metadata keys (`location_id`, `location_type`, `interval_start_utc`, `interval_end_utc`, `market`).
- Partial ISO coverage: the EIA-930 hybrid backbone (section 6) is the answer to this hole.

### Declined for v1 (scope guardrail)

- Canonical-assets vs source-observations two-table model. The compiler approach uses one authoritative source per layer (EIA-860 plants, HIFLD substations/lines, atlas datacenters) with minimal overlap, so multi-source conflict resolution is not a v1 problem and conflicts with the "no data warehouse" guardrail. The contract retains `source`/`source_id` so the split remains possible later; defer it.

## 9. Security notes (already-fixed patterns to preserve)

Recent fixes on these files, keep the patterns:
- Dashboard templates: all DOM built via `createElement`/`textContent`/`replaceChildren` and a `_mkEl` helper — no `innerHTML` with API data. URL scheme validated before setting `href`. Applies to `renderNews()`, `loadGrid()`, `loadIncidents()` Leaflet popups, `showDetail()`.
- `osint_routes.py` and `dashboard_api.py`: query-int params parsed via `_qint()` (try/except, default, max cap) — never raw `int(request.args...)`.
- `legiscan/review_server.py`: file serving confined via `Path.resolve()` + `is_relative_to(HERE)`; CORS restricted to exact loopback hostnames via `urlparse` + `p.hostname in ("localhost","127.0.0.1","::1")` (not `startswith`).
- `app.py`: DB exception messages sanitized before logging via `_safe_exc()` regex stripping `://user:pass@`; retry warnings log only `type(exc).__name__`.
