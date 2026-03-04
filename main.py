#!/usr/bin/env python3
"""
Energy Security Aggregator — main entry point.
Run manually or via GitHub Actions cron.
"""
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from aggregator import aggregate
from db import get_unsent_articles, mark_sent
from emailer import send_email
from filter import deduplicate, filter_and_categorize, categorize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def push_to_curator(articles: list[dict]) -> None:
    """Push keyword-matched articles to the curator web app (pre-AI-filter)."""
    curator_url = os.environ.get("CURATOR_URL", "").rstrip("/")
    api_key = os.environ.get("CURATOR_API_KEY", "")

    if not curator_url or not api_key:
        log.info("CURATOR_URL or CURATOR_API_KEY not set — skipping curator push.")
        return

    try:
        import urllib.request

        now = datetime.now(timezone.utc)
        week_key = f"{now.year}-W{now.isocalendar()[1]:02d}"

        # Only push articles that match at least one keyword category
        to_push = []
        for article in articles:
            matched_cats = categorize(article)
            if matched_cats:
                a = dict(article)
                a["category"] = matched_cats[0]  # primary category
                to_push.append(a)

        if not to_push:
            log.info("No keyword-matched articles to push to curator.")
            return

        payload = json.dumps({
            "week_key": week_key,
            "articles": to_push,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{curator_url}/api/ingest",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            log.info(
                f"Curator push: {result.get('added', 0)} added, "
                f"{result.get('skipped', 0)} skipped "
                f"(week {result.get('week_key', week_key)})"
            )

    except Exception as e:
        log.warning(f"Curator push failed (non-fatal): {e}")


def print_weekly_stats(
    raw_count: int,
    dedup_count: int,
    categorized: dict,
    all_articles: list,
) -> None:
    total_passed = sum(len(v) for v in categorized.values())
    dropped = dedup_count - total_passed
    drop_rate = (dropped / dedup_count * 100) if dedup_count else 0

    source_counter: Counter = Counter()
    for items in categorized.values():
        for a in items:
            source_counter[a["feed_name"]] += 1

    log.info("")
    log.info("=" * 55)
    log.info("WEEKLY DIGEST STATS")
    log.info("=" * 55)

    log.info("  PIPELINE")
    log.info(f"    Raw articles fetched:      {raw_count}")
    log.info(f"    After deduplication:       {dedup_count}")
    log.info(f"    After AI filter:           {total_passed}")
    log.info(f"    Dropped by AI filter:      {dropped}  ({drop_rate:.0f}%)")

    log.info("")
    log.info("  CATEGORIES")
    for cat, items in categorized.items():
        bar = "█" * len(items)
        log.info(f"    {cat:<28} {len(items):>2}  {bar}")

    log.info("")
    log.info("  TOP SOURCES  (articles in digest)")
    for source, count in source_counter.most_common(10):
        bar = "█" * count
        log.info(f"    {source:<35} {count:>2}  {bar}")

    for cat, items in categorized.items():
        if not items:
            continue
        cat_sources = Counter(a["feed_name"] for a in items)
        top_source, top_count = cat_sources.most_common(1)[0]
        if top_count >= 7:
            log.warning(
                f"  ⚠  Source concentration: {top_source} dominates "
                f"{cat} ({top_count}/{len(items)} articles) — consider adding more feeds"
            )

    log.info("")
    log.info("=" * 55)


def get_emailed_article_ids(categorized: dict, deduplicated_articles: list[dict]) -> list[int]:
    """Return unique DB IDs for articles that were actually included in the digest."""
    url_to_id = {
        article.get("url"): article.get("id")
        for article in deduplicated_articles
        if article.get("url") and article.get("id") is not None
    }

    sent_ids: set[int] = set()
    for items in categorized.values():
        for article in items:
            article_id = article.get("id")
            if article_id is None:
                article_id = url_to_id.get(article.get("url"))
            if article_id is not None:
                sent_ids.add(article_id)

    return sorted(sent_ids)


def main():
    # 1. Fetch new articles from all feeds and store in DB
    aggregate()

    # 2. Get all articles not yet sent
    articles = get_unsent_articles()
    raw_count = len(articles)
    log.info(f"{raw_count} unsent articles ready for digest.")

    if not articles:
        log.info("Nothing to send this week.")
        return

    # 3. Deduplicate articles by title similarity
    articles = deduplicate(articles)
    dedup_count = len(articles)
    log.info(f"{dedup_count} articles after deduplication.")

    # 4. Push keyword-matched articles to curator (pre-AI-filter)
    push_to_curator(articles)

    # 5. Run keyword filter and categorize (includes AI scoring)
    categorized = filter_and_categorize(articles)
    for cat, items in categorized.items():
        log.info(f"  {cat}: {len(items)} articles")

    # 6. Send the email digest
    success = send_email(categorized)

    # 7. Mark only emailed articles as sent so dropped items can be reconsidered
    if success:
        sent_ids = get_emailed_article_ids(categorized, articles)
        mark_sent(sent_ids)
        log.info(f"Marked {len(sent_ids)} emailed articles as sent.")

    # 8. Print weekly stats summary
    print_weekly_stats(raw_count, dedup_count, categorized, articles)


if __name__ == "__main__":
    main()
