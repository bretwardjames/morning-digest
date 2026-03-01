"""Tests for the content curator agent."""

from unittest.mock import MagicMock, patch

from agents.curator import _fit_reading_window, _extract_json_from_response
from models.article import Article


def _make_article(title: str, minutes: float) -> Article:
    return Article(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        topic_tag="test",
        word_count=int(minutes * 238),
        estimated_minutes=minutes,
        reason="test",
        source_domain="example.com",
    )


class TestFitReadingWindow:
    def test_selects_articles_within_window(self):
        articles = [
            _make_article("A", 10),
            _make_article("B", 10),
            _make_article("C", 10),
            _make_article("D", 10),
        ]
        result = _fit_reading_window(articles, target=35, tolerance=5)
        total = sum(a.estimated_minutes for a in result)
        assert total <= 40
        assert len(result) >= 3

    def test_empty_input(self):
        assert _fit_reading_window([], target=35, tolerance=5) == []

    def test_single_long_article(self):
        articles = [_make_article("Long", 50)]
        result = _fit_reading_window(articles, target=35, tolerance=5)
        assert len(result) == 0

    def test_respects_tolerance(self):
        articles = [_make_article("A", 20), _make_article("B", 20)]
        result = _fit_reading_window(articles, target=35, tolerance=5)
        assert len(result) == 2  # 40 <= 35 + 5


class TestExtractJson:
    def test_extracts_plain_json(self):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(type="text", text='[{"title": "Test", "url": "https://example.com"}]')
        ]
        result = _extract_json_from_response(mock_response)
        assert result is not None
        assert result[0]["title"] == "Test"

    def test_extracts_fenced_json(self):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(type="text", text='```json\n[{"title": "Test"}]\n```')
        ]
        result = _extract_json_from_response(mock_response)
        assert result is not None

    def test_skips_non_text_blocks(self):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(type="tool_use", text="not json"),
            MagicMock(type="text", text='[{"title": "Test"}]'),
        ]
        result = _extract_json_from_response(mock_response)
        assert result is not None

    def test_returns_none_for_invalid_json(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="not json at all")]
        result = _extract_json_from_response(mock_response)
        assert result is None
