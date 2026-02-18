#!/usr/bin/env python3
"""
Energy Security Aggregator — main entry point.
Run manually or via GitHub Actions cron.
"""

import logging
from aggregator import aggregate
from emailer import send_email
from filter import filter_and_categorize
from db import get_unsent_articles, mark_sent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    # 1. Fetch new articles from all feeds and store in DB
    aggregate()

    # 2. Get all articles not yet sent
    articles = get_unsent_articles()
    log.info(f"{len(articles)} unsent articles ready for digest.")

    if not articles:
        log.info("Nothing to send this week.")
        return

    # 3. Run keyword filter and categorize
    categorized = filter_and_categorize(articles)
    for cat, items in categorized.items():
        log.info(f"  {cat}: {len(items)} articles")

    # 4. Send the email digest
    success = send_email(categorized)

    # 5. Mark articles as sent so they're never re-sent
    if success:
        ids = [a["id"] for a in articles]
        mark_sent(ids)
        log.info("Marked all articles as sent.")


if __name__ == "__main__":
    main()
