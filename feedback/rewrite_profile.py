"""
Weekly interest profile rewrite — run every Sunday via GitHub Actions.

Reads the current profile + weekly_summary.json, asks xAI Grok to produce
an incrementally-updated profile, writes it back to data/interest-profile.md.
"""

import json
import logging
from pathlib import Path

from openai import OpenAI

from config import (
    XAI_API_KEY,
    XAI_MODEL,
    XAI_PROFILE_TEMP,
    INTEREST_PROFILE_PATH,
    WEEKLY_SUMMARY_PATH,
)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You maintain a reader's news interest profile used to filter and score daily articles.\n"
    "The profile is a plain-text Markdown file."
)


def _format_summary(summary: dict) -> str:
    lines = [
        f"Window: last {summary.get('window_days', 7)} days  "
        f"(total signals: {summary.get('total_signals', 0)})",
        "",
        "By category:",
    ]
    for cat, counts in summary.get("by_category", {}).items():
        lines.append(f"  {cat}: useful={counts.get('useful',0)}  skip={counts.get('skip',0)}")
    lines += ["", "By source (top sources by useful):"]
    by_src = summary.get("by_source", {})
    sorted_src = sorted(by_src.items(), key=lambda x: -x[1].get("useful", 0))
    for src, counts in sorted_src[:10]:
        lines.append(f"  {src}: useful={counts.get('useful',0)}  skip={counts.get('skip',0)}")
    lines += [
        "",
        "Top useful keywords: " + ", ".join(summary.get("top_useful_keywords", [])),
        "Top skipped keywords: " + ", ".join(summary.get("top_skipped_keywords", [])),
    ]
    return "\n".join(lines)


def rewrite_profile() -> str:
    profile_path = Path(INTEREST_PROFILE_PATH)
    summary_path = Path(WEEKLY_SUMMARY_PATH)

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    current_profile = profile_path.read_text()

    if not summary_path.exists():
        log.warning("No weekly summary found — skipping profile rewrite")
        return current_profile

    summary = json.loads(summary_path.read_text())
    formatted_summary = _format_summary(summary)

    user_prompt = (
        "Here is the reader's current interest profile:\n"
        "---\n"
        f"{current_profile}\n"
        "---\n\n"
        "Here is the signal data from the past 7 days:\n"
        f"{formatted_summary}\n\n"
        "Based on this, rewrite the interest profile to better reflect what the reader "
        "actually engages with. Rules:\n"
        "- Keep the same Markdown structure and rough length\n"
        "- Strengthen topics/sources with high useful signals\n"
        "- Downgrade or add caveats to sources with consistent skip signals\n"
        "- Add any new emerging topics inferred from useful story keywords\n"
        "- Do NOT make radical changes — adjust weights and emphasis, don't rewrite from scratch\n"
        "- Return ONLY the updated Markdown. No explanation."
    )

    client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
    response = client.chat.completions.create(
        model=XAI_MODEL,
        temperature=XAI_PROFILE_TEMP,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    updated_profile = (response.choices[0].message.content or "").strip()

    if len(updated_profile) < 100:
        log.error("xAI returned suspiciously short profile — aborting rewrite")
        return current_profile

    profile_path.write_text(updated_profile + "\n")
    log.info("Profile rewritten: %d chars → %d chars", len(current_profile), len(updated_profile))
    return updated_profile


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    updated = rewrite_profile()
    print("=== Updated profile ===")
    print(updated[:500])
