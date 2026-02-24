import feedparser
import yaml
import logging
from datetime import datetime, timezone, timedelta
from db import init_db, is_seen, save_article

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LOOKBACK_HOURS = 169  # slightly over 7 days to avoid missing weekly boundary articles


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


def fetch_feed(feed_config: dict) -> tuple[list[dict], bool]:
    """Returns (articles, success) where success=False means the feed failed."""
    name = feed_config["name"]
    url = feed_config["url"]
    category = ""
    articles = []

    log.info(f"Fetching: {name}")
    try:
        parsed = feedparser.parse(url, agent="energy-security-aggregator/1.0")
        if parsed.bozo and not parsed.entries:
            log.warning(f"  Feed error for {name}: {parsed.bozo_exception}")
            return [], False

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
            articles.append({
                "guid": guid,
                "title": title,
                "url": url_,
                "feed_name": name,
                "category": category,
                "published_at": pub_str,
            })

        log.info(f"  {len(articles)} new articles from {name}")
        return articles, True

    except Exception as e:
        log.error(f"  Failed to fetch {name}: {e}")
        return [], False


def print_feed_health(results: dict[str, bool]) -> None:
    """Log a clean feed health summary table."""
    log.info("=" * 55)
    log.info("FEED HEALTH REPORT")
    log.info("=" * 55)

    passed = {name for name, ok in results.items() if ok}
    failed = {name for name, ok in results.items() if not ok}

    for name in sorted(passed):
        log.info(f"  ✓  {name}")
    for name in sorted(failed):
        log.warning(f"  ✗  {name}  <- REPLACE THIS FEED")

    log.info("-" * 55)
    log.info(f"  {len(passed)} healthy / {len(failed)} failed / {len(results)} total")
    if failed:
        log.warning(f"  Action needed: replace {len(failed)} failing feed(s)")
    log.info("=" * 55)


def aggregate(feeds_path="feeds.yaml") -> list[dict]:
    init_db()
    feeds = load_feeds(feeds_path)
    all_articles = []
    health: dict[str, bool] = {}

    for feed in feeds:
        articles, success = fetch_feed(feed)
        all_articles.extend(articles)
        health[feed["name"]] = success

    log.info(f"Total new articles: {len(all_articles)}")
    print_feed_health(health)
    return all_articles
