import sqlite3
import os

DB_PATH = os.environ.get("LEGISCAN_DB_PATH", "legiscan.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_bills_state ON bills(state);
            CREATE INDEX IF NOT EXISTS idx_bills_state_hash ON bills(state, change_hash);

            CREATE TABLE IF NOT EXISTS datasets (
                session_id   INTEGER PRIMARY KEY,
                state        TEXT NOT NULL,
                session_name TEXT,
                dataset_hash TEXT,
                access_key   TEXT,
                downloaded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bills (
                bill_id     INTEGER PRIMARY KEY,
                state       TEXT NOT NULL,
                session_id  INTEGER,
                bill_number TEXT,
                title       TEXT,
                description TEXT,
                change_hash TEXT,
                status_id   INTEGER,
                last_action TEXT,
                url         TEXT,
                fetched_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS docs (
                doc_id      INTEGER PRIMARY KEY,
                bill_id     INTEGER NOT NULL,
                doc_hash    TEXT,
                cached_path TEXT,
                cached_at   TEXT DEFAULT (datetime('now'))
            );

            -- Search hits for dedup and fusion scoring
            CREATE TABLE IF NOT EXISTS search_hits (
                bill_id       INTEGER NOT NULL,
                query         TEXT NOT NULL,
                tier          INTEGER NOT NULL,
                relevance     REAL,
                state         TEXT,
                change_hash   TEXT,
                seen_at       TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (bill_id, query)
            );

            -- Bills that passed fusion threshold — watched for future changes
            CREATE TABLE IF NOT EXISTS watched_bills (
                bill_id       INTEGER PRIMARY KEY,
                state         TEXT NOT NULL,
                bill_number   TEXT,
                fusion_score  REAL,
                change_hash   TEXT,
                first_seen    TEXT DEFAULT (datetime('now')),
                last_checked  TEXT DEFAULT (datetime('now'))
            );

            -- Staged bills awaiting human review before entering states.js
            CREATE TABLE IF NOT EXISTS queue (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id       INTEGER UNIQUE NOT NULL,
                state         TEXT NOT NULL,
                bill_number   TEXT,
                title         TEXT,
                summary       TEXT,
                tags          TEXT,
                confidence    REAL,
                url           TEXT,
                review_status TEXT DEFAULT 'pending',
                reject_reason TEXT,
                reviewed_at   TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()


# ── Bills ──────────────────────────────────────────────────────────────────────

def get_bill_hash(bill_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT change_hash FROM bills WHERE bill_id = ?", (bill_id,)
        ).fetchone()
        return row["change_hash"] if row else None


def upsert_bill(bill_id, state, session_id, bill_number, title,
                change_hash, status_id, last_action, url, description=""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO bills (bill_id, state, session_id, bill_number, title,
                               description, change_hash, status_id, last_action,
                               url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(bill_id) DO UPDATE SET
                description = COALESCE(excluded.description, bills.description),
                change_hash = excluded.change_hash,
                status_id   = excluded.status_id,
                last_action = excluded.last_action,
                url         = excluded.url,
                fetched_at  = datetime('now')
        """, (bill_id, state, session_id, bill_number, title,
              description, change_hash, status_id, last_action, url))
        conn.commit()


# ── Datasets ───────────────────────────────────────────────────────────────────

def get_dataset_hash(session_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT dataset_hash FROM datasets WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["dataset_hash"] if row else None


def upsert_dataset(session_id, state, session_name, dataset_hash, access_key):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO datasets (session_id, state, session_name, dataset_hash,
                                  access_key, downloaded_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(session_id) DO UPDATE SET
                dataset_hash  = excluded.dataset_hash,
                access_key    = excluded.access_key,
                downloaded_at = datetime('now')
        """, (session_id, state, session_name, dataset_hash, access_key))
        conn.commit()


# ── Docs ───────────────────────────────────────────────────────────────────────

def get_doc_hash(doc_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT doc_hash FROM docs WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return row["doc_hash"] if row else None


def upsert_doc(doc_id, bill_id, doc_hash, cached_path):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO docs (doc_id, bill_id, doc_hash, cached_path, cached_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(doc_id) DO UPDATE SET
                doc_hash    = excluded.doc_hash,
                cached_path = excluded.cached_path,
                cached_at   = datetime('now')
        """, (doc_id, bill_id, doc_hash, cached_path))
        conn.commit()


# ── Local keyword search ───────────────────────────────────────────────────────

def find_changed_energy_bills(states: list[str], keywords: list[str]) -> list[dict]:
    """
    Single-query scan across all states for bills matching any keyword in title/description.
    Returns rows sorted by state. Zero API calls.
    """
    if not keywords or not states:
        return []
    kw_conditions = " OR ".join(
        ["(LOWER(title) LIKE ? OR LOWER(COALESCE(description,'')) LIKE ?)"] * len(keywords)
    )
    state_placeholders = ",".join("?" * len(states))
    params = [p for kw in keywords for p in (f"%{kw.lower()}%", f"%{kw.lower()}%")]
    params.extend(states)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT b.bill_id, b.state, b.bill_number, b.title, b.description,
                   b.change_hash, b.url
            FROM bills b
            WHERE ({kw_conditions})
              AND b.state IN ({state_placeholders})
        """, params).fetchall()
        return [dict(r) for r in rows]


# ── Search hits ───────────────────────────────────────────────────────────────

def upsert_search_hit(bill_id, query, tier, relevance, state, change_hash):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO search_hits (bill_id, query, tier, relevance, state, change_hash, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(bill_id, query) DO UPDATE SET
                relevance   = excluded.relevance,
                change_hash = excluded.change_hash,
                seen_at     = datetime('now')
        """, (bill_id, query, tier, relevance, state, change_hash))
        conn.commit()


def get_hits_for_bill(bill_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT query, tier, relevance FROM search_hits WHERE bill_id = ?",
            (bill_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Watched bills ──────────────────────────────────────────────────────────────

def upsert_watched_bill(bill_id, state, bill_number, fusion_score, change_hash):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO watched_bills (bill_id, state, bill_number, fusion_score,
                                       change_hash, first_seen, last_checked)
            VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(bill_id) DO UPDATE SET
                fusion_score = excluded.fusion_score,
                change_hash  = excluded.change_hash,
                last_checked = datetime('now')
        """, (bill_id, state, bill_number, fusion_score, change_hash))
        conn.commit()


def get_watched_bill_hash(bill_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT change_hash FROM watched_bills WHERE bill_id = ?", (bill_id,)
        ).fetchone()
        return row["change_hash"] if row else None


def get_all_watched_bills() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT bill_id, state, change_hash FROM watched_bills"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Queue ──────────────────────────────────────────────────────────────────────

def queue_bill(bill_id, state, bill_number, title, summary, tags, confidence, url):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO queue (bill_id, state, bill_number, title, summary,
                               tags, confidence, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bill_id) DO UPDATE SET
                summary    = excluded.summary,
                tags       = excluded.tags,
                confidence = excluded.confidence,
                url        = excluded.url
        """, (bill_id, state, bill_number, title, summary,
              ",".join(tags), confidence, url))
        conn.commit()


def get_pending_queue() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM queue WHERE review_status = 'pending'
            ORDER BY state, created_at
        """).fetchall()
        return [dict(r) for r in rows]


def set_review_status(queue_id: int, status: str, reason: str = ""):
    with get_conn() as conn:
        conn.execute("""
            UPDATE queue
            SET review_status = ?,
                reject_reason = ?,
                reviewed_at   = datetime('now')
            WHERE id = ?
        """, (status, reason, queue_id))
        conn.commit()


def update_summary(queue_id: int, summary: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE queue SET summary = ? WHERE id = ?", (summary, queue_id)
        )
        conn.commit()
