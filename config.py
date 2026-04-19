"""
Source registry and global constants for the news digest pipeline.
"""

import os

# ── xAI Grok ─────────────────────────────────────────────────────────────────
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_MODEL = "grok-4-1-fast-non-reasoning"
XAI_FILTER_TEMP = 0.1
XAI_SUMMARISE_TEMP = 0.5
XAI_COMPOSE_TEMP = 0.4
XAI_PROFILE_TEMP = 0.2

# ── External APIs ─────────────────────────────────────────────────────────────
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL", "")
TRACKER_BASE_URL = os.environ.get("TRACKER_BASE_URL", "http://localhost:5000")

# ── Pipeline limits ───────────────────────────────────────────────────────────
MAX_RAW_ARTICLES = 250       # Cap before dedup
FILTER_SCORE_THRESHOLD = 6   # Articles scoring below this are dropped
MAX_SCORED_ARTICLES = 30     # Articles passed to summarise step
FILTER_BATCH_SIZE = 20       # Articles per xAI scoring call
SUMMARISE_CONCURRENCY = 5    # Max simultaneous xAI summarise calls
MAX_DIGEST_STORIES = 12      # Stories in final email
MIN_DIGEST_STORIES = 8

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Technology & AI
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": "tech",
        "weight": 1.3,
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "tech",
        "weight": 1.1,
    },
    {
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "category": "tech",
        "weight": 0.9,
    },
    {
        "name": "Import AI (Jack Clark)",
        "url": "https://importai.substack.com/feed",
        "category": "tech",
        "weight": 1.4,
    },
    # Business & Markets
    {
        "name": "The Economist",
        "url": "https://www.economist.com/rss",
        "category": "business",
        "weight": 1.4,
    },
    {
        "name": "Financial Times",
        "url": "https://www.ft.com/rss/home",
        "category": "business",
        "weight": 1.2,
    },
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "category": "business",
        "weight": 1.0,
    },
    # Geopolitics & World Affairs
    {
        "name": "Foreign Affairs",
        "url": "https://www.foreignaffairs.com/rss.xml",
        "category": "geopolitics",
        "weight": 1.5,
    },
    {
        "name": "Foreign Policy",
        "url": "https://foreignpolicy.com/feed/",
        "category": "geopolitics",
        "weight": 1.2,
    },
    {
        "name": "BBC World",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "geopolitics",
        "weight": 1.0,
    },
    {
        "name": "Reuters World",
        "url": "https://feeds.reuters.com/Reuters/worldNews",
        "category": "geopolitics",
        "weight": 1.0,
    },
    # India
    {
        "name": "The Wire",
        "url": "https://thewire.in/rss",
        "category": "india",
        "weight": 1.3,
    },
    {
        "name": "The Hindu",
        "url": "https://www.thehindu.com/feeder/default.rss",
        "category": "india",
        "weight": 1.2,
    },
    {
        "name": "Mint",
        "url": "https://www.livemint.com/rss/news.xml",
        "category": "india",
        "weight": 1.1,
    },
    {
        "name": "Scroll.in",
        "url": "https://scroll.in/feed",
        "category": "india",
        "weight": 1.0,
    },
]

# ── NewsAPI keyword queries ────────────────────────────────────────────────────
NEWSAPI_QUERIES = [
    {"q": "artificial intelligence policy regulation", "language": "en", "pageSize": 10},
    {"q": "India economy RBI budget", "language": "en", "pageSize": 10},
    {"q": "geopolitics China India US", "language": "en", "pageSize": 10},
    {"q": "startup funding series India", "language": "en", "pageSize": 5},
]

# ── Reddit sources ────────────────────────────────────────────────────────────
REDDIT_SOURCES = [
    {
        "subreddit": "MachineLearning",
        "sort": "hot",
        "limit": 10,
        "min_score": 100,
        "category": "tech",
    },
    {
        "subreddit": "artificial",
        "sort": "hot",
        "limit": 10,
        "min_score": 50,
        "category": "tech",
    },
    {
        "subreddit": "india",
        "sort": "hot",
        "limit": 10,
        "min_score": 200,
        "category": "india",
    },
    {
        "subreddit": "IndiaInvestments",
        "sort": "hot",
        "limit": 8,
        "min_score": 100,
        "category": "india",
    },
]

# ── Hacker News ───────────────────────────────────────────────────────────────
HN_CONFIG = {
    "url": "https://hn.algolia.com/api/v1/search",
    "params": {
        "tags": "story",
        "numericFilters": "points>100,num_comments>20",
        "hitsPerPage": 15,
    },
    "category": "tech",
}

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = "data"
INTEREST_PROFILE_PATH = "data/interest-profile.md"
FEEDBACK_LOG_PATH = "data/feedback_log.jsonl"
WEEKLY_SUMMARY_PATH = "data/weekly_summary.json"
TEMPLATE_PATH = "templates/digest.html.jinja"
