"""
Fetch articles from all configured sources in parallel.

Returns List[dict] with keys:
  id          : str  — sha256 of normalised URL
  title       : str
  url         : str
  description : str  — from feed, may be truncated
  full_text   : str  — extracted via trafilatura (empty string if blocked)
  source      : str
  category    : str
  published   : str  — ISO 8601
  source_weight: float
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx
import trafilatura
from trafilatura.settings import use_config as trafilatura_use_config

from pipeline.dedup import _article_id  # noqa: F401 — shared ID helper
from config import (
    HN_CONFIG,
    MAX_ARTICLE_AGE_DAYS,
    MAX_RAW_ARTICLES,
    NEWSAPI_KEY,
    NEWSAPI_QUERIES,
    REDDIT_SOURCES,
    RSS_FEEDS,
)

log = logging.getLogger(__name__)

# trafilatura: precision mode, no comments
_traf_cfg = trafilatura_use_config()
_traf_cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "10")

_REDDIT_UA = {"User-Agent": "news-digest-bot/1.0"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(entry: Any) -> str:
    """Best-effort ISO date from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _extract_text(url: str) -> str:
    """Fetch and extract full article text. Returns '' on failure."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            favor_precision=True,
            include_comments=False,
            config=_traf_cfg,
        )
        return text or ""
    except Exception as exc:
        log.debug("trafilatura failed for %s: %s", url, exc)
        return ""


def _safe_text(entry: Any) -> str:
    """Pull description/summary text from a feedparser entry."""
    for attr in ("summary", "description", "content"):
        raw = getattr(entry, attr, None)
        if raw:
            if isinstance(raw, list):
                raw = raw[0].get("value", "")
            # strip HTML tags
            return re.sub(r"<[^>]+>", " ", raw).strip()
    return ""


# ── RSS ───────────────────────────────────────────────────────────────────────

def _fetch_rss_feed(feed_cfg: dict) -> list[dict]:
    articles = []
    try:
        parsed = feedparser.parse(feed_cfg["url"])
        for entry in parsed.entries:
            url = getattr(entry, "link", None)
            if not url:
                continue
            articles.append(
                {
                    "id": _article_id(url),
                    "title": getattr(entry, "title", "").strip(),
                    "url": url,
                    "description": _safe_text(entry),
                    "full_text": "",  # filled later in parallel
                    "source": feed_cfg["name"],
                    "category": feed_cfg["category"],
                    "published": _parse_date(entry),
                    "source_weight": feed_cfg.get("weight", 1.0),
                }
            )
    except Exception as exc:
        log.warning("RSS fetch failed for %s: %s", feed_cfg["name"], exc)
    return articles


async def _fetch_all_rss(executor: ThreadPoolExecutor) -> list[dict]:
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(executor, _fetch_rss_feed, f) for f in RSS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
    return articles


# ── NewsAPI ───────────────────────────────────────────────────────────────────

async def _fetch_newsapi(client: httpx.AsyncClient) -> list[dict]:
    if not NEWSAPI_KEY:
        log.info("NEWSAPI_KEY not set — skipping NewsAPI")
        return []

    articles = []
    for query in NEWSAPI_QUERIES:
        try:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params={**query, "apiKey": NEWSAPI_KEY, "sortBy": "publishedAt"},
                timeout=15,
            )
            resp.raise_for_status()
            for item in resp.json().get("articles", []):
                url = item.get("url", "")
                if not url or url == "https://removed.com":
                    continue
                articles.append(
                    {
                        "id": _article_id(url),
                        "title": item.get("title", "").strip(),
                        "url": url,
                        "description": item.get("description", "") or "",
                        "full_text": "",
                        "source": item.get("source", {}).get("name", "NewsAPI"),
                        "category": "general",
                        "published": item.get("publishedAt", datetime.now(timezone.utc).isoformat()),
                        "source_weight": 1.0,
                    }
                )
        except Exception as exc:
            log.warning("NewsAPI query failed (%s): %s", query.get("q"), exc)
    return articles


# ── Reddit ────────────────────────────────────────────────────────────────────

async def _fetch_reddit(client: httpx.AsyncClient) -> list[dict]:
    articles = []
    for src in REDDIT_SOURCES:
        try:
            url = f"https://www.reddit.com/r/{src['subreddit']}/{src['sort']}.json?limit={src['limit']}"
            resp = await client.get(url, headers=_REDDIT_UA, timeout=15)
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            for child in children:
                d = child.get("data", {})
                if d.get("is_self", True):
                    continue  # skip text-only posts
                if d.get("score", 0) < src["min_score"]:
                    continue
                post_url = d.get("url", "")
                if not post_url:
                    continue
                title = d.get("title", "").strip()
                articles.append(
                    {
                        "id": _article_id(post_url),
                        "title": title,
                        "url": post_url,
                        "description": d.get("selftext", "")[:500],
                        "full_text": "",
                        "source": f"Reddit/r/{src['subreddit']}",
                        "category": src["category"],
                        "published": datetime.fromtimestamp(
                            d.get("created_utc", 0), tz=timezone.utc
                        ).isoformat(),
                        "source_weight": 0.9,
                    }
                )
        except Exception as exc:
            log.warning("Reddit fetch failed for r/%s: %s", src["subreddit"], exc)
    return articles


# ── Hacker News ───────────────────────────────────────────────────────────────

async def _fetch_hn(client: httpx.AsyncClient) -> list[dict]:
    articles = []
    try:
        cfg = HN_CONFIG
        resp = await client.get(cfg["url"], params=cfg["params"], timeout=15)
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            url = hit.get("url", "")
            if not url:
                continue
            articles.append(
                {
                    "id": _article_id(url),
                    "title": hit.get("title", "").strip(),
                    "url": url,
                    "description": "",
                    "full_text": "",
                    "source": "Hacker News",
                    "category": cfg["category"],
                    "published": hit.get("created_at", datetime.now(timezone.utc).isoformat()),
                    "source_weight": 1.0,
                }
            )
    except Exception as exc:
        log.warning("HN fetch failed: %s", exc)
    return articles


# ── Date filtering ────────────────────────────────────────────────────────────

def _filter_recent(articles: list[dict], max_age_days: int) -> list[dict]:
    """Drop articles older than max_age_days. Keeps articles with unparseable dates."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    recent = []
    for a in articles:
        try:
            pub_str = a.get("published", "")
            # Handle both "+00:00" and "Z" suffixes
            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                recent.append(a)
        except Exception:
            recent.append(a)  # keep if date can't be parsed
    return recent


