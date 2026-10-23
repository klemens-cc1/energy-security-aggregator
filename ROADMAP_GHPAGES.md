# Roadmap — Move the RSS aggregator + newsletter triage to GitHub Pages

> Drafted 2026-10-09. Scope: the newsletter flow only (feeds → triage → export).
> Research and History search stay on Render for now.

---

## Why

The newsletter flow currently needs three services to be awake at once:

```
GitHub Actions (aggregator) ──POST /api/ingest──▶ Render (Flask) ──▶ Supabase (Postgres)
                                                       ▲
                                         browser triage (/newsletter)
```

Every link has broken recently: Supabase pauses after a week idle, Render free tier
cold-starts and was crash-looping, and `CURATOR_URL` silently pointed at a dead
service for months because a failed push is logged as "non-fatal" and the run
still goes green.

Target:

```
GitHub Actions (aggregator) ──commit JSON──▶ repo /data ──served by──▶ GitHub Pages (static triage UI)
                                                  ▲                              │
                                                  └──── commit triage JSON ◀─────┘  (GitHub API, curator's token)
```

No server, no database, nothing to pause. The repo is already public, so Pages is free.

---

## Design decisions

### 1. The repo is the database

| File | Written by | Contents |
|------|-----------|----------|
| `data/weeks/<week>.json` | aggregator workflow only | articles for that ISO week: `guid, title, url, feed_name, category, published_at, summary` |
| `data/triage/<week>.json` | triage page only | `{ guid: { status, note } }` |
| `data/seen.json` | aggregator workflow only | GUIDs already ingested (replaces the throwaway SQLite file) |
| `data/refresh-log.json` | aggregator workflow only | last ~50 runs: time, week, added, skipped, trigger |
| `feeds.yaml` | humans (edit in GitHub) | feed list, becomes the only source (Supabase `feed_sources` retired for the newsletter) |

Articles and triage are separate files on purpose. The workflow and the page never
write the same file, so a refresh can't collide with a curator's in-progress edits.

### 2. Triage writes go through the GitHub API with a personal token

Each curator creates a fine-grained personal access token (repo: `energy-security-aggregator`;
permissions: Contents read/write, Actions read/write), pastes it into the page once, and
it's kept in `localStorage`. The same token powers:

- **Save:** `PUT /repos/.../contents/data/triage/<week>.json` (batched, one commit per save, not per click)
- **Refresh:** `POST /repos/.../actions/workflows/curator-refresh.yml/dispatches`

This removes `REFRESH_PASSWORD`, `GITHUB_PAT`, `INGEST_API_KEY` and `CURATOR_URL` entirely.

### 3. Everything else runs in the browser

Filter, sort, search, stats, and the CSV/text export are all computed client-side from the
week's JSON (~150 articles/week). The export becomes a `Blob` download built from the
same fields `/api/export` uses today.

### 4. Drop on-demand "Summarize"

The button calls Groq from the server. Pages can't hold the Groq key. The RSS summary
already fills `ai_summary` for most articles. If summaries are still wanted, generate
them in the workflow at ingest time (the Groq key is already a GitHub secret).

---

## Trade-offs to accept (or veto) before starting

- **Everything is public:** article lists, statuses, and curator notes are readable by anyone
  who finds the repo or site. Fine for public news links; not fine if notes are sensitive.
- **Every curator needs a GitHub account and a token.** Fine for 1–3 technical curators.
  If curators are non-technical, use the fallback below instead.
- **Saves are commits:** history of every triage decision shows up in `git log` (a plus for
  audit, mild noise). Two curators editing the same week at once: last save wins, unless
  the page re-fetches and merges on a `409`, which is planned in Phase 2.

**Fallback if any of those is a dealbreaker:** keep Supabase as the data store, have the
Pages site talk to it directly with `supabase-js` + Supabase Auth (magic-link email login)
and row-level security. That still removes Render, but keeps the Supabase pausing problem
(needs a keep-alive job).

---

## Phases

### Phase 0 — Decide (no code)
- Confirm the trade-offs above, and who triages.
- Confirm Pages lives in `klemens-cc1/energy-security-aggregator` (it already has the workflows).

