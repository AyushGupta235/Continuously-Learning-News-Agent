"""
Feedback tracking endpoint — deploy on Railway (free tier).

GET /signal?id={story_id}&v={useful|skip}&date={YYYY-MM-DD}

  1. Loads the digest manifest for that date to resolve URL + metadata
  2. Appends signal to feedback_log.jsonl
  3. Redirects browser to the article URL

Environment variables required on Railway:
  FEEDBACK_LOG_PATH   — path to feedback_log.jsonl (persistent volume mount)
  MANIFEST_DIR        — directory where digest_manifest_*.json files are stored
                        (or clone the repo and point here; see notes below)

For simplicity in a single-person deployment, both files can live in the same
repo and Railway can clone it on startup. Alternatively, use a GitHub Gist for
the log (append via GitHub API) — this avoids needing a persistent volume.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, request

app = Flask(__name__)

FEEDBACK_LOG_PATH = os.environ.get("FEEDBACK_LOG_PATH", "data/feedback_log.jsonl")
MANIFEST_DIR = os.environ.get("MANIFEST_DIR", "data")

VALID_SIGNALS = {"useful", "skip"}


def _load_manifest(date_str: str) -> dict:
    path = Path(MANIFEST_DIR) / f"digest_manifest_{date_str}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _append_signal(record: dict) -> None:
    log_path = Path(FEEDBACK_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@app.route("/signal")
def signal():
    story_id = request.args.get("id", "").strip()
    vote = request.args.get("v", "").strip()
    date_str = request.args.get("date", "").strip()

    if not story_id or vote not in VALID_SIGNALS or not date_str:
        abort(400, "Missing or invalid parameters")

    manifest = _load_manifest(date_str)
    story_meta = manifest.get(story_id, {})
    article_url = story_meta.get("url", "")

    record = {
        "story_id": story_id,
        "signal": vote,
        "date": date_str,
        "ts": int(time.time()),
        "source": story_meta.get("source", "unknown"),
        "category": story_meta.get("category", "unknown"),
        "title": story_meta.get("title", ""),
    }
    _append_signal(record)

    if article_url:
        return redirect(article_url, code=302)
    return "Signal recorded.", 200


@app.route("/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
