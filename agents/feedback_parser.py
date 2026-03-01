"""Feedback parser agent — extracts form data from returned PDFs and stores in ragtime."""

import logging
from pathlib import Path

import anthropic
from pypdf import PdfReader

from integrations.google_drive import GoogleDriveClient
from integrations.ragtime import RagtimeClient
from models.feedback import Feedback
from models.sender_feedback import SenderFeedback

logger = logging.getLogger(__name__)

# AcroForm field name mappings (must match article_pdf.py form generation)
FIELD_MAP = {
    "was_read": "was_read",
    "rating": "rating",
    "liked": "liked_text",
    "disliked": "disliked_text",
    "want_more": "want_more",
    "tag_ai": "AI/tech",
    "tag_business": "Business",
    "tag_politics": "Politics",
    "tag_health": "Health",
    "tag_other": "Other",
    "other_text": "other_tag",
}

# Sender onboarding form fields (must match email_pdf.py form generation)
SENDER_FIELD_MAP = {
    "who_is_this": "who_is_this",
    "sender_importance": "importance",
    "sender_context": "context",
    "worth_surfacing": "was_email_worth_surfacing",
}


def process_returned_forms(config: dict, drive: GoogleDriveClient, ragtime: RagtimeClient) -> list[Feedback]:
    """Check Drive feedback folder for modified PDFs, parse forms, store in ragtime."""
    feedback_folder_id = config["drive"].get("feedback_folder_id", "")
    archive_folder_id = config["drive"].get("archive_folder_id", "")

    if not feedback_folder_id:
        logger.warning("No feedback folder configured")
        return []

    # Also check liked/disliked folders for simple move-based feedback
    liked_folder_id = config["drive"].get("liked_folder_id", "")
    disliked_folder_id = config["drive"].get("disliked_folder_id", "")

    feedbacks = []

    # Process form-based feedback from feedback folder
    files = drive.list_files(feedback_folder_id)
    for file_info in files:
        try:
            local_path = f"/tmp/digest_feedback_{file_info['id']}.pdf"
            drive.download_file(file_info["id"], local_path)

            is_email_pdf = "_email_" in file_info["name"]

            if is_email_pdf:
                # Try sender onboarding form first, fall back to generic
                sender_fb = _parse_sender_form(local_path, file_info["name"])
                if sender_fb:
                    _store_sender_feedback(sender_fb, ragtime)
                    logger.info(f"Stored sender context for {sender_fb.sender_email}")
            else:
                feedback = _parse_pdf_form(local_path, file_info["name"])
                if feedback:
                    _store_feedback(feedback, ragtime)
                    feedbacks.append(feedback)

            if archive_folder_id:
                drive.move_file(file_info["id"], archive_folder_id)

            Path(local_path).unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Error processing feedback for {file_info['name']}: {e}")

    # Process liked folder (simple positive signal)
    if liked_folder_id:
        for file_info in drive.list_files(liked_folder_id):
            feedback = Feedback(
                source_filename=file_info["name"],
                want_more="more",
                rating=8,
            )
            _store_feedback(feedback, ragtime)
            feedbacks.append(feedback)
            if archive_folder_id:
                drive.move_file(file_info["id"], archive_folder_id)

    # Process disliked folder (simple negative signal)
    if disliked_folder_id:
        for file_info in drive.list_files(disliked_folder_id):
            feedback = Feedback(
                source_filename=file_info["name"],
                want_more="less",
                rating=3,
            )
            _store_feedback(feedback, ragtime)
            feedbacks.append(feedback)
            if archive_folder_id:
                drive.move_file(file_info["id"], archive_folder_id)

    logger.info(f"Processed {len(feedbacks)} feedback items")
    return feedbacks


def _parse_pdf_form(pdf_path: str, filename: str) -> Feedback | None:
    """Extract AcroForm field values from a PDF."""
    reader = PdfReader(pdf_path)
    fields = reader.get_form_text_fields() or {}
    checkboxes = reader.get_fields() or {}

    if not fields and not checkboxes:
        return None

    # Map form fields to Feedback
    topic_tags = []
    for field_key, tag_name in FIELD_MAP.items():
        if field_key.startswith("tag_") and field_key in checkboxes:
            field_val = checkboxes[field_key]
            if isinstance(field_val, dict):
                val = field_val.get("/V", "")
            else:
                val = str(field_val)
            if val and val != "/Off":
                topic_tags.append(tag_name)

    # Parse rating from radio buttons
    rating = None
    raw_rating = checkboxes.get("rating", {})
    if isinstance(raw_rating, dict):
        val = raw_rating.get("/V", "")
        if val:
            try:
                rating = int(str(val).strip("/"))
            except ValueError:
                pass

    # Parse want_more radio
    want_more = "neutral"
    raw_want = checkboxes.get("want_more", {})
    if isinstance(raw_want, dict):
        val = str(raw_want.get("/V", ""))
        if "more" in val.lower():
            want_more = "more"
        elif "less" in val.lower():
            want_more = "less"

    return Feedback(
        source_filename=filename,
        was_read=bool(checkboxes.get("was_read", {}).get("/V", "")),
        rating=rating,
        liked_text=fields.get("liked", ""),
        disliked_text=fields.get("disliked", ""),
        want_more=want_more,
        topic_tags=topic_tags,
        other_tag=fields.get("other_text", ""),
        raw_fields={**fields, **{k: str(v) for k, v in checkboxes.items()}},
    )


