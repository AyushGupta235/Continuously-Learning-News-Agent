"""
Feedback tracking endpoint — deploy on Railway (free tier).

GET /signal?id={story_id}&v={useful|skip}&date={YYYY-MM-DD}&user={user_id}

  1. Validates the user_id against a slug allowlist (prevents path traversal)
  2. Loads the digest manifest for that date + user to resolve URL + metadata
  3. Appends signal to data/feedback/{user_id}/feedback_log.jsonl
  4. Redirects browser to the article URL

Environment variables:
  MANIFEST_DIR   — root dir for per-user manifests (default: data/manifests)
                   Resolved path: {MANIFEST_DIR}/{user_id}/digest_manifest_{date}.json
  FEEDBACK_DIR   — root dir for per-user feedback logs (default: data/feedback)
                   Resolved path: {FEEDBACK_DIR}/{user_id}/feedback_log.jsonl
  VALID_USER_IDS — comma-separated list of allowed user slugs (e.g. "ayush,priya")
                   If unset, any well-formed slug is accepted (alphanumeric + _ -)
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, request, make_response

app = Flask(__name__)

MANIFEST_DIR = os.environ.get("MANIFEST_DIR", "data/manifests")
FEEDBACK_DIR = os.environ.get("FEEDBACK_DIR", "data/feedback")

VALID_SIGNALS = {"useful", "skip"}

# Optional explicit allowlist of user slugs loaded from env
_ALLOWLIST_ENV = os.environ.get("VALID_USER_IDS", "")
_ALLOWED_USERS: set[str] = set(_ALLOWLIST_ENV.split(",")) - {""} if _ALLOWLIST_ENV else set()

# Slug pattern — prevents directory traversal and injection
_SLUG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def _is_valid_user(user_id: str) -> bool:
    if not _SLUG_RE.match(user_id):
        return False
    if _ALLOWED_USERS:
        return user_id in _ALLOWED_USERS
    return True


def _load_manifest(date_str: str, user_id: str) -> dict:
    path = Path(MANIFEST_DIR) / user_id / f"digest_manifest_{date_str}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _append_signal(record: dict, user_id: str) -> None:
    log_path = Path(FEEDBACK_DIR) / user_id / "feedback_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _cors(response):
    """
    Add CORS headers for:
      - file:// / localhost origins (browser preview fetch calls)
      - AMP for Email: echo back __amp_source_origin so Gmail renders the form
    """
    origin = request.headers.get("Origin", "")
    if not origin or origin == "null" or origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
        response.headers["Access-Control-Allow-Origin"] = origin or "*"

    # AMP requires the server to echo __amp_source_origin back as a response header
    amp_source_origin = request.args.get("__amp_source_origin", "")
    if amp_source_origin:
        response.headers["AMP-Access-Control-Allow-Source-Origin"] = amp_source_origin
        expose = response.headers.get("Access-Control-Expose-Headers", "")
        extra = "AMP-Access-Control-Allow-Source-Origin"
        response.headers["Access-Control-Expose-Headers"] = f"{expose},{extra}".strip(",")
        # Allow the AMP origin itself
        response.headers["Access-Control-Allow-Origin"] = amp_source_origin

    return response


@app.route("/signal", methods=["GET", "POST"])
def signal():
    # AMP forms POST; regular links GET — read from the right source
    src = request.form if request.method == "POST" else request.args

    story_id = src.get("id", "").strip()
    vote = src.get("v", "").strip()
    date_str = src.get("date", "").strip()
    user_id = src.get("user", "default").strip()
    noredirect = request.args.get("noredirect", "0") == "1"

    if not story_id or vote not in VALID_SIGNALS or not date_str:
        abort(400, "Missing or invalid parameters")

    if not _is_valid_user(user_id):
        abort(400, "Invalid user")

    manifest = _load_manifest(date_str, user_id)
    story_meta = manifest.get(story_id, {})
    article_url = story_meta.get("url", "")

    record = {
        "story_id": story_id,
        "signal": vote,
        "date": date_str,
        "user": user_id,
        "ts": int(time.time()),
        "source": story_meta.get("source", "unknown"),
        "category": story_meta.get("category", "unknown"),
        "title": story_meta.get("title", ""),
    }
    _append_signal(record, user_id)

    if noredirect:
        return _cors(make_response("ok", 200))

    label = "👍 Useful" if vote == "useful" else "👎 Skip"
    title = story_meta.get("title", "")
    article_link = (
        f'<a href="{article_url}" style="display:inline-block;margin-top:16px;padding:10px 20px;'
        f'background:#1a1a2e;color:#fff;border-radius:6px;text-decoration:none;font-size:14px;">Read article →</a>'
        if article_url else ""
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Feedback recorded</title></head>
<body style="margin:0;padding:40px 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f4f4;text-align:center;">
  <div style="max-width:400px;margin:0 auto;background:#fff;border-radius:8px;padding:32px 24px;">
    <p style="font-size:32px;margin:0 0 8px;">✓</p>
    <p style="font-size:16px;font-weight:600;color:#1a1a2e;margin:0 0 6px;">{label} — noted!</p>
    {'<p style="font-size:13px;color:#666;margin:0 0 16px;">' + title + '</p>' if title else ''}
    {article_link}
  </div>
</body>
</html>"""
    return _cors(make_response(html, 200))


@app.route("/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
