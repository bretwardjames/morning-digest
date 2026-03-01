"""Email PDF generator — renders email as readable PDF with QR feedback codes."""

import logging
from pathlib import Path

import html2text
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from generators.qr import generate_sender_qr, generate_email_qr, QR_SIZE_POINTS
from models.email_item import EmailItem

logger = logging.getLogger(__name__)

PAGE_MARGIN = 0.75 * inch


def generate(email: EmailItem, output_dir: str = "/tmp/digest", feedback_base_url: str = "") -> str:
    """Generate a PDF for an email.

    For new senders: includes a 'classify this sender' QR code.
    For known senders: includes a 'was this worth it?' QR code.
    Both get a blank notes page.

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

    # QR feedback code
    if feedback_base_url:
        story.append(Spacer(1, 24))
        if email.is_new_sender:
            story.extend(_build_sender_qr_section(styles, email, feedback_base_url))
        else:
            story.extend(_build_email_qr_section(styles, email, feedback_base_url))

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


def _build_sender_qr_section(styles: dict, email: EmailItem, base_url: str) -> list:
    """Build the new-sender QR code section."""
    qr_image, feedback_id = generate_sender_qr(
        sender_name=email.sender_name,
        sender_email=email.sender_email,
        account_id=email.account_id,
        subject=email.subject,
        base_url=base_url,
    )

    elements = []
    elements.append(Paragraph("&mdash;" * 20, styles["QRLabel"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"<b>New sender:</b> {email.sender_name} &lt;{email.sender_email}&gt;",
        styles["QRLabel"],
    ))
    elements.append(Paragraph("Scan to classify this sender", styles["QRLabel"]))
    elements.append(Spacer(1, 8))

    qr_img = Image(qr_image, width=QR_SIZE_POINTS, height=QR_SIZE_POINTS)
    qr_img.hAlign = "CENTER"
    elements.append(qr_img)

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<font size='8' color='#aaaaaa'>{feedback_id}</font>", styles["QRLabel"]))

    return elements


def _build_email_qr_section(styles: dict, email: EmailItem, base_url: str) -> list:
    """Build the known-sender email feedback QR code section."""
    qr_image, feedback_id = generate_email_qr(
        sender_name=email.sender_name,
        sender_email=email.sender_email,
        subject=email.subject,
        account_id=email.account_id,
        base_url=base_url,
    )

    elements = []
    elements.append(Paragraph("&mdash;" * 20, styles["QRLabel"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("Scan to give feedback on this email", styles["QRLabel"]))
    elements.append(Spacer(1, 8))

    qr_img = Image(qr_image, width=QR_SIZE_POINTS, height=QR_SIZE_POINTS)
    qr_img.hAlign = "CENTER"
    elements.append(qr_img)

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<font size='8' color='#aaaaaa'>{feedback_id}</font>", styles["QRLabel"]))

    return elements


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
        "QRLabel": ParagraphStyle(
            "QRLabel",
            parent=base["Normal"],
            fontSize=11,
            textColor=HexColor("#888888"),
            alignment=1,  # center
        ),
    }
