"""
Groq-based relevance scoring.

Batches articles (FILTER_BATCH_SIZE per call) against the interest profile.
Keeps articles scoring >= FILTER_SCORE_THRESHOLD, sorted descending by score.
Caps output at MAX_SCORED_ARTICLES.
"""

import json
import logging
import re
from pathlib import Path

from groq import Groq

from config import (
    FILTER_BATCH_SIZE,
    FILTER_SCORE_THRESHOLD,
    GROQ_API_KEY,
    GROQ_FILTER_TEMP,
    GROQ_MODEL,
    INTEREST_PROFILE_PATH,
    MAX_SCORED_ARTICLES,
)

log = logging.getLogger(__name__)

def _get_client() -> Groq:
    return Groq(api_key=GROQ_API_KEY)


def _load_profile() -> str:
    return Path(INTEREST_PROFILE_PATH).read_text()


def _build_user_prompt(batch: list[dict]) -> str:
    items = [
        {
            "id": a["id"],
            "title": a["title"],
            "description": a["description"][:400],
            "source": a["source"],
            "category": a["category"],
        }
        for a in batch
    ]
    return (
        f"You are a news relevance scorer. Below are {len(items)} articles.\n"
        "For each, return a JSON array with: "
        '[{"id": "...", "score": 0-10, "reason": "..."}]\n'
        "Score 0 = completely irrelevant or clickbait. Score 10 = directly on-topic, substantive.\n"
        "Penalise heavily: celebrity gossip, sports scores, stock tickers without context,\n"
        "sensational headlines with no analytical content, PR announcements.\n"
        "Reward: policy analysis, original reporting, expert commentary, data-backed arguments.\n\n"
        f"Articles:\n{json.dumps(items, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON. No preamble."
    )


def _parse_scores(text: str) -> list[dict]:
    """Extract JSON array from model output, tolerating minor formatting issues."""
    # find first '[' and last ']'
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        log.warning("Could not find JSON array in Groq response")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error in filter response: %s", exc)
        return []


def score_articles(articles: list[dict]) -> list[dict]:
    """
    Score all articles and return those above threshold, sorted by score desc.
    Attaches 'relevance_score' and 'score_reason' to each surviving article.
    """
    profile = _load_profile()
    client = _get_client()

    score_map: dict[str, dict] = {}

    batches = [
        articles[i : i + FILTER_BATCH_SIZE]
        for i in range(0, len(articles), FILTER_BATCH_SIZE)
    ]
    log.info("Scoring %d articles in %d batches", len(articles), len(batches))

    for i, batch in enumerate(batches):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=GROQ_FILTER_TEMP,
                messages=[
                    {"role": "system", "content": profile},
                    {"role": "user", "content": _build_user_prompt(batch)},
                ],
            )
            raw = response.choices[0].message.content or ""
            scores = _parse_scores(raw)
            for item in scores:
                score_map[item["id"]] = {
                    "relevance_score": float(item.get("score", 0)),
                    "score_reason": item.get("reason", ""),
                }
            log.info("Batch %d/%d scored: %d results", i + 1, len(batches), len(scores))
        except Exception as exc:
            log.error("Groq scoring failed for batch %d: %s", i + 1, exc)

    # Attach scores, filter, sort
    scored = []
    for a in articles:
        info = score_map.get(a["id"])
        if info and info["relevance_score"] >= FILTER_SCORE_THRESHOLD:
            a = dict(a)
            a["relevance_score"] = info["relevance_score"]
            a["score_reason"] = info["score_reason"]
            scored.append(a)

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    result = scored[:MAX_SCORED_ARTICLES]
    log.info(
        "Filter: %d → %d articles (threshold=%s, cap=%d)",
        len(articles), len(result), FILTER_SCORE_THRESHOLD, MAX_SCORED_ARTICLES,
    )
    return result


if __name__ == "__main__":
    import asyncio
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup

    articles = asyncio.run(fetch_all())
    articles = dedup(articles)
    scored = score_articles(articles)
    for a in scored[:5]:
        print(f"[{a['relevance_score']:.1f}] {a['title'][:80]}  ({a['source']})")
        print(f"       {a['score_reason']}")
    print(f"\nTotal kept: {len(scored)}")
