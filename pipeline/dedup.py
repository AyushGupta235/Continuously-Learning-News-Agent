"""
Two-pass deduplication of ingested articles.

Pass 1 — Exact URL match (sha256 of normalised URL)
Pass 2 — Title similarity (difflib.SequenceMatcher ratio > 0.75)

Keeps the article with the longer full_text when merging duplicates.
Typically reduces article count by ~40%.
"""

import hashlib
import logging
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

log = logging.getLogger(__name__)

_TITLE_SIMILARITY_THRESHOLD = 0.75


# ── Article ID ────────────────────────────────────────────────────────────────

def _article_id(url: str) -> str:
    """Stable 16-char ID from the raw URL (before normalisation)."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ── URL normalisation ─────────────────────────────────────────────────────────

_UTM_PARAMS = re.compile(r"^utm_")


def _normalise_url(url: str) -> str:
    """Strip tracking params, trailing slash, and www prefix."""
    try:
        p = urlparse(url.strip())
        # remove www.
        netloc = re.sub(r"^www\.", "", p.netloc)
        # strip utm_* query params
        qs = parse_qs(p.query, keep_blank_values=False)
        qs = {k: v for k, v in qs.items() if not _UTM_PARAMS.match(k)}
        clean_query = urlencode(qs, doseq=True)
        # rebuild, strip trailing slash from path
        path = p.path.rstrip("/") or "/"
        normalised = urlunparse((p.scheme, netloc, path, p.params, clean_query, ""))
        return normalised.lower()
    except Exception:
        return url.lower()


def _url_id(url: str) -> str:
    return hashlib.sha256(_normalise_url(url).encode()).hexdigest()[:16]


# ── Title similarity ──────────────────────────────────────────────────────────

def _title_key(title: str) -> str:
    """Lowercase, strip punctuation for comparison."""
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, _title_key(a), _title_key(b)).ratio() > _TITLE_SIMILARITY_THRESHOLD


def _merge(a: dict, b: dict) -> dict:
    """Keep the article with longer full_text; inherit higher source_weight."""
    primary = a if len(a.get("full_text", "")) >= len(b.get("full_text", "")) else b
    primary["source_weight"] = max(
        a.get("source_weight", 1.0), b.get("source_weight", 1.0)
    )
    return primary


# ── Main dedup logic ──────────────────────────────────────────────────────────

def dedup(articles: list[dict]) -> list[dict]:
    # Pass 1: exact URL dedup
    seen_url_ids: dict[str, int] = {}  # url_id -> index in result
    pass1: list[dict] = []

    for article in articles:
        uid = _url_id(article["url"])
        if uid in seen_url_ids:
            idx = seen_url_ids[uid]
            pass1[idx] = _merge(pass1[idx], article)
        else:
            seen_url_ids[uid] = len(pass1)
            article = dict(article)  # don't mutate original
            article["id"] = uid      # re-stamp with normalised id
            pass1.append(article)

    log.info("After URL dedup: %d → %d articles", len(articles), len(pass1))

    # Pass 2: title similarity dedup
    pass2: list[dict] = []
    for article in pass1:
        merged = False
        for i, existing in enumerate(pass2):
            if _similar(article["title"], existing["title"]):
                pass2[i] = _merge(existing, article)
                merged = True
                break
        if not merged:
            pass2.append(article)

    log.info("After title dedup: %d → %d articles", len(pass1), len(pass2))
    return pass2


if __name__ == "__main__":
    import asyncio
    import json
    from pipeline.ingest import fetch_all

    articles = asyncio.run(fetch_all())
    deduped = dedup(articles)
    print(f"Raw: {len(articles)}  After dedup: {len(deduped)}")
    print(json.dumps(deduped[:2], indent=2))
