# OSINT Energy Security Dashboard — Roadmap

---

## What Already Exists (inherit, don't rebuild)

| Asset | File(s) | Role in dashboard |
|---|---|---|
| Legislative intelligence | `legiscan/` + `analyze_dc_bills.py` | Policy layer |
| News/OSINT feed | `aggregator.py` + `feeds.yaml` | Open-source intelligence layer |
| Datacenter inventory | `datacenter_merge.R` + `echo_phase4.R` | Infrastructure layer (partial) |
| LLM enrichment pattern | `analyze_dc_bills.py` (Groq) | Classification/summarization engine |
| Map UI | `map/index.html` | Visualization layer (extend, not replace) |
| EIA API key | `.env` `EIA_API_KEY` | Market/supply signal layer |
| SQLite pattern | `db.py`, `legiscan/db.py` | Unified local store |
| Supabase | `feeds_db.py` | Remote config/sync |

---

## Architecture Target

```
┌─────────────────────────────────────────────────────────┐
│                    osint.db  (SQLite)                   │
│  assets │ grid_snapshots │ incidents │ news │ bills     │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   fetch_hifld.py   fetch_grid.py   fetch_incidents.py
   (infrastructure) (ISO telemetry) (PHMSA/CISA/NERC)
         │               │               │
         └───────────────┴───────────────┘
                         │
                  dashboard/index.html
           (Leaflet map + sidebar panels)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        asset layer           intelligence layer
     (HIFLD + WRI +          (cross-source correlation,
      datacenters)            anomaly alerts, entity flags)
```

---

## Phase 1 — Infrastructure Atlas
*Goal: a unified asset database covering US energy infrastructure*
*Effort: 2–3 days*

### 1.1 Power plant inventory
- **Source**: EIA Form 860 (Annual Electric Generator Report) — free CSV download, authoritative, ~11k plants
- **Script**: `fetch_eia860.py`
  - Download `2___Plant_Y2023.xlsx` from EIA bulk
  - Normalize to: `id, type='power_plant', name, state, county, lat, lng, capacity_mw, fuel_type, operator, owner, status`
  - Insert into `osint.db` table `assets`
- **Also pull**: EIA-923 for actual generation output per plant (tells you which plants are operating vs. dormant)

### 1.2 Transmission + substation layer
- **Source**: HIFLD (Homeland Infrastructure Foundation-Level Data, DHS/ArcGIS) — free GeoJSON download
  - Electric substations: ~55k records, includes owner/operator
  - Electric power transmission lines: polylines with voltage class
  - Natural gas pipelines: ~2,700 pipeline segments
  - LNG export/import terminals: ~50 facilities
- **Script**: `fetch_hifld.py`
  - Download each dataset as GeoJSON (no API key needed, direct URLs)
  - Convert to `assets` rows, preserve geometry as WKT for later map use
  - Flag any asset with foreign-linked operator names for Phase 5

### 1.3 Datacenter integration
- **Source**: existing `datacenter_merged_final.xlsx` from R pipeline
- **Script**: add `seed_assets_from_dc.py` (1-day work, pattern from `seed_from_dcp.py`)
  - Read Excel, write rows into `assets` as `type='data_center'`
  - Preserve EPA ECHO linkage, county MW data, operator

### 1.4 WRI Global Power Plant Database
- **Source**: GitHub `wri/global-power-plant-database` — single CSV, 35k plants worldwide
- Filter to US, dedup against EIA-860 on plant name + lat/lng proximity
- Fills gaps for smaller distributed generation EIA-860 misses

**Exit criterion**: `SELECT type, COUNT(*) FROM assets GROUP BY type` returns plausible numbers for all five asset classes. Map renders dots without crashing.

---

## Phase 2 — Grid Telemetry
*Goal: live generation mix and stress indicators for all major US ISOs*
*Effort: 2–3 days*

### 2.1 gridstatus integration
- **Install**: `pip install gridstatus`
- **Covers**: ERCOT, PJM, CAISO, MISO, NYISO, NEISO, SPP — all 7 major ISOs
- **Script**: `fetch_grid.py`
  ```python
  from gridstatus import Ercot, PJM, CAISO  # etc.
  # Pull: fuel_mix, load_forecast, lmp (locational marginal prices)
  # Store in osint.db: grid_snapshots(iso, timestamp, metric, value)
  ```
- **Schedule**: every 15 minutes via GitHub Actions or local cron
- **Metrics to track**:
  - Generation mix by fuel (gas, coal, nuclear, wind, solar, hydro)
  - Operating reserve margin (alert if < 15%)
  - Net imports/exports between regions
  - Real-time load vs. forecast deviation

### 2.2 EIA weekly reports (already have key)
- **Existing**: `EIA_API_KEY` in `.env`
- **New script**: `fetch_eia_weekly.py`
  - Natural gas in storage (series `NG.NGS_EPG0_SS_NUS_BCF.W`)
  - Crude oil stocks (series `PET.WCRSTUS1.W`)
  - Weekly net generation by fuel (series `ELEC.GEN.*`)
