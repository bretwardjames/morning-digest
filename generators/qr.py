"""QR code generation for feedback URLs.

Generates QR code images and writes metadata files that the feedback
web app uses to render context-aware forms.
"""

import json
import uuid
from io import BytesIO
from pathlib import Path

import qrcode

FEEDBACK_META_DIR = Path(__file__).parent.parent / "data" / "feedback" / "meta"

# QR code sizing for e-ink readability (scanned from phone at ~30cm)
QR_SIZE_POINTS = 144  # 2 inches at 72 DPI


def generate_article_qr(
    title: str,
    topic_tag: str,
    source_domain: str,
    base_url: str,
) -> tuple[BytesIO, str]:
    """Generate a QR code for article feedback.

    Returns (image_reader, feedback_id) — the image_reader can be
    passed directly to reportlab's canvas.drawImage().
    """
    feedback_id = str(uuid.uuid4())[:8]
    url = f"{base_url}/article/{feedback_id}"

    _write_meta(feedback_id, {
        "type": "article",
        "title": title,
        "topic_tag": topic_tag,
        "source_domain": source_domain,
        "url": url,
    })

    return _make_qr_image(url), feedback_id


def generate_sender_qr(
    sender_name: str,
    sender_email: str,
    account_id: str,
    subject: str,
    base_url: str,
) -> tuple[BytesIO, str]:
    """Generate a QR code for new sender classification.

    Returns (image_reader, feedback_id).
    """
    feedback_id = str(uuid.uuid4())[:8]
    url = f"{base_url}/sender/{feedback_id}"

    _write_meta(feedback_id, {
        "type": "sender",
        "sender_name": sender_name,
        "sender_email": sender_email,
        "account_id": account_id,
        "subject": subject,
        "url": url,
    })

    return _make_qr_image(url), feedback_id


def generate_email_qr(
    sender_name: str,
    sender_email: str,
    subject: str,
    account_id: str,
    base_url: str,
) -> tuple[BytesIO, str]:
    """Generate a QR code for known-sender email feedback.

    Returns (image_reader, feedback_id).
    """
    feedback_id = str(uuid.uuid4())[:8]
    url = f"{base_url}/email/{feedback_id}"

    _write_meta(feedback_id, {
        "type": "email",
        "sender_name": sender_name,
        "sender_email": sender_email,
        "subject": subject,
        "account_id": account_id,
        "url": url,
    })

    return _make_qr_image(url), feedback_id


def _make_qr_image(url: str) -> BytesIO:
    """Generate a QR code and return a BytesIO PNG buffer for reportlab."""
    qr = qrcode.QRCode(
        version=None,  # auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,  # minimal border — saves space on page
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _write_meta(feedback_id: str, data: dict) -> None:
    """Write metadata JSON so the feedback web app knows what to render."""
    FEEDBACK_META_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = FEEDBACK_META_DIR / f"{feedback_id}.json"
    meta_path.write_text(json.dumps(data, indent=2))
