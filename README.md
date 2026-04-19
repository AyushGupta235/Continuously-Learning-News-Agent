# AI News Digest

A self-improving daily news briefing with multi-user support. Each recipient gets their own personalised digest.

- **Sources**: RSS feeds, NewsAPI, Reddit, Hacker News
- **AI**: xAI Grok API (`grok-4-1-fast-non-reasoning`) for scoring, summarising, and composing
- **Email**: Gmail SMTP with per-user delivery
- **Feedback loop**: click "Useful" / "Skip" on stories → weekly xAI profile rewrite (per user)
- **Scheduling**: GitHub Actions (free)

## Quick start

### Single-user mode (existing setup)

```bash
pip install -r requirements.txt

export XAI_API_KEY=...
export GMAIL_APP_PASSWORD=...          # From https://myaccount.google.com/apppasswords
export NEWSAPI_KEY=...
export DIGEST_EMAIL=your-email@gmail.com
export TRACKER_BASE_URL=https://your-railway-app.up.railway.app

# Dry run — skips email, writes data/digest_preview.html
python run_pipeline.py --dry-run

# Full send (uses data/interest-profile.md and DIGEST_EMAIL)
python run_pipeline.py
```

### Multi-user mode

1. Update `users/registry.yaml` with your email and any friends' entries:

```yaml
users:
  - id: ayush
    name: Ayush Gupta
    email: ayush@example.com
    profile: users/profiles/a3f8b2c1.md
    active: true

  - id: priya
    name: Priya Sharma
    email: priya@example.com
    profile: users/profiles/7f3c9a1d.md
    active: true
```

2. Create profile files with UUID filenames (obfuscation):

```bash
# Generate UUID: python -c "import uuid; print(uuid.uuid4().hex[:8])"
# Create users/profiles/a3f8b2c1.md with Markdown interest profile
# (copy from data/interest-profile.md as a starting point)
```

3. Run the multi-user pipeline:

```bash
# Dry run
python -m pipeline.fan_out --dry-run

# Full send
python -m pipeline.fan_out

# For specific users only
python -m pipeline.fan_out --users ayush,priya
```

## Project structure

```
pipeline/
  fan_out.py      Multi-user orchestrator (shared ingest/dedup, per-user filter/compose)
  ingest.py       Fetch articles from RSS, NewsAPI, Reddit, HN
  dedup.py        URL + title similarity deduplication
  filter.py       xAI scoring against interest profile
  summarise.py    xAI 5-7 sentence summaries (concurrent)
  cluster.py      Group same-story articles
  compose.py      xAI story ordering + HTML rendering
  deliver.py      Gmail SMTP send

feedback/
  server.py       Flask tracking endpoint (deploy on Railway)
  aggregate.py    7-day signal tallies + TF-IDF keywords
  rewrite_profile.py    Weekly xAI profile rewrite

users/
  registry.yaml   User list (id, name, email, profile path)
  profiles/       UUID-named .md profile files (one per user)

data/
  interest-profile.md    Legacy single-user profile (fallback)
  feedback/{user_id}/    Per-user feedback logs and summaries
  manifests/{user_id}/   Per-user story manifests (feedback tracker lookup)

templates/        Jinja2 email template

tests/            Unit tests (pytest)

.github/          Daily (9 AM IST) and weekly (Sunday 11 PM IST) workflows
```

## GitHub Secrets & Variables

| Name | Type | Where to get it |
|---|---|---|
| `XAI_API_KEY` | Secret | console.x.ai |
| `GMAIL_APP_PASSWORD` | Secret | https://myaccount.google.com/apppasswords |
| `NEWSAPI_KEY` | Secret | newsapi.org |
| `DIGEST_EMAIL` | Secret | Sender Gmail address (for SMTP auth) |
| `TRACKER_BASE_URL` | Variable | Railway deployment URL |

**Note**: User emails are stored in `users/registry.yaml` (committed), not as secrets.

## Feedback server (Railway)

Deploy `feedback/server.py` as a standalone Flask app on Railway.
Set `FEEDBACK_LOG_PATH` and `MANIFEST_DIR` env vars pointing to a persistent volume
(or a GitHub Gist — see `feedback/server.py` comments).

## Adding a new user

1. Generate a UUID-based filename for obfuscation:
   ```bash
   python -c "import uuid; print(uuid.uuid4().hex[:8])"
   ```

2. Create `users/profiles/{uuid}.md` with their Markdown interest profile.

3. Add an entry to `users/registry.yaml`:
   ```yaml
   - id: friend-slug
     name: Friend Full Name
     email: friend@example.com
     profile: users/profiles/{uuid}.md
     active: true
   ```

4. Push. The next scheduled run (9 AM IST) will send them their personalised digest.

## Customising a profile

Edit the `.md` file directly, or let the weekly xAI rewrite (`feedback/rewrite_profile.py`)
evolve it from their click signals (Useful/Skip). Per-user rewrites run every Sunday 11 PM IST.

## Running tests

```bash
pytest tests/ -v
```
