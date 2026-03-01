"""Tests for PDF generation."""

from pathlib import Path
from datetime import datetime

from models.article import Article
from models.email_item import EmailItem
from generators import article_pdf, email_pdf


def _make_article() -> Article:
    return Article(
        title="Test Article About AI",
        url="https://example.com/test-ai-article",
        topic_tag="ai_technology",
        word_count=1000,
        estimated_minutes=4.2,
        reason="Test article",
        source_domain="example.com",
        body_text="This is the first paragraph.\n\nThis is the second paragraph.\n\nFinal thoughts here.",
        author="Test Author",
    )


def _make_email() -> EmailItem:
    return EmailItem(
        message_id="msg123",
        thread_id="thread456",
        account_id="gmail_primary",
        sender_name="Jane Doe",
        sender_email="jane@example.com",
        subject="Important Business Decision",
        snippet="We need to discuss the Q2 budget...",
        received_date=datetime(2026, 3, 1, 9, 30),
        importance_score=8.5,
        importance_reason="Requires decision on budget allocation",
        suggested_action="reply",
        body_text="Hi,\n\nWe need to discuss the Q2 budget allocation.\n\nPlease review and respond by Friday.\n\nBest,\nJane",
        recipients=["user@example.com"],
    )


class TestArticlePdf:
    def test_generates_pdf_file(self, tmp_path):
        article = _make_article()
        path = article_pdf.generate(article, output_dir=str(tmp_path))
        assert Path(path).exists()
        assert path.endswith(".pdf")

    def test_filename_format(self):
        article = _make_article()
        assert "ai_technology" in article.filename
        assert article.filename.endswith(".pdf")
        assert article.filename.startswith(datetime.now().strftime("%Y-%m-%d"))


class TestEmailPdf:
    def test_generates_pdf_file(self, tmp_path):
        email = _make_email()
        path = email_pdf.generate(email, output_dir=str(tmp_path))
        assert Path(path).exists()
        assert path.endswith(".pdf")

    def test_filename_format(self):
        email = _make_email()
        assert "gmail_primary" in email.filename
        assert "email" in email.filename
