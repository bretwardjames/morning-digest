"""Tests for the feedback parser."""

from models.feedback import Feedback


class TestFeedback:
    def test_positive_by_rating(self):
        f = Feedback(source_filename="test.pdf", rating=8)
        assert f.is_positive
        assert not f.is_negative

    def test_positive_by_want_more(self):
        f = Feedback(source_filename="test.pdf", want_more="more")
        assert f.is_positive

    def test_negative_by_rating(self):
        f = Feedback(source_filename="test.pdf", rating=3)
        assert f.is_negative
        assert not f.is_positive

    def test_negative_by_want_less(self):
        f = Feedback(source_filename="test.pdf", want_more="less")
        assert f.is_negative

    def test_neutral(self):
        f = Feedback(source_filename="test.pdf", rating=5, want_more="neutral")
        assert not f.is_positive
        assert not f.is_negative

    def test_ragtime_memory_format(self):
        f = Feedback(
            source_filename="2026-03-01_ai_test.pdf",
            rating=9,
            liked_text="Great practical examples",
            want_more="more",
            topic_tags=["AI/tech"],
        )
        memory = f.to_ragtime_memory()
        assert "2026-03-01_ai_test.pdf" in memory
        assert "9/10" in memory
        assert "Great practical examples" in memory
        assert "more" in memory

    def test_unrated_memory_format(self):
        f = Feedback(source_filename="test.pdf")
        memory = f.to_ragtime_memory()
        assert "Unrated" in memory
