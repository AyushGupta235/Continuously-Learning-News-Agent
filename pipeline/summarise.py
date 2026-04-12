"""
Groq deep summarisation for each scored article.

Runs up to SUMMARISE_CONCURRENCY calls concurrently.
Attaches 'summary' field to each article.
"""

import asyncio
import logging

from groq import AsyncGroq

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_SUMMARISE_TEMP,
    SUMMARISE_CONCURRENCY,
)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior analyst writing for a busy professional in Bengaluru, India.\n"
    "Your summaries must:\n"
    "- Lead with the single most important fact or development\n"
    "- Explain WHY it matters (consequences, implications, context)\n"
    "- Note what is still uncertain or contested\n"
    "- Be 4-5 sentences maximum. No filler. No 'In conclusion.'\n"
    "- Never repeat the headline verbatim as the first sentence"
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
    article: dict, client: AsyncGroq, sem: asyncio.Semaphore
) -> dict:
    async with sem:
        try:
            response = await client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=GROQ_SUMMARISE_TEMP,
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
    async with AsyncGroq(api_key=GROQ_API_KEY) as client:
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
