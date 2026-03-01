"""Morning Digest — main orchestrator.

Runs the full digest pipeline:
1. Parse feedback from previous run
2. Curate articles via Claude + web_search
3. Process emails for importance
4. Generate PDFs
5. Upload to Google Drive
6. Store run record in ragtime
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from agents import curator, email_processor, feedback_parser
from generators import article_pdf, email_pdf
from integrations.google_drive import GoogleDriveClient
from integrations.ragtime import RagtimeClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/digest.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== Morning Digest run: {today} ===")

    config = load_config()

    # Initialize clients
    drive = GoogleDriveClient(credentials_file="credentials/gmail_primary.json")
    drive.authenticate()

    ragtime = RagtimeClient(
        project_path=config["ragtime"]["project_path"],
        namespace=config["ragtime"]["namespace"],
    )

    # Ensure Drive folder structure exists
    folder_ids = drive.ensure_folder_structure(config)
    inbox_folder_id = folder_ids["inbox"]

    # 1. Parse feedback from previous run
    logger.info("Step 1: Processing feedback from previous run")
    feedbacks = feedback_parser.process_returned_forms(config, drive, ragtime)
    logger.info(f"Processed {len(feedbacks)} feedback items")

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
            path = article_pdf.generate(article, output_dir=output_dir)
            article_pdfs.append(path)
        except Exception as e:
            logger.error(f"Failed to generate PDF for '{article.title}': {e}")

    email_pdfs = []
    for email_item in emails:
        try:
            path = email_pdf.generate(email_item, output_dir=output_dir)
            email_pdfs.append(path)
        except Exception as e:
            logger.error(f"Failed to generate PDF for '{email_item.subject}': {e}")

    # 5. Upload to Drive
    logger.info("Step 5: Uploading to Google Drive")
    for pdf_path in article_pdfs + email_pdfs:
        try:
            drive.upload_pdf(pdf_path, inbox_folder_id)
        except Exception as e:
            logger.error(f"Failed to upload {pdf_path}: {e}")

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
        f"=== Digest complete: {len(article_pdfs)} articles, {len(email_pdfs)} emails uploaded ==="
    )


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    run()
