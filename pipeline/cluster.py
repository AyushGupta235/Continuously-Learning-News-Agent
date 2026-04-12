"""
Group related stories that cover the same underlying event.

Method: title similarity (difflib) + shared named entities (proper noun regex).
For each cluster of 2+ articles:
  - Keep the highest relevance_score article as primary
  - Append a one-line "Also covered" note from secondary sources

Output: list of story dicts, each with:
  - all primary article fields
  - summary: str
  - also_covered: List[str]
  - category: str
  - relevance_score: float
"""

import logging
import re
from difflib import SequenceMatcher

log = logging.getLogger(__name__)

_TITLE_SIM_THRESHOLD = 0.60   # slightly looser than dedup — same story, different angles
_MIN_SHARED_ENTITIES = 2


def _title_key(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _title_key(a), _title_key(b)).ratio()


def _extract_entities(text: str) -> set[str]:
    """Extract capitalised words/phrases as a rough entity proxy."""
    # Match sequences of Title-Cased words (2+ chars) not at sentence start
    tokens = re.findall(r"\b[A-Z][a-z]{1,}\b", text)
    # Filter common stop-words
    stops = {
        "The", "A", "An", "In", "Of", "For", "To", "And", "Or", "But",
        "Is", "Are", "Was", "Were", "Has", "Have", "This", "That", "With",
        "Its", "It", "On", "At", "By", "As", "Be",
    }
    return {t for t in tokens if t not in stops}


def _are_same_story(a: dict, b: dict) -> bool:
    sim = _title_sim(a["title"], b["title"])
    if sim >= _TITLE_SIM_THRESHOLD:
        return True
    # entity overlap fallback
    ea = _extract_entities(a["title"] + " " + a.get("description", ""))
    eb = _extract_entities(b["title"] + " " + b.get("description", ""))
    shared = ea & eb
    return len(shared) >= _MIN_SHARED_ENTITIES


def _one_line_note(article: dict) -> str:
    """Short cross-source note for 'also covered'."""
    summary = article.get("summary", article.get("description", ""))
    first_sentence = re.split(r"(?<=[.!?])\s", summary.strip())[0][:120]
    return f"{article['source']}: {first_sentence}"


def cluster_stories(articles: list[dict]) -> list[dict]:
    """Group articles into story clusters and return the flattened story list."""
    clusters: list[list[dict]] = []

    for article in articles:
        placed = False
        for cluster in clusters:
            # compare against the primary (first/best) article in cluster
            if _are_same_story(cluster[0], article):
                cluster.append(article)
                placed = True
                break
        if not placed:
            clusters.append([article])

    stories = []
    for cluster in clusters:
        # Sort by relevance_score descending
        cluster.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        primary = dict(cluster[0])
        also = [_one_line_note(a) for a in cluster[1:]]
        primary["also_covered"] = also
        stories.append(primary)

    # Sort final list by relevance_score
    stories.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    log.info(
        "Cluster: %d articles → %d stories (%d multi-source clusters)",
        len(articles),
        len(stories),
        sum(1 for c in clusters if len(c) > 1),
    )
    return stories


if __name__ == "__main__":
    import asyncio
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup
    from pipeline.filter import score_articles
    from pipeline.summarise import summarise_articles

    articles = asyncio.run(fetch_all())
    articles = dedup(articles)
    articles = score_articles(articles)
    articles = asyncio.run(summarise_articles(articles))
    stories = cluster_stories(articles)
    for s in stories[:5]:
        also = "; ".join(s["also_covered"]) if s["also_covered"] else "—"
        print(f"[{s['relevance_score']:.1f}] {s['title'][:70]}")
        print(f"  Also: {also[:80]}")
