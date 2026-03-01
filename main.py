"""Morning Digest — main orchestrator.

Runs the full digest pipeline:
1. Process QR code feedback submissions from previous run
2. Curate articles via Claude + web_search
3. Process emails for importance
4. Generate PDFs with feedback QR codes
5. Deliver to reMarkable (primary) and/or Google Drive (secondary)
6. Store run record in ragtime
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from agents import curator, email_processor
from generators import article_pdf, email_pdf
from integrations.ragtime import RagtimeClient
from models.sender_feedback import SenderFeedback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/digest.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

FEEDBACK_SUBMISSIONS_DIR = Path("data/feedback/submissions")


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== Morning Digest run: {today} ===")

    config = load_config()
    feedback_base_url = config.get("feedback", {}).get("base_url", "")

    ragtime = RagtimeClient(
        project_path=config["ragtime"]["project_path"],
        namespace=config["ragtime"]["namespace"],
    )

    # 1. Process QR code feedback from previous run
    logger.info("Step 1: Processing feedback submissions")
    feedback_count = _process_feedback_submissions(ragtime)
    logger.info(f"Processed {feedback_count} feedback submissions")

    # 2. Curate articles
    logger.info("Step 2: Curating articles")
    articles = curator.find_articles(config, ragtime)
    logger.info(f"Selected {len(articles)} articles")

    # 3. Process emails
    logger.info("Step 3: Processing emails")
    emails = email_processor.get_important_emails(config, ragtime)
    logger.info(f"Found {len(emails)} important emails")

    # 4. Generate PDFs
    logger.info("Step 4: Generating PDFs")
    output_dir = f"/tmp/digest/{today}"

    article_pdfs = []
    for article in articles:
        try:
            path = article_pdf.generate(
                article, output_dir=output_dir, feedback_base_url=feedback_base_url,
            )
            article_pdfs.append(path)
        except Exception as e:
            logger.error(f"Failed to generate PDF for '{article.title}': {e}")

    email_pdfs = []
    for email_item in emails:
        try:
            path = email_pdf.generate(
                email_item, output_dir=output_dir, feedback_base_url=feedback_base_url,
            )
            email_pdfs.append(path)
        except Exception as e:
            logger.error(f"Failed to generate PDF for '{email_item.subject}': {e}")

    all_pdfs = article_pdfs + email_pdfs

    # 5. Deliver PDFs
    logger.info("Step 5: Delivering PDFs")
    _deliver_pdfs(config, all_pdfs)

    # 6. Store run record in ragtime
    logger.info("Step 6: Storing run record")
    article_titles = [a.title for a in articles]
    email_subjects = [e.subject for e in emails]
    ragtime.remember(
        f"Run {today}: sent {len(articles)} articles, {len(emails)} emails. "
        f"Articles: {article_titles}. Emails: {email_subjects}",
        type="context",
        component="run-history",
    )

    logger.info(
        f"=== Digest complete: {len(article_pdfs)} articles, {len(email_pdfs)} emails delivered ==="
    )


def _deliver_pdfs(config: dict, pdf_paths: list[str]) -> None:
    """Deliver PDFs to configured targets (reMarkable, Google Drive, or both)."""
    delivery = config.get("delivery", {})

    # reMarkable
    rm_config = delivery.get("remarkable", {})
    if rm_config.get("enabled", False):
        from integrations.remarkable import RemarkableClient

        rm = RemarkableClient(rmapi_path=rm_config.get("rmapi_path", "rmapi"))
        folder = rm_config.get("folder", "/Morning Digest")
        rm.ensure_folder(folder)

        for pdf_path in pdf_paths:
            try:
                rm.upload_pdf(pdf_path, folder)
            except Exception as e:
                logger.error(f"reMarkable upload failed for {pdf_path}: {e}")

    # Google Drive (secondary/optional)
    drive_config = delivery.get("drive", {})
    if drive_config.get("enabled", False):
        from integrations.google_drive import GoogleDriveClient

        drive = GoogleDriveClient(credentials_file="credentials/gmail_primary.json")
        drive.authenticate()
        folder_ids = drive.ensure_folder_structure(config)

        for pdf_path in pdf_paths:
            try:
                drive.upload_pdf(pdf_path, folder_ids["inbox"])
            except Exception as e:
                logger.error(f"Drive upload failed for {pdf_path}: {e}")


def _process_feedback_submissions(ragtime: RagtimeClient) -> int:
    """Process QR code feedback submissions saved by the Flask app."""
    if not FEEDBACK_SUBMISSIONS_DIR.exists():
        return 0

    count = 0
    for submission_file in FEEDBACK_SUBMISSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(submission_file.read_text())
            feedback_type = data.get("type", "")

            if feedback_type == "article":
                _process_article_feedback(data, ragtime)
            elif feedback_type == "sender":
                _process_sender_feedback(data, ragtime)
            elif feedback_type == "email":
                _process_email_feedback(data, ragtime)

            # Move to processed
            processed_dir = FEEDBACK_SUBMISSIONS_DIR.parent / "processed"
            processed_dir.mkdir(exist_ok=True)
            submission_file.rename(processed_dir / submission_file.name)
            count += 1
        except Exception as e:
            logger.error(f"Error processing feedback {submission_file.name}: {e}")

    return count


def _process_article_feedback(data: dict, ragtime: RagtimeClient) -> None:
    """Store article feedback in ragtime."""
    rating = data.get("rating", 0)
    want_more = data.get("want_more", "neutral")
    title = data.get("title", "unknown")
    topic = data.get("topic_tag", "")
    domain = data.get("source_domain", "")

    signal = "more" if (rating >= 7 or want_more == "more") else \
             "less" if (rating <= 4 or want_more == "less") else "neutral"

    memory = f"Article feedback: '{title}' from {domain}. "
    memory += f"Rating: {rating}/10. Signal: {signal} of [{topic}]."

    if data.get("liked"):
        memory += f' Liked: "{data["liked"]}".'
    if data.get("disliked"):
        memory += f' Disliked: "{data["disliked"]}".'

    ragtime.remember(memory, type="preference", component="articles")


def _process_sender_feedback(data: dict, ragtime: RagtimeClient) -> None:
    """Store sender classification in ragtime."""
    sf = SenderFeedback(
        source_filename="qr_submission",
        sender_name=data.get("sender_name", ""),
        sender_email=data.get("sender_email", ""),
        who_is_this=data.get("who_is_this", ""),
        importance=data.get("importance", "unknown"),
        context=data.get("context", ""),
        was_email_worth_surfacing=data.get("worth_surfacing", ""),
    )
    ragtime.remember(sf.to_ragtime_memory(), type="context", component="contacts")

    if sf.importance == "never":
        ragtime.remember(
            f"SUPPRESS emails from {sf.sender_name} <{sf.sender_email}>. "
            f"User marked as never surface.",
            type="preference",
            component="contacts",
        )


def _process_email_feedback(data: dict, ragtime: RagtimeClient) -> None:
    """Store email feedback in ragtime."""
    sender = data.get("sender_name", "")
    email_addr = data.get("sender_email", "")
    subject = data.get("subject", "")
    worth = data.get("worth_surfacing", "")
    notes = data.get("notes", "")

    memory = f"Email feedback: '{subject}' from {sender} <{email_addr}>. "
    memory += f"Worth surfacing: {worth}."
    if notes:
        memory += f' Notes: "{notes}".'

    ragtime.remember(memory, type="context", component="contacts")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    run()
