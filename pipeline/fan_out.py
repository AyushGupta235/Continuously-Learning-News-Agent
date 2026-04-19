"""
Multi-user pipeline orchestrator.

Runs a single shared ingest/dedup/summarise pass, then delivers a personalised
digest to each active user defined in users/registry.yaml.

Usage:
    python -m pipeline.fan_out [--dry-run] [--users ayush,priya]

    --dry-run        skip email delivery; write HTML to data/digest_preview_{id}.html
    --users id1,id2  run only these user IDs (comma-separated); default: all active

Profile files live in users/profiles/ with UUID-based filenames for obfuscation.
The id → file mapping is in users/registry.yaml, which also holds email addresses.

Pipeline flow:
    SHARED (once):
      ingest → dedup → [per-user filter] → union of passing articles
                     → summarise(union)  → summarised_map

    PER-USER (loop):
      filter(user.profile) → cluster → compose → deliver → aggregate feedback
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_LEGACY_PROFILE = Path("data/interest-profile.md")


# ── Registry loader ───────────────────────────────────────────────────────────

def load_users(registry_path: str = "users/registry.yaml", filter_ids: set | None = None) -> list[dict]:
    """
    Load active users from registry.yaml.

    Each user dict is the registry entry plus '_resolved_profile': the path to
    the profile .md file that will be used for filtering, after fallback logic.
    """
    path = Path(registry_path)
    if not path.exists():
        raise FileNotFoundError(f"Registry not found: {path}")

    data = yaml.safe_load(path.read_text())
    users = [u for u in data.get("users", []) if u.get("active", True)]

    if filter_ids:
        users = [u for u in users if u["id"] in filter_ids]

    for user in users:
        profile_path = Path(user.get("profile", f"users/profiles/{user['id']}.md"))
        if profile_path.exists():
            user["_resolved_profile"] = str(profile_path)
        elif _LEGACY_PROFILE.exists():
            log.warning(
                "Profile not found at %s — falling back to %s",
                profile_path,
                _LEGACY_PROFILE,
            )
            user["_resolved_profile"] = str(_LEGACY_PROFILE)
        else:
            log.warning("No profile found for user %s — will be skipped", user["id"])
            user["_resolved_profile"] = None

    return users


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run(dry_run: bool = False, user_ids: list[str] | None = None) -> None:
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup
    from pipeline.filter import score_articles
    from pipeline.summarise import summarise_articles
    from pipeline.cluster import cluster_stories
    from pipeline.compose import compose
    from pipeline.deliver import send
    from feedback.aggregate import aggregate

    users = load_users(filter_ids=set(user_ids) if user_ids else None)
    if not users:
        log.error("No active users found in registry.")
        sys.exit(1)
    log.info("Running digest for %d user(s): %s", len(users), [u["id"] for u in users])

    # ── Shared: ingest + dedup ────────────────────────────────────────────────
    log.info("=== Shared Step 1: Ingest ===")
    articles = await fetch_all()

    log.info("=== Shared Step 2: Dedup ===")
    articles = dedup(articles)

    # ── Per-user filter → build union of passing articles ─────────────────────
    log.info("=== Step 3: Filter (per-user, building union for summarisation) ===")
    user_passing_ids: dict[str, list[str]] = {}
    union_articles: dict[str, dict] = {}

    for user in users:
        uid = user["id"]
        resolved = user["_resolved_profile"]
        if not resolved:
            log.warning("User %s has no profile — skipping", uid)
            user_passing_ids[uid] = []
            continue
        scored = score_articles(articles, profile_path=resolved)
        user_passing_ids[uid] = [a["id"] for a in scored]
        for a in scored:
            union_articles[a["id"]] = a
        log.info("User %s: %d articles passed filter", uid, len(scored))

    if not union_articles:
        log.error("No articles passed the relevance filter for any user. Aborting.")
        sys.exit(1)

    # ── Shared: summarise union once (avoids duplicate xAI calls) ────────────
    log.info(
        "=== Shared Step 4: Summarise (%d unique articles across all users) ===",
        len(union_articles),
    )
    summarised = await summarise_articles(list(union_articles.values()))
    summarised_map = {a["id"]: a for a in summarised}

    # ── Per-user: cluster → compose → deliver → aggregate ────────────────────
    for user in users:
        uid = user["id"]
        display_name = user.get("name", uid)
        # Email from registry; fall back to DIGEST_EMAIL for single-user / legacy mode
        email = user.get("email", "") or os.environ.get("DIGEST_EMAIL", "")

        log.info("=== Per-user Steps 5-8: %s ===", uid)

        user_articles = [
            summarised_map[aid]
            for aid in user_passing_ids[uid]
            if aid in summarised_map
        ]
        if not user_articles:
            log.warning("User %s: no summarised articles — skipping", uid)
            continue

        stories = cluster_stories(user_articles)
        html, _ = compose(stories, user_id=uid, manifest_dir="data/manifests")

        if dry_run:
            out = Path(f"data/digest_preview_{uid}.html")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html)
            log.info("Dry run: HTML for %s written to %s  (%d chars)", uid, out, len(html))
        else:
            if not email:
                log.warning("User %s: no email configured — skipping delivery", uid)
            else:
                send(html, recipient_email=email, sender_name=f"{display_name}'s Digest")
                log.info("Delivered digest to %s", uid)

        aggregate(user_id=uid)

    log.info("Multi-user pipeline complete.")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Multi-user news digest pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip email delivery")
    parser.add_argument(
        "--users",
        help="Comma-separated user IDs to run (default: all active in registry)",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, user_ids=args.users.split(",") if args.users else None))
