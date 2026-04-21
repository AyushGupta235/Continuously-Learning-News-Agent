"""
Final digest assembly.

1. Single xAI call: writes a 2-sentence intro and returns optimal story order.
2. Renders the HTML email via Jinja2 template.
3. Writes a digest_manifest_{date}.json for the feedback tracker.
"""

import json
import logging
import re
from datetime import date, timezone
from pathlib import Path

from openai import OpenAI
from jinja2 import Environment, FileSystemLoader

from config import (
    AMP_TEMPLATE_PATH,
    DATA_DIR,
    MANIFEST_DIR,
    XAI_API_KEY,
    XAI_COMPOSE_TEMP,
    XAI_MODEL,
    MAX_DIGEST_STORIES,
    MIN_DIGEST_STORIES,
    TEMPLATE_PATH,
    TRACKER_BASE_URL,
)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are the editor of a curated daily briefing. "
    "Given a list of today's top stories with their summaries, do two things:\n"
    "1. Write a 2-sentence 'Today in brief' that captures the day's defining theme.\n"
    "2. Return the stories in the best reading order (most important first, "
    "with natural topic flow — don't cluster all tech then all geopolitics).\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    '{"intro": "...", "ordered_story_ids": ["id1", "id2", ...]}'
)


def _stories_payload(stories: list[dict]) -> str:
    items = [
        {
            "id": s["id"],
            "title": s["title"],
            "summary": s.get("summary", "")[:300],
            "category": s["category"],
            "source": s["source"],
        }
        for s in stories
    ]
    return json.dumps(items, ensure_ascii=False)


def _parse_compose_response(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        log.warning("Could not find JSON in xAI response")
        return {"intro": "", "ordered_story_ids": []}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error in compose response: %s", exc)
        return {"intro": "", "ordered_story_ids": []}


def _order_stories(stories: list[dict], ordered_ids: list[str]) -> list[dict]:
    """Re-order stories per xAI's suggestion; fall back to relevance order."""
    id_to_story = {s["id"]: s for s in stories}
    ordered = [id_to_story[oid] for oid in ordered_ids if oid in id_to_story]
    # append any stories xAI omitted
    seen = set(ordered_ids)
    ordered += [s for s in stories if s["id"] not in seen]
    return ordered[:MAX_DIGEST_STORIES]


def compose(
    stories: list[dict],
    user_id: str = "default",
    manifest_dir: str | None = None,
) -> tuple[str, str, dict]:
    """
    Returns (rendered_html, rendered_amp_html, manifest_dict).
    manifest_dict maps story_id → {url, source, category, title}.

    user_id:      used to namespace the manifest file and feedback tracker URLs.
    manifest_dir: root directory for manifests; defaults to MANIFEST_DIR from config.
                  Manifest is written to {manifest_dir}/{user_id}/digest_manifest_{date}.json.
    """
    # Limit to reasonable number for xAI call
    stories = stories[:MAX_DIGEST_STORIES]
    client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
    today = date.today()
    date_str = today.strftime("%Y-%m-%d")

    # xAI: intro + ordering
    try:
        response = client.chat.completions.create(
            model=XAI_MODEL,
            temperature=XAI_COMPOSE_TEMP,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Today's date: {date_str}\n\nStories:\n{_stories_payload(stories)}",
                },
            ],
        )
        raw = response.choices[0].message.content or ""
        compose_data = _parse_compose_response(raw)
    except Exception as exc:
        log.error("xAI compose failed: %s", exc)
        compose_data = {"intro": "", "ordered_story_ids": [s["id"] for s in stories]}

    intro = compose_data.get("intro", "")
    ordered_ids = compose_data.get("ordered_story_ids", [])
    ordered_stories = _order_stories(stories, ordered_ids)

    log.info(
        "Compose: intro=%s, %d stories ordered", bool(intro), len(ordered_stories)
    )

    # Render HTML + AMP HTML (both templates live in the same directory)
    template_dir = str(Path(TEMPLATE_PATH).parent)
    env = Environment(loader=FileSystemLoader(template_dir))

    render_vars = dict(
        intro=intro,
        stories=ordered_stories,
        date_display=today.strftime("%A, %d %b %Y"),
        tracker_base=TRACKER_BASE_URL,
        date_str=date_str,
        user_id=user_id,
    )

    rendered_html = env.get_template(Path(TEMPLATE_PATH).name).render(**render_vars)
    rendered_amp_html = env.get_template(Path(AMP_TEMPLATE_PATH).name).render(**render_vars)

    # Manifest for feedback tracker
    manifest = {
        s["id"]: {
            "url": s["url"],
            "source": s["source"],
            "category": s["category"],
            "title": s["title"],
        }
        for s in ordered_stories
    }

    # Persist manifest — namespaced by user_id
    mdir = Path(manifest_dir or MANIFEST_DIR) / user_id
    mdir.mkdir(parents=True, exist_ok=True)
    manifest_path = mdir / f"digest_manifest_{date_str}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("Manifest written to %s", manifest_path)

    return rendered_html, rendered_amp_html, manifest


if __name__ == "__main__":
    import asyncio
    from pipeline.ingest import fetch_all
    from pipeline.dedup import dedup
    from pipeline.filter import score_articles
    from pipeline.summarise import summarise_articles
    from pipeline.cluster import cluster_stories

    articles = asyncio.run(fetch_all())
    articles = dedup(articles)
    articles = score_articles(articles)
    articles = asyncio.run(summarise_articles(articles))
    stories = cluster_stories(articles)
    html, amp_html, manifest = compose(stories)
    out = Path("data/digest_preview.html")
    out.write_text(html)
    out_amp = Path("data/digest_preview.amp.html")
    out_amp.write_text(amp_html)
    print(f"Preview written to {out}  ({len(html)} chars)")
    print(f"AMP preview written to {out_amp}  ({len(amp_html)} chars)")
    print(f"Manifest has {len(manifest)} stories")
