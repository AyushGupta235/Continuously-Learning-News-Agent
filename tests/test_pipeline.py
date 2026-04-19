"""
Unit tests for pipeline/ingest, dedup, and filter (with mocked xAI).
Run with: pytest tests/test_pipeline.py -v
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_article(
    url="https://example.com/article-1",
    title="AI policy gets serious",
    description="A detailed look at AI regulation.",
    source="MIT Technology Review",
    category="tech",
    weight=1.3,
    full_text="Full text of the article about AI policy.",
) -> dict:
    from pipeline.dedup import _article_id, _normalise_url
    return {
        "id": _article_id(url),
        "title": title,
        "url": url,
        "description": description,
        "full_text": full_text,
        "source": source,
        "category": category,
        "published": datetime.now(timezone.utc).isoformat(),
        "source_weight": weight,
    }


# ── Dedup tests ───────────────────────────────────────────────────────────────

class TestDedup:
    def test_exact_url_dedup(self):
        from pipeline.dedup import dedup

        a1 = _make_article(url="https://example.com/story?utm_source=twitter")
        a2 = _make_article(url="https://example.com/story")  # same after normalisation
        result = dedup([a1, a2])
        assert len(result) == 1

    def test_title_similarity_dedup(self):
        from pipeline.dedup import dedup

        a1 = _make_article(
            url="https://source-a.com/article",
            title="RBI raises interest rates by 50 basis points",
        )
        a2 = _make_article(
            url="https://source-b.com/article",
            title="RBI raises interest rates 50 basis points",  # minor variation
        )
        result = dedup([a1, a2])
        assert len(result) == 1

    def test_different_stories_not_deduped(self):
        from pipeline.dedup import dedup

        a1 = _make_article(url="https://example.com/a", title="India GDP grows 7%")
        a2 = _make_article(url="https://example.com/b", title="TSMC expands to Europe")
        result = dedup([a1, a2])
        assert len(result) == 2

    def test_keeps_longer_full_text(self):
        from pipeline.dedup import dedup

        a1 = _make_article(url="https://example.com/story?utm_source=x", full_text="short")
        a2 = _make_article(url="https://example.com/story", full_text="much longer full text here that beats the short one")
        result = dedup([a1, a2])
        assert result[0]["full_text"] == a2["full_text"]

    def test_utm_params_stripped(self):
        from pipeline.dedup import _normalise_url
        raw = "https://Example.com/path/?utm_source=feed&utm_medium=rss"
        assert "utm" not in _normalise_url(raw)
        assert "example.com" in _normalise_url(raw)

    def test_www_stripped(self):
        from pipeline.dedup import _normalise_url
        assert _normalise_url("https://www.example.com/") == _normalise_url("https://example.com/")

    def test_empty_input(self):
        from pipeline.dedup import dedup
        assert dedup([]) == []


# ── Ingest shape tests ────────────────────────────────────────────────────────

class TestIngestShapes:
    """Test that ingest helper functions produce correct shapes."""

    def test_article_id_is_deterministic(self):
        from pipeline.dedup import _article_id
        assert _article_id("https://example.com") == _article_id("https://example.com")

    def test_article_id_length(self):
        from pipeline.dedup import _article_id
        assert len(_article_id("https://example.com")) == 16

    def test_article_id_different_urls(self):
        from pipeline.dedup import _article_id
        assert _article_id("https://a.com") != _article_id("https://b.com")


# ── Filter tests (mocked xAI) ────────────────────────────────────────────────

class TestFilter:
    def _make_xai_response(self, scores: list[dict]) -> MagicMock:
        """Build a mock xAI response containing a JSON score array."""
        msg = MagicMock()
        msg.content = json.dumps(scores)
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    @patch("pipeline.filter.OpenAI")
    def test_score_threshold_filter(self, mock_openai_cls):
        from pipeline.filter import score_articles

        articles = [
            _make_article(url=f"https://example.com/{i}", title=f"Story {i}")
            for i in range(3)
        ]
        ids = [a["id"] for a in articles]

        scores = [
            {"id": ids[0], "score": 8, "reason": "highly relevant"},
            {"id": ids[1], "score": 4, "reason": "not relevant"},
            {"id": ids[2], "score": 7, "reason": "relevant"},
        ]
        mock_openai_cls.return_value.chat.completions.create.return_value = (
            self._make_xai_response(scores)
        )

        result = score_articles(articles)
        # Only articles with score >= 6 should survive
        assert len(result) == 2
        assert all(a["relevance_score"] >= 6 for a in result)

    @patch("pipeline.filter.OpenAI")
    def test_results_sorted_by_score(self, mock_openai_cls):
        from pipeline.filter import score_articles

        articles = [
            _make_article(url=f"https://example.com/{i}", title=f"Story {i}")
            for i in range(2)
        ]
        ids = [a["id"] for a in articles]

        scores = [
            {"id": ids[0], "score": 7, "reason": "good"},
            {"id": ids[1], "score": 9, "reason": "excellent"},
        ]
        mock_openai_cls.return_value.chat.completions.create.return_value = (
            self._make_xai_response(scores)
        )

        result = score_articles(articles)
        assert result[0]["relevance_score"] == 9

    @patch("pipeline.filter.OpenAI")
    def test_xai_failure_graceful(self, mock_openai_cls):
        from pipeline.filter import score_articles

        mock_openai_cls.return_value.chat.completions.create.side_effect = Exception("timeout")
        articles = [_make_article()]
        result = score_articles(articles)
        assert result == []

    @patch("pipeline.filter.OpenAI")
    def test_attaches_score_fields(self, mock_openai_cls):
        from pipeline.filter import score_articles

        article = _make_article()
        scores = [{"id": article["id"], "score": 8, "reason": "great"}]
        mock_openai_cls.return_value.chat.completions.create.return_value = (
            self._make_xai_response(scores)
        )

        result = score_articles([article])
        assert "relevance_score" in result[0]
        assert "score_reason" in result[0]
        assert result[0]["score_reason"] == "great"


# ── Cluster tests ─────────────────────────────────────────────────────────────

class TestCluster:
    def test_similar_titles_grouped(self):
        from pipeline.cluster import cluster_stories

        a1 = {**_make_article(url="https://a.com/x", title="India RBI hikes rates by 50bp"), "relevance_score": 8, "summary": "RBI raised."}
        a2 = {**_make_article(url="https://b.com/x", title="India RBI hikes rates 50 basis points"), "relevance_score": 7, "summary": "RBI decision."}
        stories = cluster_stories([a1, a2])
        assert len(stories) == 1
        assert stories[0]["also_covered"]  # secondary source noted

    def test_different_stories_not_grouped(self):
        from pipeline.cluster import cluster_stories

        a1 = {**_make_article(url="https://a.com/x", title="TSMC opens factory in Japan"), "relevance_score": 8, "summary": "Chip news."}
        a2 = {**_make_article(url="https://b.com/x", title="RBI cuts repo rate"), "relevance_score": 7, "summary": "Rate cut."}
        stories = cluster_stories([a1, a2])
        assert len(stories) == 2

    def test_primary_is_highest_score(self):
        from pipeline.cluster import cluster_stories

        a1 = {**_make_article(url="https://a.com/x", title="AI policy bill passes Senate"), "relevance_score": 6, "summary": "Senate passed."}
        a2 = {**_make_article(url="https://b.com/x", title="AI policy bill passes US Senate"), "relevance_score": 9, "summary": "Major AI vote."}
        stories = cluster_stories([a1, a2])
        assert stories[0]["relevance_score"] == 9
