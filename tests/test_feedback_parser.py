"""Tests for the feedback parser and sender feedback."""

from models.feedback import Feedback
from models.sender_feedback import SenderFeedback


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


class TestSenderFeedback:
    def test_ragtime_memory_includes_identity(self):
        sf = SenderFeedback(
            source_filename="2026-03-01_email_gmail_primary_q2-budget.pdf",
            sender_name="Sarah Johnson",
            sender_email="sarah@company.com",
            who_is_this="Business partner, co-owner",
            importance="always",
            context="Anything about payroll or clients is top priority",
        )
        memory = sf.to_ragtime_memory()
        assert "Sarah Johnson" in memory
        assert "sarah@company.com" in memory
        assert "Business partner" in memory
        assert "always" in memory
        assert "payroll" in memory

    def test_minimal_sender_feedback(self):
        sf = SenderFeedback(
            source_filename="test.pdf",
            sender_email="news@techcrunch.com",
            importance="never",
        )
        memory = sf.to_ragtime_memory()
        assert "news@techcrunch.com" in memory
        assert "never" in memory

    def test_worth_surfacing_recorded(self):
        sf = SenderFeedback(
            source_filename="test.pdf",
            sender_email="jane@example.com",
            was_email_worth_surfacing="no",
            importance="rarely",
        )
        memory = sf.to_ragtime_memory()
        assert "no" in memory
