"""
feeds_db.py — Load feed list from Supabase feed_sources table.
Used by aggregator.py as the primary feed source; falls back to feeds.yaml if unavailable.
"""
import logging
import os

log = logging.getLogger(__name__)


def load_feeds_from_supabase() -> list[dict]:
    """
    Query Supabase for active newsletter feeds.
    Returns list of {name, url} dicts — same shape as feeds.yaml entries.
    Raises on any failure so caller can fall back to YAML.
    """
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    if db_url.startswith("sqlite"):
        raise ValueError("DATABASE_URL is SQLite — not a valid Supabase connection")

    # SQLAlchemy uses postgresql://, psycopg2 accepts both
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(db_url, connect_timeout=10)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT name, url
                FROM feed_sources
                WHERE use_newsletter = true AND active = true
                ORDER BY name
                """
            )
            rows = cur.fetchall()
            if not rows:
                raise ValueError("feed_sources table returned 0 newsletter feeds — is it seeded?")
            return [{"name": row["name"], "url": row["url"]} for row in rows]
    finally:
        conn.close()