### Phase 1 — Aggregator writes JSON to the repo · ~half day
- `main.py --mode curate`: after dedup + categorize, merge new articles into
  `data/weeks/<week>.json`, append GUIDs to `data/seen.json`, append a row to
  `data/refresh-log.json`; workflow commits and pushes `data/` (`permissions: contents: write`,
  `concurrency: data-write` so two runs never push at once).
- `aggregator.is_seen()` reads `data/seen.json` instead of SQLite, which fixes dedup on Actions
  (today `articles.db` is discarded after every run, so dedup only works because of the
  lookback window and the curator's GUID check).
- Feeds: export the current Supabase `feed_sources` (newsletter, active) into `feeds.yaml`
  once, then drop `feeds_db.py` from the newsletter path.
- Fix the week key: use `isocalendar().year`, not `now.year` (Dec 29–31 currently gets
  labelled week 01 of the *old* year).
- Keep the existing `push_to_curator()` call running in parallel until cutover, so the Render
  site keeps working during migration. Make a failed push exit non-zero so it can't fail
  silently again.

### Phase 2 — Static triage page · ~1–2 days
- New `site/index.html`, ported from `cits-newsletter-curator/templates/index.html`
  (same look; Jinja bits removed).
- Swap each API call:

  | Today | On Pages |
  |-------|----------|
  | `GET /api/articles`, `/api/stats`, `/api/filters` | fetch `data/weeks/<w>.json` + `data/triage/<w>.json`, compute in JS |
  | `PATCH /api/articles/<id>` | update local state, mark dirty; **Save** commits `data/triage/<w>.json` |
  | `GET /api/export` | build CSV / text in the browser |
  | `GET /api/refresh-log` | fetch `data/refresh-log.json` |
  | `POST /api/trigger-refresh` | `workflow_dispatch` with the curator's token |
  | `POST .../summarize` | removed (see decision 4) |
  | `GET /api/weeks` (history page) | list `data/weeks/` via the contents API, or a `data/weeks/index.json` the workflow maintains |

- Read data through `raw.githubusercontent.com` or the contents API, not the Pages copy:
  Pages redeploys lag a minute or two behind commits, which would make a just-saved
  status look lost.
- Save handles `409 Conflict`: re-fetch, re-apply local changes, retry once.
- Deploy with a `pages.yml` workflow (or Pages "deploy from branch", `/site` folder).

### Phase 3 — Backfill history · ~1 hour
- One-off script: read all `articles` rows from Supabase and write `data/weeks/*.json` +
  `data/triage/*.json` (status/note), and seed `data/seen.json` with every GUID.
- Run once while Supabase is awake. After this, Supabase holds nothing the newsletter needs.

### Phase 4 — Cutover · ~1 hour
- Share the Pages URL; run one real Friday cycle on it.
- Remove `push_to_curator()` and the `CURATOR_URL` / `CURATOR_API_KEY` secrets.
- On Render: replace `/newsletter` with a link to the Pages site (or leave it read-only).
- Retire `/api/ingest`, `/api/trigger-refresh`, `REFRESH_PASSWORD`, `GITHUB_PAT` on Render.

---

## Out of scope (stays on Render + Supabase)

- Research page (`/research`, `ResearchSession`/`ResearchJob`: long-running server-side
  searches + Groq clustering, which can't be static).
- History search across research sessions.
- The Friday email digest (`daily-digest.yml`) keeps working as-is; it only gains the
  `seen.json` dedup fix.

If Research later moves too, Render and Supabase can be shut down entirely. That's a separate plan.

---

## Open questions

1. Who triages, and are they comfortable with a GitHub token? (Decides main plan vs. fallback.)
2. Are curator notes OK to be public?
3. Keep AI summaries? If yes: generate in the workflow for every article, or only for top-scored ones?
4. Should the Friday email use the curator's **selected** articles instead of the AI filter?
   It doesn't today. Once triage lives in the repo it's an easy switch, but it changes what the
   digest is.
