"""Article PDF generator — renders article text with a feedback QR code."""

import logging
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image

from generators.qr import generate_article_qr, QR_SIZE_POINTS
from models.article import Article

logger = logging.getLogger(__name__)

# Typography optimized for e-ink readability
BODY_FONT_SIZE = 16
BODY_LEADING = 24
TITLE_FONT_SIZE = 24
SUBTITLE_FONT_SIZE = 12
PAGE_MARGIN = 0.75 * inch


def generate(article: Article, output_dir: str = "/tmp/digest", feedback_base_url: str = "") -> str:
    """Generate a PDF for an article with a feedback QR code at the end.

    Returns the path to the generated PDF file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    pdf_path = str(output_path / article.filename)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )

    styles = _build_styles()
    story = []

    # Header
    story.append(Paragraph(article.title, styles["Title"]))
    story.append(Spacer(1, 8))

    meta = f"{article.source_domain} &bull; ~{article.estimated_minutes:.0f} min read"
    if article.author:
        meta = f"{article.author} &bull; {meta}"
    story.append(Paragraph(meta, styles["Subtitle"]))
    story.append(Spacer(1, 24))

    # Body paragraphs
    for paragraph in article.body_text.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            story.append(Paragraph(paragraph, styles["Body"]))
            story.append(Spacer(1, 12))

    # Feedback QR code at the end of the article
    if feedback_base_url:
        story.append(Spacer(1, 24))
        story.extend(_build_feedback_section(styles, article, feedback_base_url))

    doc.build(story)
    logger.info(f"Generated article PDF: {pdf_path}")
    return pdf_path


def _build_styles() -> dict:
    """Build paragraph styles optimized for e-ink reading."""
    base = getSampleStyleSheet()

    return {
        "Title": ParagraphStyle(
            "DigestTitle",
            parent=base["Title"],
            fontSize=TITLE_FONT_SIZE,
            leading=TITLE_FONT_SIZE * 1.3,
            spaceAfter=4,
        ),
        "Subtitle": ParagraphStyle(
            "DigestSubtitle",
            parent=base["Normal"],
            fontSize=SUBTITLE_FONT_SIZE,
            textColor=HexColor("#666666"),
        ),
        "Body": ParagraphStyle(
            "DigestBody",
            parent=base["Normal"],
            fontSize=BODY_FONT_SIZE,
            leading=BODY_LEADING,
        ),
        "QRLabel": ParagraphStyle(
            "QRLabel",
            parent=base["Normal"],
            fontSize=11,
            textColor=HexColor("#888888"),
            alignment=1,  # center
        ),
    }


def _build_feedback_section(styles: dict, article: Article, base_url: str) -> list:
    """Build the feedback QR code section at the end of the article."""
    qr_image, feedback_id = generate_article_qr(
        title=article.title,
        topic_tag=article.topic_tag,
        source_domain=article.source_domain,
        base_url=base_url,
    )

    elements = []
    # Horizontal rule
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("&mdash;" * 20, styles["QRLabel"]))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("Scan to rate this article", styles["QRLabel"]))
    elements.append(Spacer(1, 8))

    # QR code as centered image
    qr_img = Image(qr_image, width=QR_SIZE_POINTS, height=QR_SIZE_POINTS)
    qr_img.hAlign = "CENTER"
    elements.append(qr_img)

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<font size='8' color='#aaaaaa'>{feedback_id}</font>", styles["QRLabel"]))

    return elements