- These are lagging indicators (published Thursday) but useful for trend detection

### 2.3 Anomaly baseline
- After 30 days of snapshots: compute rolling mean + std per ISO per hour-of-week
- Flag deviations > 2σ as anomalies — store in `grid_alerts` table
- Initially rule-based, no ML needed

**Exit criterion**: Dashboard sidebar shows current fuel mix donut charts for all 7 ISOs, updating on page load.

---

## Phase 3 — Incident + Threat Feeds
*Goal: structured incident monitoring across pipeline, grid, cyber, and nuclear domains*
*Effort: 1–2 days*

### 3.1 PHMSA pipeline incidents
- **Source**: PHMSA (Pipeline & Hazardous Materials Safety Administration) bulk download — free CSV
  - Gas distribution, gas transmission, hazardous liquid, LNG
  - ~20k incidents going back to 2002
- **Script**: `fetch_phmsa.py`
  - Download CSVs, normalize, insert into `incidents(id, source, type, date, state, county, operator, commodity, lat, lng, fatalities, injuries, cost_usd, description)`
  - Refresh monthly (PHMSA updates quarterly but releases monthly)

### 3.2 CISA ICS/OT advisories
- **Source**: CISA ICS-CERT RSS feed — zero new infrastructure needed
- **Change**: add entry to `feeds.yaml`:
  ```yaml
  - name: CISA ICS Advisories
    url: https://www.cisa.gov/uscert/ics/advisories/advisories.xml
    category: ics_advisory
  ```
- Existing `aggregator.py` picks it up automatically
- Tag `ics_advisory` articles separately in the dashboard news panel

### 3.3 NERC reliability events
- **Source**: NERC Disturbance Analysis Working Group (DAWG) — annual reports + event database
- Less automatable; download PDF reports annually, parse key events manually into `incidents`
- Automate later with a PDF extractor once volume justifies it

### 3.4 NRC event notifications
- **Source**: NRC Event Notification Reports — available as RSS + searchable web
- Add RSS to `feeds.yaml` with `category: nrc_event`
- Captures: reactor scrams, unusual events, 10 CFR 50.72 notifications

**Exit criterion**: `SELECT source, COUNT(*) FROM incidents GROUP BY source` shows records from PHMSA. CISA + NRC feeds appear in news panel with correct category tags.

---

## Phase 4 — Dashboard UI
*Goal: unified map tying all data layers together*
*Effort: 3–5 days*

