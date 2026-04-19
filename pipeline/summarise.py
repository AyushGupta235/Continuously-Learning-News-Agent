"""
xAI Grok deep summarisation for each scored article.

Runs up to SUMMARISE_CONCURRENCY calls concurrently.
Attaches 'summary' field to each article.
"""

import asyncio
import logging

from openai import AsyncOpenAI

from config import (
    XAI_API_KEY,
    XAI_MODEL,
    XAI_SUMMARISE_TEMP,
    SUMMARISE_CONCURRENCY,
)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior analyst writing for a busy professional in Bengaluru, India.\n"
    "Your summaries must prioritize INSIGHT over recitation:\n\n"
    "Structure:\n"
    "1. Lead with the most significant insight or implication (not just what happened)\n"
    "2. Ground it with specific data, evidence, or details that reveal why it matters\n"
    "3. Explain the downstream consequences or second-order effects\n"
    "4. Note what remains uncertain or contested\n\n"
    "Style:\n"
    "- 5-7 sentences (substance over brevity)\n"
    "- Include specific numbers, quotes, or examples that illuminate the insight\n"
    "- Avoid 'this matters because' throat-clearing; show WHY through evidence\n"
    "- Never repeat the headline verbatim\n"
    "- If the story has a contrarian or unintuitive angle, highlight it\n"
    "- No filler, no vagueness. Assume the reader will only read this once."
)

_MAX_FULL_TEXT = 12_000  # chars — leaves headroom in 128k context


def _build_user_prompt(article: dict) -> str:
    text = article.get("full_text") or article.get("description", "")
    return (
        f"Source: {article['source']}\n"
        f"Headline: {article['title']}\n"
        f"Published: {article['published']}\n\n"
        f"Full article:\n{text[:_MAX_FULL_TEXT]}\n\n"
        "Write the briefing now."
    )


async def _summarise_one(
    article: dict, client: AsyncOpenAI, sem: asyncio.Semaphore
) -> dict:
    async with sem:
        try:
            response = await client.chat.completions.create(
                model=XAI_MODEL,
                temperature=XAI_SUMMARISE_TEMP,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(article)},
                ],
            )
            summary = (response.choices[0].message.content or "").strip()
            log.info("Summarised: %s", article["title"][:60])
        except Exception as exc:
            log.error("Summarise failed for %s: %s", article["title"][:60], exc)
            summary = article.get("description", "")[:500]

        return {**article, "summary": summary}


async def summarise_articles(articles: list[dict]) -> list[dict]:
    sem = asyncio.Semaphore(SUMMARISE_CONCURRENCY)
    async with AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1") as client:
        tasks = [_summarise_one(a, client, sem) for a in articles]
        results = await asyncio.gather(*tasks)
    log.info("Summarised %d articles", len(results))
    return list(results)


if __name__ == "__main__":
    import asyncio as _asyncio
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup
    from pipeline.filter import score_articles

    articles = _asyncio.run(fetch_all())
    articles = dedup(articles)
    articles = score_articles(articles)
    summarised = _asyncio.run(summarise_articles(articles))
    for a in summarised[:3]:
        print(f"\n=== {a['title']} ===")
        print(a["summary"])
