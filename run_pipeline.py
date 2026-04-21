"""
End-to-end pipeline runner — equivalent to running all steps sequentially.

Usage:
    python run_pipeline.py [--dry-run]

    --dry-run  : skips email delivery; writes HTML to data/digest_preview.html instead
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("runner")


async def main(dry_run: bool) -> None:
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup
    from pipeline.filter import score_articles
    from pipeline.summarise import summarise_articles
    from pipeline.cluster import cluster_stories
    from pipeline.compose import compose
    from pipeline.deliver import send
    from feedback.aggregate import aggregate

    log.info("=== Step 1: Ingest ===")
    articles = await fetch_all()

    log.info("=== Step 2: Dedup ===")
    articles = dedup(articles)

    log.info("=== Step 3: Filter ===")
    articles = score_articles(articles)
    if not articles:
        log.error("No articles passed the relevance filter. Aborting.")
        sys.exit(1)

    log.info("=== Step 4: Summarise ===")
    articles = await summarise_articles(articles)

    log.info("=== Step 5: Cluster ===")
    stories = cluster_stories(articles)

    log.info("=== Step 6: Compose ===")
    html, amp_html, manifest = compose(stories)

    if dry_run:
        out = Path("data/digest_preview.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        log.info("Dry run: HTML written to %s  (%d chars)", out, len(html))
        out_amp = Path("data/digest_preview.amp.html")
        out_amp.write_text(amp_html)
        log.info("Dry run: AMP HTML written to %s  (%d chars)", out_amp, len(amp_html))
    else:
        log.info("=== Step 7: Deliver ===")
        email_id = send(html, amp_html=amp_html)
        log.info("Delivered! email_id=%s", email_id)

    log.info("=== Step 8: Aggregate feedback ===")
    aggregate()

    log.info("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip email delivery")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
