#!/usr/bin/env python3
"""
Energy Security Aggregator — main entry point.
Run manually or via GitHub Actions cron.
"""
import logging
from collections import Counter
from aggregator import aggregate
from emailer import send_email
from filter import filter_and_categorize
from db import get_unsent_articles, mark_sent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def print_weekly_stats(
    raw_count: int,
    dedup_count: int,
    categorized: dict,
    all_articles: list,
) -> None:
    total_passed = sum(len(v) for v in categorized.values())
    total_keyword = sum(1 for a in all_articles if a.get("_keyword_matched"))
    dropped = dedup_count - total_passed
    drop_rate = (dropped / dedup_count * 100) if dedup_count else 0

    # Source counts across all categorized articles
    source_counter: Counter = Counter()
    for items in categorized.values():
        for a in items:
            source_counter[a["feed_name"]] += 1

    log.info("")
    log.info("=" * 55)
    log.info("WEEKLY DIGEST STATS")
    log.info("=" * 55)

    # Article pipeline
    log.info("  PIPELINE")
    log.info(f"    Raw articles fetched:      {raw_count}")
    log.info(f"    After deduplication:       {dedup_count}")
    log.info(f"    After AI filter:           {total_passed}")
    log.info(f"    Dropped by AI filter:      {dropped}  ({drop_rate:.0f}%)")

    # Category breakdown
    log.info("")
    log.info("  CATEGORIES")
    for cat, items in categorized.items():
        bar = "█" * len(items)
        log.info(f"    {cat:<28} {len(items):>2}  {bar}")

    # Top sources
    log.info("")
    log.info("  TOP SOURCES  (articles in digest)")
    for source, count in source_counter.most_common(10):
        bar = "█" * count
        log.info(f"    {source:<35} {count:>2}  {bar}")

    # Source diversity warning
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
    from filter import deduplicate
    articles = deduplicate(articles)
    dedup_count = len(articles)
    log.info(f"{dedup_count} articles after deduplication.")

    # 4. Run keyword filter and categorize (includes AI scoring)
    categorized = filter_and_categorize(articles)
    for cat, items in categorized.items():
        log.info(f"  {cat}: {len(items)} articles")

    # 5. Send the email digest
    success = send_email(categorized)

    # 6. Mark articles as sent so they're never re-sent
    if success:
        ids = [a["id"] for a in articles]
        mark_sent(ids)
        log.info("Marked all articles as sent.")

    # 7. Print weekly stats summary
    print_weekly_stats(raw_count, dedup_count, categorized, articles)


if __name__ == "__main__":
    main()
