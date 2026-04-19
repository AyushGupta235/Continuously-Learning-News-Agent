"""
Daily signal aggregation — run after digest delivery in GitHub Actions.

Reads feedback_log.jsonl, computes last-7-day tallies, writes weekly_summary.json.
Also extracts top useful/skipped keywords via TF-IDF.
"""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

from config import FEEDBACK_LOG_PATH, WEEKLY_SUMMARY_PATH, FEEDBACK_DIR

log = logging.getLogger(__name__)

_WINDOW_DAYS = 7
_TOP_K_KEYWORDS = 5


def _load_signals(since: date, log_path: Path | None = None) -> list[dict]:
    log_path = log_path or Path(FEEDBACK_LOG_PATH)
    if not log_path.exists():
        return []
    signals = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec_date = date.fromisoformat(rec.get("date", "1970-01-01"))
                if rec_date >= since:
                    signals.append(rec)
            except Exception:
                continue
    return signals


def _extract_keywords(titles: list[str], top_k: int = _TOP_K_KEYWORDS) -> list[str]:
    if not titles:
        return []
    try:
        vec = TfidfVectorizer(
            max_features=200,
            stop_words="english",
            ngram_range=(1, 2),
        )
        vec.fit_transform(titles)
        vocab = vec.get_feature_names_out()
        scores = vec.idf_
        ranked = sorted(zip(vocab, scores), key=lambda x: -x[1])
        return [kw for kw, _ in ranked[:top_k]]
    except Exception as exc:
        log.warning("TF-IDF failed: %s", exc)
        return []


def aggregate(user_id: str | None = None) -> dict:
    """
    Aggregate feedback signals for the given user.

    user_id: slug from users/registry.yaml. When provided, reads from
             data/feedback/{user_id}/feedback_log.jsonl and writes
             data/feedback/{user_id}/weekly_summary.json.
             Falls back to legacy single-user paths when None.
    """
    today = date.today()
    since = today - timedelta(days=_WINDOW_DAYS)

    if user_id:
        log_path = Path(FEEDBACK_DIR) / user_id / "feedback_log.jsonl"
        out_path = Path(FEEDBACK_DIR) / user_id / "weekly_summary.json"
    else:
        log_path = Path(FEEDBACK_LOG_PATH)
        out_path = Path(WEEKLY_SUMMARY_PATH)

    signals = _load_signals(since, log_path=log_path)

    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"useful": 0, "skip": 0})
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: {"useful": 0, "skip": 0})
    useful_titles: list[str] = []
    skip_titles: list[str] = []

    for rec in signals:
        cat = rec.get("category", "unknown")
        src = rec.get("source", "unknown")
        sig = rec.get("signal", "")
        title = rec.get("title", "")

        if sig in ("useful", "skip"):
            by_category[cat][sig] += 1
            by_source[src][sig] += 1
            if sig == "useful" and title:
                useful_titles.append(title)
            elif sig == "skip" and title:
                skip_titles.append(title)

    summary = {
        "generated": today.isoformat(),
        "window_days": _WINDOW_DAYS,
        "total_signals": len(signals),
        "by_category": dict(by_category),
        "by_source": dict(by_source),
        "top_useful_keywords": _extract_keywords(useful_titles),
        "top_skipped_keywords": _extract_keywords(skip_titles),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    log.info("Weekly summary written to %s  (%d signals)", out_path, len(signals))
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = aggregate()
    print(json.dumps(result, indent=2))
