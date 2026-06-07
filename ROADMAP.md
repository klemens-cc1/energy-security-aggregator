# Energy Security Map — Project Roadmap

---

## What Exists Today

### RSS Aggregator (`aggregator.py`)
Pulls from multiple energy news feeds on a rolling 7-day lookback. Deduplicates via SQLite, strips HTML from summaries, filters boilerplate, and returns structured article dicts. Feed sources managed in Supabase with `feeds.yaml` fallback.

### Interactive Map (`map/index.html` + `map/data/states.js`)
D3.js v7 standalone map. 21 active states, each with a slide-in panel showing hand-curated legislation (47 bills), governor + chamber party affiliation, and utility market structure (Regulated / Deregulated / Partial). Georgia zoom animation. Shareable single-file version: `map/share.html`.

---

## Phase 1 — Legislative Auto-Feed
*Goal: replace manual bill entry with a monitored, human-reviewed pipeline*

### 1.1 LegiScan Integration

**Initial backfill via Datasets**
- Call `getDatasetList` → download weekly ZIP snapshots for all sessions
- ~1,000 API calls covers all 3.5M records from 2010–2026
- Store `dataset_hash` per session in SQLite — skip download if hash unchanged
- Parse ZIP into local SQLite schema

**Weekly delta loop (~350 calls/week)**
```
Sunday 6am ET (after LegiScan dataset rebuild at 5am):
  1. getDatasetList → check dataset_hash → download only if changed     (~1 call)
  2. getMasterListRaw × 50 states → compare change_hash per bill        (~50 calls)
  3. getBill for changed bills passing title keyword pre-filter          (~200 calls)
  4. getBillText for description-filtered survivors, skip if doc cached  (~100 calls)
```
Steady-state budget: ~1,400 calls/month out of 30,000 free-tier limit.

**Operational rules**
- Always check `status: "OK"` in every JSON response before processing
- Cache all JSON responses locally — never re-fetch unchanged data
- All published outputs must include LegiScan attribution (CC BY 4.0)

### 1.2 Relevance Filtering
- Pre-filter on bill title before calling `getBill` (free, no API spend)
- Score `getBill` description against keyword set: `energy`, `nuclear`, `utility`, `transmission`, `grid`, `solar`, `wind`, `storage`, `data center`, `generation`, `electricity`, `pipeline`, `fuel`
- Reuse boilerplate-filter pattern from `aggregator.py`
- Bills above threshold → summarization queue; borderline → human review queue; below → discard

### 1.3 LLM Summarization
- Fetch full bill text via `getBillText` only after passing relevance filter
- Claude prompt: *"In 1–2 sentences, describe what this bill does and its significance to energy infrastructure or supply security. Classify with one or more tags: nuclear | solar/wind | transmission | storage | data center load | market reform | grid resilience. Return a confidence score (0–1) on relevance."*
- Output: `{ text: "...", url: "...", tags: [...], confidence: 0.0–1.0 }`
- Low-confidence outputs (< 0.7) route to human review regardless of keyword score

### 1.4 Governance Layer
Phase 1.2–1.4 is a governance layer, not just ETL. False positives erode editorial credibility faster than gaps do.

- **Precision target**: maintain a labeled validation sample of ~50 bills; re-run against it whenever prompt or filter logic changes
- **No auto-publish**: bills never land in `states.js` without explicit human approval
- **Rejected bills** stay in SQLite with reason codes — not deleted
- **Review page**: shows title, state, summary, tags, confidence score, link to full text. Actions: Approve / Reject (with reason) / Edit summary. On approval, script merges into `states.js` and regenerates `share.html`

---

## Phase 2 — Analytics
*Goal: surface cross-state patterns, not just per-state facts*

### 2.1 Topic Filter Bar
- Chip filter above the map: All | Nuclear | Transmission | Solar/Wind | Storage | Data Center | Market Reform
- Filters which bills appear in state panels and dims states with no matching bills
- Powered by the `tags` field added in Phase 1.3

### 2.2 Legislative Trend Tracking
- SQLite snapshots of bill counts per state per session
- Panel mini-chart: bills this session vs. last session
- National summary: total tracked bills by topic over time

### 2.3 Market Structure Correlation
- Scatter: x = market structure (Regulated / Partial / Deregulated), y = bill volume by topic
- Highlights whether regulated states cluster on nuclear, deregulated on market reform, etc.

### 2.4 Political Alignment Overlays
- Per-topic bill breakdown by trifecta control (R / D / split)
- Example callout: "11 of 14 nuclear bills are in R-trifecta states"

---

## Phase 3 — Full Dashboard
*Goal: self-updating, hosted, newsletter-integrated product*

### 3.1 Automated Update Pipeline
- GitHub Actions cron (weekly): LegiScan poll → filter → summarize → write `staged_bills.json` → open PR for human review

### 3.2 Export + Newsletter Integration
- "Export state briefing" button: generates markdown summary for selected state
- Output format drops directly into the CITS newsletter curator pipeline

### 3.3 Hosted Deploy
- Vendor `d3.min.js` and `topojson.min.js` locally
- Single deployable directory, no build step — S3 / GitHub Pages ready
- `share.html` generation becomes a CI step

---

## Dependency Map

```
aggregator.py (filter patterns, SQLite dedup, boilerplate rules)
        │
        ▼
LegiScan poller → relevance filter → LLM summarize → staging review → states.js
                                                                           │
                                                                   map/index.html
                                                               (legislation display)
                                                                           │
                                             Phase 2 analytics (tags, trends, correlations)
                                                                           │
                                                          Phase 3 hosted + newsletter
```

---

## Shipping Order

**Slice 1 — Ingestion + human review (no auto-publish)**
- 1.1 LegiScan client + dataset backfill + delta loop
- 1.2 Relevance filter
- 1.3 LLM summarization with confidence scoring
- 1.4 Review page
- *Exit: one full weekly cycle completes; validation sample passes precision target*

**Slice 2 — Limited analytics (precomputed)**
- 2.1 Topic filter bar
- 2.3 Market structure correlation (static, current dataset)
- 2.4 Political alignment strip
- *Exit: filter works across all 50 states; correlation view labeled as preliminary*

**Slice 3 — Trend tracking**
- 2.2 Legislative trend charts
- *Exit: at least two weekly cycles in SQLite; chart handles states with zero bills*

**Slice 4 — Automation + hosted deploy**
- 3.1 GitHub Actions cron + PR review workflow
- 3.2 Newsletter export
- 3.3 Hosted deploy
- *Exit: one full automated cycle end-to-end without manual intervention*
