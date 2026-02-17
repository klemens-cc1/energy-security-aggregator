import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "articles.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT UNIQUE NOT NULL,
                title TEXT,
                url TEXT,
                feed_name TEXT,
                category TEXT,
                published_at TEXT,
                sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def is_seen(guid: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM articles WHERE guid = ?", (guid,)).fetchone()
        return row is not None


def save_article(guid, title, url, feed_name, category, published_at):
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO articles (guid, title, url, feed_name, category, published_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (guid, title, url, feed_name, category, published_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # already exists


def get_unsent_articles():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE sent = 0 ORDER BY category, feed_name"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_sent(article_ids: list):
    if not article_ids:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE articles SET sent = 1 WHERE id IN ({','.join('?' * len(article_ids))})",
            article_ids,
        )
        conn.commit()