def _store_feedback(feedback: Feedback, ragtime: RagtimeClient) -> None:
    """Store feedback signal in ragtime memory."""
    memory = feedback.to_ragtime_memory()

    if feedback.is_positive:
        ragtime.remember(memory, type="preference", component="articles")
    elif feedback.is_negative:
        ragtime.remember(memory, type="preference", component="articles")
    else:
        ragtime.remember(memory, type="context", component="articles")

    # If freeform text exists, extract keywords via Claude
    if feedback.liked_text or feedback.disliked_text:
        _extract_and_store_topic_signals(feedback, ragtime)


def _parse_sender_form(pdf_path: str, filename: str) -> SenderFeedback | None:
    """Extract sender onboarding form fields from an email PDF."""
    reader = PdfReader(pdf_path)
    fields = reader.get_form_text_fields() or {}
    all_fields = reader.get_fields() or {}

    # Check if this PDF has sender form fields
    has_sender_fields = any(k in all_fields for k in SENDER_FIELD_MAP)
    if not has_sender_fields:
        return None

    # Extract sender metadata from the hidden footer line
    sender_email = ""
    sender_name = ""
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            if "sender_email:" in line:
                for part in line.split("|"):
                    part = part.strip()
                    if part.startswith("sender_email:"):
                        sender_email = part.split(":", 1)[1].strip()
                    elif part.startswith("sender_name:"):
                        sender_name = part.split(":", 1)[1].strip()

    # Parse importance radio
    importance = "unknown"
    raw_imp = all_fields.get("sender_importance", {})
    if isinstance(raw_imp, dict):
        val = str(raw_imp.get("/V", "")).lower()
        for level in ("always", "sometimes", "rarely", "never"):
            if level in val:
                importance = level
                break

    # Parse worth surfacing radio
    worth = ""
    raw_worth = all_fields.get("worth_surfacing", {})
    if isinstance(raw_worth, dict):
        val = str(raw_worth.get("/V", "")).lower()
        if "yes" in val:
            worth = "yes"
        elif "no" in val:
            worth = "no"

    return SenderFeedback(
        source_filename=filename,
        sender_name=sender_name,
        sender_email=sender_email,
        who_is_this=fields.get("who_is_this", ""),
        importance=importance,
        context=fields.get("sender_context", ""),
        was_email_worth_surfacing=worth,
        raw_fields={**fields, **{k: str(v) for k, v in all_fields.items()}},
    )


def _store_sender_feedback(sender_fb: SenderFeedback, ragtime: RagtimeClient) -> None:
    """Store sender classification in ragtime as contact context."""
    memory = sender_fb.to_ragtime_memory()
    ragtime.remember(memory, type="context", component="contacts")

    # If they said "never surface", store a strong negative signal
    if sender_fb.importance == "never":
        ragtime.remember(
            f"SUPPRESS emails from {sender_fb.sender_name} <{sender_fb.sender_email}>. "
            f"User marked as never surface.",
            type="preference",
            component="contacts",
        )


def _extract_and_store_topic_signals(feedback: Feedback, ragtime: RagtimeClient) -> None:
    """Use Claude to extract topic preference keywords from freeform text."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"""Extract topic preference keywords from this article feedback.

Liked: "{feedback.liked_text}"
Disliked: "{feedback.disliked_text}"
Rating: {feedback.rating}/10

Return a single sentence summarizing the preference signal, e.g.:
"Prefers practical AI tutorials over theoretical research. Likes concrete examples."

Be concise. One sentence only.""",
        }],
    )

    for block in response.content:
        if block.type == "text":
            ragtime.remember(
                f"Topic signal from {feedback.source_filename}: {block.text.strip()}",
                type="pattern",
                component="topics",
            )
            break