### 4.1 Technology choice
- **Keep**: D3.js for the legislative map (it works, don't touch it)
- **New dashboard**: Leaflet.js — far better for multi-layer tile maps with 50k+ points
- **Data serving**: simple Flask API (`dashboard_api.py`) serving JSON from `osint.db`
  - `GET /api/assets?type=power_plant&state=TX` → GeoJSON
  - `GET /api/grid/current` → ISO fuel mix snapshots
  - `GET /api/incidents?days=30` → recent incidents
  - `GET /api/news?limit=20` → recent articles from aggregator

### 4.2 Map layers
- **Base**: OpenStreetMap or Esri satellite toggle
- **Layer toggles** (checkboxes in sidebar):
  - Power plants (dots, colored by fuel type)
  - Substations (triangles, colored by voltage)
  - Pipelines (polylines)
  - Data centers (squares)
  - Incidents — last 90 days (red circles, sized by severity)
  - Legislation — active bills by state (state fill, colored by topic)

### 4.3 Asset detail panel
- Click any asset → right panel slides in:
  - Name, operator, owner, capacity/voltage
  - Any linked incidents within 50 miles in last 12 months
  - Any active legislation in that state matching asset type
  - Recent news mentioning operator name
- This is the core intelligence integration point

### 4.4 Live grid sidebar
- Collapsible left panel showing all 7 ISOs:
  - Fuel mix donut (last snapshot)
  - Reserve margin gauge with red/yellow/green
  - Net import/export arrow indicator
  - Link to ISO's own status page

### 4.5 News + incident strip
- Bottom panel: recent items from aggregator + CISA + NRC + PHMSA
- Each item tagged with source category, clickable to locate on map if geo-tagged
- Filter: All | Infrastructure | Cyber | Nuclear | Pipeline | Policy

**Exit criterion**: All layer toggles work. Clicking a power plant shows its state's active legislation. News strip scrolls and filters. Loads in < 3 seconds on first paint.

---

## Phase 5 — Intelligence Layer
*Goal: surface non-obvious connections; the thing lists and feeds can't show*
*Effort: ongoing*

### 5.1 Cross-source correlation engine
Rule-based initially. When records share entity/location/time proximity, surface the connection:
- Incident in state + active legislation covering that asset type → link them
- News article mentioning operator name + that operator has PHMSA incidents → flag
- CISA advisory for specific ICS vendor + that vendor's equipment at known substations → alert
- Script: `correlate.py` runs nightly, writes to `correlations(entity_a_id, entity_b_id, correlation_type, score, generated_at)`

### 5.2 Entity resolution seed
- **Source**: FERC Form 1 (Annual Report of Major Electric Utilities) — public XML
  - Contains: utility name, parent company, subsidiaries, balance sheets
  - Covers all FERC-jurisdictional utilities
- Build `entities(id, name, aliases[], parent_id, country_of_parent)` table
- Link `assets.operator` to `entities.name` via fuzzy match + manual review for ambiguous cases
- This seeds the ownership graph without scraping

### 5.3 Foreign ownership flags
- Cross-reference `entities.country_of_parent` against OFAC/BIS country lists
- China, Russia, Iran, North Korea → flag asset in UI with warning indicator
- Sources for parent identification: SEC EDGAR (public companies), OpenCorporates API (privates)
- This is semi-automated: generate candidates, require human confirmation before flagging

### 5.4 Grid anomaly alerting
- Once 30-day baseline exists from Phase 2.3:
  - Email/Slack alert when ISO reserve margin < 10%
  - Alert when generation mix shifts > 2σ from hourly baseline
  - Alert when same-day incident + grid stress in same region
- Use existing `emailer.py` infrastructure

---

## Dependency Map

```
aggregator.py (news feed, boilerplate filter, SQLite dedup)
legiscan/ (legislative pipeline, review workflow)
datacenter_merge.R (datacenter inventory, EPA ECHO enrichment)
        │
        ▼
osint.db (unified store)
  assets ← fetch_eia860.py + fetch_hifld.py + seed_assets_from_dc.py
  grid_snapshots ← fetch_grid.py (gridstatus)
  incidents ← fetch_phmsa.py + feeds.yaml (CISA, NRC)
  news ← aggregator.py (unchanged)
  bills ← legiscan/ (unchanged)
  correlations ← correlate.py (Phase 5)
        │
        ▼
dashboard_api.py (Flask, serves JSON to frontend)
        │
        ▼
dashboard/index.html (Leaflet map, layer toggles, panels)
```

---

## First Steps — Week 1

**Day 1 — Environment + first data**
```bash
pip install gridstatus geopandas shapely flask
# Verify gridstatus works:
python -c "from gridstatus import Ercot; print(Ercot().get_fuel_mix())"
```
- Create `osint.db` schema (`osint_db.py`) with `assets`, `grid_snapshots`, `incidents` tables
- Write `fetch_grid.py`: pull current fuel mix for all 7 ISOs, store snapshots

**Day 2 — Power plant inventory**
- Download EIA-860 plant file (manual download, ~5MB Excel)
- Write `fetch_eia860.py`: normalize + insert ~11k US plants into `assets`
- Spot-check: `SELECT state, COUNT(*) FROM assets GROUP BY state ORDER BY 2 DESC LIMIT 10`

**Day 3 — HIFLD infrastructure**
- Write `fetch_hifld.py`: download substations + pipeline GeoJSON, insert into `assets`
- Run `seed_assets_from_dc.py`: merge datacenter Excel into `assets`
- Total asset count should be ~70–80k records across all types

**Day 4 — Incident feeds**
- Write `fetch_phmsa.py`: download + parse gas transmission incident CSV
- Add CISA ICS and NRC RSS entries to `feeds.yaml`
- Verify incidents land in DB and CISA articles appear in aggregator output

**Day 5 — Dashboard scaffold**
- Create `dashboard/index.html` with Leaflet + OpenStreetMap base
- Create `dashboard_api.py` (Flask) with `/api/assets` endpoint
- Drop power plant dots on map, confirm 11k points render without freezing (use clustering)
- Add layer toggle for data centers

**End of week exit check**:
- [ ] `osint.db` has assets, grid snapshots, and PHMSA incidents
- [ ] Map loads and shows power plants + data centers
- [ ] Clicking an asset shows its metadata in a side panel
- [ ] CISA advisories showing up in news feed with correct tag

---

## Shipping Order

| Slice | Deliverable | Exit condition |
|---|---|---|
| **Slice 1** | Infrastructure Atlas | 70k+ assets in DB, visible on map |
| **Slice 2** | Grid Telemetry | 7 ISO fuel mix charts, live on dashboard |
| **Slice 3** | Incident Feeds | PHMSA + CISA + NRC flowing, tagged in UI |
| **Slice 4** | Full Dashboard UI | All layers toggleable, asset detail panel works |
| **Slice 5** | Cross-source correlation | Incidents linked to nearby assets + active bills |
| **Slice 6** | Entity resolution | Operator → parent company for top 100 assets |
| **Slice 7** | Foreign ownership flags | FERC Form 1 parsed, flagged assets visible on map |

---

## What This Does NOT Include (by design)

- **Satellite imagery**: commercial, expensive, no open-source substitute with useful cadence
- **Social media monitoring**: high noise, legal complexity, not worth it for v1
- **Real-time AIS ship tracking**: useful for LNG terminal monitoring but expensive feed; add in v2
- **Full ownership graph**: the 5.2/5.3 work seeds it; a complete graph is a months-long project
- **Predictive modeling**: anomaly detection is statistical baselines, not ML — keep it interpretable