# ── Full text extraction (parallel) ──────────────────────────────────────────

async def _enrich_full_text(
    articles: list[dict], executor: ThreadPoolExecutor
) -> list[dict]:
    """Fill full_text for articles that don't have it yet, in parallel."""
    loop = asyncio.get_running_loop()

    async def _enrich(article: dict) -> dict:
        if len(article.get("full_text", "")) >= 200:
            return article
        text = await loop.run_in_executor(executor, _extract_text, article["url"])
        if len(text) >= 200:
            article["full_text"] = text
        else:
            # fall back to description
            article["full_text"] = article.get("description", "")
        return article

    return list(await asyncio.gather(*[_enrich(a) for a in articles]))


# ── Entry point ───────────────────────────────────────────────────────────────

async def fetch_all() -> list[dict]:
    """Fetch from all sources, enrich with full text, return up to MAX_RAW_ARTICLES."""
    logging.basicConfig(level=logging.INFO)

    with ThreadPoolExecutor(max_workers=8) as executor:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            rss, newsapi, reddit, hn = await asyncio.gather(
                _fetch_all_rss(executor),
                _fetch_newsapi(client),
                _fetch_reddit(client),
                _fetch_hn(client),
            )

    all_articles = rss + newsapi + reddit + hn
    log.info(
        "Fetched: RSS=%d NewsAPI=%d Reddit=%d HN=%d  total=%d",
        len(rss), len(newsapi), len(reddit), len(hn), len(all_articles),
    )

    # Drop stale articles before the expensive text extraction
    all_articles = _filter_recent(all_articles, MAX_ARTICLE_AGE_DAYS)
    log.info(
        "After date filter (<%d days): %d articles remain",
        MAX_ARTICLE_AGE_DAYS, len(all_articles),
    )

    # Cap before expensive text extraction
    all_articles = all_articles[:MAX_RAW_ARTICLES]

    with ThreadPoolExecutor(max_workers=10) as executor:
        all_articles = await _enrich_full_text(all_articles, executor)

    log.info("After text enrichment: %d articles ready", len(all_articles))
    return all_articles


if __name__ == "__main__":
    import json

    articles = asyncio.run(fetch_all())
    print(json.dumps(articles[:3], indent=2))
    print(f"\nTotal: {len(articles)} articles")
