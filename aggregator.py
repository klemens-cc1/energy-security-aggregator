import feedparser
import yaml
import logging
from datetime import datetime, timezone, timedelta
from db import init_db, is_seen, save_article

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LOOKBACK_HOURS = 25  # slightly over 24h to avoid missing articles at boundaries


def load_feeds(path="feeds.yaml") -> list:
    with open(path) as f:
        config = yaml.safe_load(f)
    return config.get("feeds", [])


def parse_published(entry) -> datetime | None:
    """Try to extract a timezone-aware published datetime from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def is_recent(published: datetime | None) -> bool:
    if published is None:
        return True  # include if we can't determine age
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    return published >= cutoff


def fetch_feed(feed_config: dict) -> list[dict]:
    name = feed_config["name"]
    url = feed_config["url"]
    category = feed_config.get("category", "General")
    articles = []

    log.info(f"Fetching: {name}")
    try:
        parsed = feedparser.parse(url, agent="energy-security-aggregator/1.0")
        if parsed.bozo and not parsed.entries:
            log.warning(f"  Feed error for {name}: {parsed.bozo_exception}")
            return []

        for entry in parsed.entries:
            guid = getattr(entry, "id", None) or getattr(entry, "link", None)
            if not guid:
                continue

            if is_seen(guid):
                continue

            published = parse_published(entry)
            if not is_recent(published):
                continue

            title = getattr(entry, "title", "(No title)").strip()
            url_ = getattr(entry, "link", "")
            pub_str = published.isoformat() if published else ""

            save_article(guid, title, url_, name, category, pub_str)
            articles.append(
                {
                    "guid": guid,
                    "title": title,
                    "url": url_,
                    "feed_name": name,
                    "category": category,
                    "published_at": pub_str,
                }
            )

        log.info(f"  {len(articles)} new articles from {name}")
    except Exception as e:
        log.error(f"  Failed to fetch {name}: {e}")

    return articles


def aggregate(feeds_path="feeds.yaml") -> list[dict]:
    init_db()
    feeds = load_feeds(feeds_path)
    all_articles = []
    for feed in feeds:
        all_articles.extend(fetch_feed(feed))
    log.info(f"Total new articles: {len(all_articles)}")
    return all_articles
