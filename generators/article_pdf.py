"""Article PDF generator — renders article text with appended fillable feedback form."""

import logging
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
)
from reportlab.pdfbase import pdfform
from reportlab.lib import colors

from models.article import Article

logger = logging.getLogger(__name__)

# Typography optimized for e-ink readability
BODY_FONT_SIZE = 16
BODY_LEADING = 24
TITLE_FONT_SIZE = 24
SUBTITLE_FONT_SIZE = 12
PAGE_MARGIN = 0.75 * inch


def generate(article: Article, output_dir: str = "/tmp/digest") -> str:
    """Generate a PDF for an article with an appended feedback form.

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

    # Feedback form on new page
    story.append(PageBreak())
    story.extend(_build_feedback_form(styles, article))

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
        "FormHeader": ParagraphStyle(
            "FormHeader",
            parent=base["Heading2"],
            fontSize=18,
            spaceAfter=12,
        ),
        "FormLabel": ParagraphStyle(
            "FormLabel",
            parent=base["Normal"],
            fontSize=14,
            leading=20,
            spaceBefore=8,
        ),
    }


def _build_feedback_form(styles: dict, article: Article) -> list:
    """Build the feedback form page elements.

    Note: AcroForm fields require canvas-level drawing. This builds the
    static layout; the actual form fields are added via a custom page template
    or post-processing. For the initial scaffold, we use placeholder text
    that will be replaced with actual AcroForm fields in Phase 1 validation.
    """
    elements = []
    elements.append(Paragraph("Feedback", styles["FormHeader"]))
    elements.append(Paragraph(f"Article: {article.title}", styles["FormLabel"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Did you read this article?  [ ]", styles["FormLabel"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(
        "Rating:  1 ( )  2 ( )  3 ( )  4 ( )  5 ( )  6 ( )  7 ( )  8 ( )  9 ( )  10 ( )",
        styles["FormLabel"],
    ))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("What did you like about it?", styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("What did you like less?", styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(
        "Want more like this?  ( ) Yes, more  ( ) No, less  ( ) Neutral",
        styles["FormLabel"],
    ))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(
        "Tags:  [ ] AI/tech  [ ] Business  [ ] Politics  [ ] Health  [ ] Other: ___",
        styles["FormLabel"],
    ))

    return elements
