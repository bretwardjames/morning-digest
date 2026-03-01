"""Email PDF generator — renders email as readable PDF with blank notes page."""

import logging
from pathlib import Path

import html2text
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

from models.email_item import EmailItem

logger = logging.getLogger(__name__)

PAGE_MARGIN = 0.75 * inch


def generate(email: EmailItem, output_dir: str = "/tmp/digest") -> str:
    """Generate a PDF for an email.

    For new senders: appends a sender classification form + notes page.
    For known senders: appends just a blank notes page.

    Returns the path to the generated PDF file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    pdf_path = str(output_path / email.filename)

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

    # Email header block
    story.append(Paragraph(email.subject, styles["Subject"]))
    story.append(Spacer(1, 8))

    header_lines = [
        f"<b>From:</b> {email.sender_name} &lt;{email.sender_email}&gt;",
        f"<b>Date:</b> {email.received_date.strftime('%B %d, %Y at %I:%M %p')}",
        f"<b>To:</b> {', '.join(email.recipients)}",
    ]
    if email.importance_reason:
        header_lines.append(f"<b>Why important:</b> {email.importance_reason}")
    if email.suggested_action:
        header_lines.append(f"<b>Suggested action:</b> {email.suggested_action}")

    for line in header_lines:
        story.append(Paragraph(line, styles["Header"]))
    story.append(Spacer(1, 20))

    # Email body
    body_text = _get_readable_body(email)
    for paragraph in body_text.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            story.append(Paragraph(paragraph, styles["Body"]))
            story.append(Spacer(1, 10))

    # Sender classification form for new senders, then notes page
    if email.is_new_sender:
        story.append(PageBreak())
        story.extend(_build_sender_form(styles, email))

    # Notes page
    story.append(PageBreak())
    story.append(Paragraph("Notes", styles["NotesHeader"]))
    story.append(Spacer(1, 12))

    for _ in range(25):
        story.append(Paragraph("_" * 65, styles["Lines"]))

    # Footer with thread metadata
    story.append(Spacer(1, 20))
    footer = f"Account: {email.account_id} | Thread: {email.thread_id} | {email.received_date.strftime('%Y-%m-%d')}"
    story.append(Paragraph(footer, styles["Footer"]))

    doc.build(story)
    logger.info(f"Generated email PDF: {pdf_path}")
    return pdf_path


def _get_readable_body(email: EmailItem) -> str:
    """Extract readable text from email body, preferring plain text."""
    if email.body_text:
        return email.body_text

    if email.body_html:
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        return converter.handle(email.body_html)

    return email.snippet


def _build_sender_form(styles: dict, email: EmailItem) -> list:
    """Build the sender onboarding form for new/unknown senders.

    This form appears between the email body and the notes page, only for
    emails from senders not yet in ragtime. The filled form feeds back into
    ragtime as contact context on the next run.
    """
    elements = []

    elements.append(Paragraph("New Sender — Help me learn", styles["FormHeader"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"I don't have context for <b>{email.sender_name}</b> "
        f"&lt;{email.sender_email}&gt; yet.",
        styles["FormLabel"],
    ))
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("Who is this person / what is this sender?", styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(
        "How important are their emails generally?",
        styles["FormLabel"],
    ))
    elements.append(Paragraph(
        "( ) Always read  ( ) Sometimes  ( ) Rarely  ( ) Never surface",
        styles["FormLabel"],
    ))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Any specific context?", styles["FormLabel"]))
    elements.append(Paragraph(
        "(e.g. \"my business partner — anything about clients is urgent\")",
        styles["FormHint"],
    ))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Paragraph("_" * 60, styles["FormLabel"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Was this email worth surfacing?", styles["FormLabel"]))
    elements.append(Paragraph("( ) Yes  ( ) No", styles["FormLabel"]))
    elements.append(Spacer(1, 16))

    # Hidden metadata for the feedback parser
    elements.append(Paragraph(
        f"<font size='7' color='#aaaaaa'>"
        f"sender_email:{email.sender_email} | sender_name:{email.sender_name} | "
        f"account:{email.account_id}</font>",
        styles["Footer"],
    ))

    return elements


def _build_styles() -> dict:
    base = getSampleStyleSheet()

    return {
        "Subject": ParagraphStyle(
            "EmailSubject",
            parent=base["Title"],
            fontSize=22,
            leading=28,
        ),
        "Header": ParagraphStyle(
            "EmailHeader",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            textColor=HexColor("#444444"),
        ),
        "Body": ParagraphStyle(
            "EmailBody",
            parent=base["Normal"],
            fontSize=15,
            leading=22,
        ),
        "NotesHeader": ParagraphStyle(
            "NotesHeader",
            parent=base["Heading2"],
            fontSize=18,
        ),
        "Lines": ParagraphStyle(
            "Lines",
            parent=base["Normal"],
            fontSize=12,
            leading=24,
            textColor=HexColor("#cccccc"),
        ),
        "Footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontSize=9,
            textColor=HexColor("#999999"),
        ),
        "FormHeader": ParagraphStyle(
            "FormHeader",
            parent=base["Heading2"],
            fontSize=18,
            spaceAfter=8,
        ),
        "FormLabel": ParagraphStyle(
            "FormLabel",
            parent=base["Normal"],
            fontSize=14,
            leading=20,
            spaceBefore=4,
        ),
        "FormHint": ParagraphStyle(
            "FormHint",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=HexColor("#888888"),
        ),
    }
