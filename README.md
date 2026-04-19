# AI News Digest

A self-improving daily news briefing that emails you at 9 AM IST.

- **Sources**: RSS feeds, NewsAPI, Reddit, Hacker News
- **AI**: xAI Grok API (`grok-4-1-fast-non-reasoning`) for scoring, summarising, and composing
- **Email**: Resend API
- **Feedback loop**: click "Useful" / "Skip" on stories → weekly xAI profile rewrite
- **Scheduling**: GitHub Actions (free)

## Quick start

```bash
pip install -r requirements.txt

export XAI_API_KEY=...
export RESEND_API_KEY=...
export NEWSAPI_KEY=...
export DIGEST_EMAIL=you@example.com
export TRACKER_BASE_URL=https://your-railway-app.up.railway.app

# Dry run — skips email, writes data/digest_preview.html
python run_pipeline.py --dry-run

# Full send
python run_pipeline.py
```

## Project structure

```
pipeline/       Core pipeline steps (ingest → dedup → filter → summarise → cluster → compose → deliver)
feedback/       Tracking server, signal aggregation, weekly profile rewrite
data/           Interest profile, feedback log, weekly summary, manifests
templates/      Jinja2 email template
tests/          Unit tests (pytest)
.github/        Daily (9 AM IST) and weekly (Sunday 11 PM IST) workflows
```

## GitHub Secrets

| Secret | Where to get it |
|---|---|
| `XAI_API_KEY` | console.x.ai |
| `RESEND_API_KEY` | resend.com |
| `NEWSAPI_KEY` | newsapi.org |
| `DIGEST_EMAIL` | Your email |
| `TRACKER_BASE_URL` | Railway deployment URL |

## Feedback server (Railway)

Deploy `feedback/server.py` as a standalone Flask app on Railway.
Set `FEEDBACK_LOG_PATH` and `MANIFEST_DIR` env vars pointing to a persistent volume
(or a GitHub Gist — see `feedback/server.py` comments).

## Customising your profile

Edit `data/interest-profile.md` directly, or let the weekly xAI rewrite
(`feedback/rewrite_profile.py`) evolve it from your click signals.

## Running tests

```bash
pytest tests/ -v
```
