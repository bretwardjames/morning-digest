"""Morning Digest CLI — curate, deliver, and brief.

Usage:
  python digest.py --run      Cron target: curate + deliver + store manifest
  python digest.py            Briefing: what was sent, why, skipped emails, feedback
  python digest.py --review   End-of-day triage of unengaged items

The system sends everything automatically. You run `digest.py` to see
what it sent and why, give feedback, and request swaps. Your feedback
trains the system over time via ragtime.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from agents import curator, email_processor
from generators import article_pdf, email_pdf
from integrations.ragtime import RagtimeClient
from models.article import Article
from models.email_item import EmailItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/digest.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

FEEDBACK_DIR = Path("data/feedback")
META_DIR = FEEDBACK_DIR / "meta"
SUBMISSIONS_DIR = FEEDBACK_DIR / "submissions"
PROCESSED_DIR = FEEDBACK_DIR / "processed"
SKIPPED_DIR = FEEDBACK_DIR / "skipped"
REVIEWED_DIR = FEEDBACK_DIR / "reviewed"
RUNS_DIR = Path("data/runs")


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Main entry point ─────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Morning Digest CLI")
    parser.add_argument("--run", action="store_true", help="Curate + deliver (cron target)")
    parser.add_argument("--review", action="store_true", help="End-of-day triage")
    parser.add_argument("--annotations", action="store_true", help="Extract pen annotations from Remarkable")
    parser.add_argument("--date", type=str, default=None, help="Target date (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()

    Path("logs").mkdir(exist_ok=True)
    config = load_config()
    ragtime = RagtimeClient(
        project_path=config["ragtime"]["project_path"],
        namespace=config["ragtime"]["namespace"],
    )

    if args.run:
        mode_run(config, ragtime)
    elif args.annotations:
        mode_annotations(config, ragtime, target_date=args.date)
    elif args.review:
        mode_review(config, ragtime)
    else:
        mode_briefing(config, ragtime, target_date=args.date)


# ── Run mode (cron target) ───────────────────────────────────────────

def mode_run(config: dict, ragtime: RagtimeClient) -> None:
    """Curate articles, score emails, generate PDFs, deliver, store manifest."""
    today = datetime.now().strftime("%Y-%m-%d")
    feedback_base_url = config.get("feedback", {}).get("base_url", "")
    logger.info(f"=== Digest run: {today} ===")

    # Housekeeping — archive yesterday, process feedback, extract annotations
    _archive_remarkable(config, today)
    fb = _process_feedback_submissions(ragtime)
    sk = _process_skipped_items(ragtime)
    logger.info(f"Processed {fb} feedback, {sk} skipped items")

    # Extract annotations from yesterday's archived documents
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        from integrations.annotation_reviewer import review_annotations
        anns = review_annotations(config, ragtime, yesterday)
        if anns:
            logger.info(f"Extracted {len(anns)} annotations from yesterday's documents")
    except Exception as e:
        logger.warning(f"Annotation extraction failed: {e}")

    # Curate articles
    articles = curator.find_articles(config, ragtime)
    logger.info(f"Selected {len(articles)} articles")

    # Score emails — get both surfaced and skipped
    emails_surfaced, emails_skipped = email_processor.get_important_emails(config, ragtime)
    logger.info(f"Surfacing {len(emails_surfaced)} emails, {len(emails_skipped)} below threshold")

    # Generate PDFs
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
    for email_item in emails_surfaced:
        try:
            path = email_pdf.generate(
                email_item, output_dir=output_dir, feedback_base_url=feedback_base_url,
            )
            email_pdfs.append(path)
        except Exception as e:
            logger.error(f"Failed to generate PDF for '{email_item.subject}': {e}")

    # Deliver
    all_pdfs = article_pdfs + email_pdfs
    _deliver_pdfs(config, all_pdfs)

    # Store manifest for briefing
    manifest = _build_manifest(today, articles, emails_surfaced, emails_skipped,
                                article_pdfs, email_pdfs)
    _save_manifest(today, manifest)

    # Store run record in ragtime
    ragtime.remember(
        f"Run {today}: sent {len(articles)} articles, {len(emails_surfaced)} emails. "
        f"Articles: {[a.title for a in articles]}. "
        f"Emails: {[e.subject for e in emails_surfaced]}.",
        type="context", component="run-history",
    )

    logger.info(f"=== Digest complete: {len(all_pdfs)} PDFs delivered ===")


# ── Annotations mode ─────────────────────────────────────────────────

def mode_annotations(config: dict, ragtime: RagtimeClient, target_date: str | None = None) -> None:
    """Download documents from Remarkable, extract pen annotations, store signals."""
    from integrations.annotation_reviewer import review_annotations

    date = target_date or datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'═' * 60}")
    print(f"  Annotation Review — {date}")
    print(f"{'═' * 60}")
    print(f"  Downloading documents from Remarkable archive...")

    annotations = review_annotations(config, ragtime, date)

    if not annotations:
        print("\n  No annotations found.")
        print(f"{'═' * 60}\n")
        return

    circles = [a for a in annotations if a.gesture == "circle"]
    underlines = [a for a in annotations if a.gesture == "underline"]
    crossouts = [a for a in annotations if a.gesture == "crossout"]

    if circles:
        print(f"\n{'─' * 60}")
        print(f"  Circled — want more like this ({len(circles)})")
        print(f"{'─' * 60}")
        for a in circles:
            print(f"\n  Source: {a.source_title}")
            print(f"    \"{a.text}\"")

    if underlines:
        print(f"\n{'─' * 60}")
        print(f"  Underlined — remembered verbatim ({len(underlines)})")
        print(f"{'─' * 60}")
        for a in underlines:
            print(f"\n  Source: {a.source_title}")
            if a.source_url:
                print(f"    URL: {a.source_url}")
            print(f"    \"{a.text}\"")

    if crossouts:
        print(f"\n{'─' * 60}")
        print(f"  Crossed out — less of this ({len(crossouts)})")
        print(f"{'─' * 60}")
        for a in crossouts:
            print(f"\n  Source: {a.source_title}")
            print(f"    \"{a.text}\"")

    print(f"\n{'═' * 60}")
    print(f"  Stored {len(annotations)} annotation signals in ragtime.")
    print(f"{'═' * 60}\n")


# ── Briefing mode (default) ──────────────────────────────────────────

def mode_briefing(config: dict, ragtime: RagtimeClient, target_date: str | None = None) -> None:
    """Show what was sent, why, what emails were skipped, and take feedback."""
    date = target_date or datetime.now().strftime("%Y-%m-%d")
    manifest = _load_manifest(date)

    if not manifest:
        print(f"\n  No digest found for {date}. Run `python digest.py --run` first.")
        return

    print(f"\n{'═' * 60}")
    print(f"  Digest Briefing — {date}")
    print(f"{'═' * 60}")

    # Articles sent
    articles = manifest.get("articles", [])
    if articles:
        total_min = sum(a.get("estimated_minutes", 0) for a in articles)
        print(f"\n{'─' * 60}")
        print(f"  Articles sent ({len(articles)}, ~{total_min:.0f} min)")
        print(f"{'─' * 60}")
        for i, a in enumerate(articles, 1):
            print(f"\n  {i}. {a['title']}")
            print(f"     {a['source_domain']} · [{a['topic_tag']}] · ~{a['estimated_minutes']:.0f} min")
            print(f"     Why: {a['reason']}")

    # Emails sent
    emails_sent = manifest.get("emails_sent", [])
    if emails_sent:
        print(f"\n{'─' * 60}")
        print(f"  Emails sent ({len(emails_sent)})")
        print(f"{'─' * 60}")
        for i, e in enumerate(emails_sent, 1):
            sender = f"{e['sender_name']} <{e['sender_email']}>"
            new_tag = " [NEW SENDER]" if e.get("is_new_sender") else ""
            print(f"\n  {i}. {e['subject']}")
            print(f"     From: {sender}{new_tag}")
            print(f"     Score: {e['importance_score']}/10 — {e['importance_reason']}")
            if e.get("suggested_action"):
                print(f"     Suggested: {e['suggested_action']}")

    # Emails NOT sent
    emails_skipped = manifest.get("emails_skipped", [])
    if emails_skipped:
        print(f"\n{'─' * 60}")
        print(f"  Emails NOT sent ({len(emails_skipped)})")
        print(f"{'─' * 60}")
        for i, e in enumerate(emails_skipped, 1):
            sender = f"{e['sender_name']} <{e['sender_email']}>"
            print(f"\n  {i}. {e['subject']}")
            print(f"     From: {sender}")
            print(f"     Score: {e['importance_score']}/10 — {e['importance_reason']}")
            if e.get("snippet"):
                snippet = e["snippet"][:120] + "..." if len(e["snippet"]) > 120 else e["snippet"]
                print(f"     Preview: {snippet}")

    # Feedback prompt
    print(f"\n{'─' * 60}")
    print("  Feedback")
    print(f"{'─' * 60}")
    print("  Commands:")
    print("    remove <n>      Remove article #n from Remarkable")
    print("    send <n>        Send skipped email #n to Remarkable")
    print("    feedback        Give general feedback (stored in ragtime)")
    print("    done            Exit")
    print()

    _feedback_loop(config, ragtime, manifest, date)


def _feedback_loop(config: dict, ragtime: RagtimeClient, manifest: dict, date: str) -> None:
    """Interactive feedback loop after briefing."""
    feedback_base_url = config.get("feedback", {}).get("base_url", "")
    articles = manifest.get("articles", [])
    emails_skipped = manifest.get("emails_skipped", [])

    while True:
        cmd = input("  > ").strip().lower()

        if not cmd or cmd == "done":
            print("  Done.\n")
            break

        parts = cmd.split(maxsplit=1)
        action = parts[0]

        if action == "remove" and len(parts) == 2:
            try:
                idx = int(parts[1]) - 1
                if 0 <= idx < len(articles):
                    article = articles[idx]
                    _remove_from_remarkable(config, article["pdf_filename"])
                    print(f"    Removed: {article['title']}")
                    ragtime.remember(
                        f"User removed article '{article['title']}' [{article['topic_tag']}] "
                        f"from {article['source_domain']}. Don't send similar.",
                        type="preference", component="articles",
                    )
                else:
                    print(f"    Invalid article number. Range: 1-{len(articles)}")
            except ValueError:
                print("    Usage: remove <number>")

        elif action == "send" and len(parts) == 2:
            try:
                idx = int(parts[1]) - 1
                if 0 <= idx < len(emails_skipped):
                    email_data = emails_skipped[idx]
                    print(f"    Sending: {email_data['subject']}")
                    _send_skipped_email(config, ragtime, email_data, date, feedback_base_url)
                    ragtime.remember(
                        f"User requested skipped email '{email_data['subject']}' from "
                        f"{email_data['sender_name']} <{email_data['sender_email']}>. "
                        f"Score was {email_data['importance_score']}/10 — should have been surfaced.",
                        type="context", component="contacts",
                    )
                    print(f"    Sent to Remarkable.")
                else:
                    print(f"    Invalid email number. Range: 1-{len(emails_skipped)}")
            except ValueError:
                print("    Usage: send <number>")

        elif action == "feedback":
            text = input("    What feedback? > ").strip()
            if text:
                ragtime.remember(
                    f"User feedback on {date} digest: \"{text}\"",
                    type="preference", component="articles",
                )
                print("    Stored.")

        else:
            print("    Commands: remove <n>, send <n>, feedback, done")


# ── Review mode (end-of-day triage) ──────────────────────────────────

def mode_review(config: dict, ragtime: RagtimeClient) -> None:
    """Triage items from Remarkable that weren't engaged with."""
    print(f"\n{'═' * 60}")
    print(f"  End-of-day Review")
    print(f"{'═' * 60}")

    REVIEWED_DIR.mkdir(parents=True, exist_ok=True)
    unengaged = _find_unengaged()

    if not unengaged:
        print("\n  Nothing to triage — you engaged with everything.")
        print(f"{'═' * 60}\n")
        return

    articles = [u for u in unengaged if u["type"] == "article"]
    senders = [u for u in unengaged if u["type"] == "sender"]
    emails = [u for u in unengaged if u["type"] == "email"]

    print(f"\n  {len(unengaged)} items to triage:")
    print(f"    {len(articles)} articles, {len(senders)} new senders, {len(emails)} emails")
    print()
    print("  For each item:")
    print("    [s] Skipped — not interested")
    print("    [b] Busy — didn't get to it")
    print("    [r] Read it — read but didn't rate")
    print("    [d] Done — handled outside digest")
    print("    [enter] Skip this review item")
    print()

    reviewed = 0

    if articles:
        print(f"{'─' * 60}")
        print(f"  Articles ({len(articles)})")
        print(f"{'─' * 60}")
        for item in articles:
            result = _triage_article(item)
            if result:
                _store_article_triage(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    if senders:
        print(f"\n{'─' * 60}")
        print(f"  New Senders ({len(senders)})")
        print(f"{'─' * 60}")
        for item in senders:
            result = _triage_sender(item)
            if result:
                _store_sender_triage(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    if emails:
        print(f"\n{'─' * 60}")
        print(f"  Emails ({len(emails)})")
        print(f"{'─' * 60}")
        for item in emails:
            result = _triage_email(item)
            if result:
                _store_email_triage(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    print(f"\n{'═' * 60}")
    print(f"  Reviewed {reviewed} items.")
    print(f"{'═' * 60}\n")


# ── Manifest ─────────────────────────────────────────────────────────

def _build_manifest(
    date: str,
    articles: list[Article],
    emails_sent: list[EmailItem],
    emails_skipped: list[EmailItem],
    article_pdfs: list[str],
    email_pdfs: list[str],
) -> dict:
    """Build a run manifest with everything needed for the briefing."""
    return {
        "date": date,
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "topic_tag": a.topic_tag,
                "source_domain": a.source_domain,
                "estimated_minutes": a.estimated_minutes,
                "reason": a.reason,
                "pdf_filename": a.filename,
                "pdf_path": article_pdfs[i] if i < len(article_pdfs) else "",
            }
            for i, a in enumerate(articles)
        ],
        "emails_sent": [
            {
                "sender_name": e.sender_name,
                "sender_email": e.sender_email,
                "subject": e.subject,
                "importance_score": e.importance_score,
                "importance_reason": e.importance_reason,
                "suggested_action": e.suggested_action,
                "is_new_sender": e.is_new_sender,
                "account_id": e.account_id,
                "message_id": e.message_id,
                "thread_id": e.thread_id,
                "snippet": e.snippet,
                "pdf_filename": e.filename,
                "pdf_path": email_pdfs[i] if i < len(email_pdfs) else "",
            }
            for i, e in enumerate(emails_sent)
        ],
        "emails_skipped": [
            {
                "sender_name": e.sender_name,
                "sender_email": e.sender_email,
                "subject": e.subject,
                "importance_score": e.importance_score,
                "importance_reason": e.importance_reason,
                "suggested_action": e.suggested_action,
                "is_new_sender": e.is_new_sender,
                "account_id": e.account_id,
                "message_id": e.message_id,
                "thread_id": e.thread_id,
                "snippet": e.snippet,
            }
            for e in emails_skipped
        ],
    }


def _save_manifest(date: str, manifest: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{date}.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))
    logger.info(f"Saved run manifest: {path}")


def _load_manifest(date: str) -> dict | None:
    path = RUNS_DIR / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ── Remarkable operations ────────────────────────────────────────────

def _remove_from_remarkable(config: dict, filename: str) -> None:
    rm_config = config.get("delivery", {}).get("remarkable", {})
    if not rm_config.get("enabled", False):
        return

    from integrations.remarkable import RemarkableClient

    rm = RemarkableClient(rmapi_path=rm_config.get("rmapi_path", "rmapi"))
    folder = rm_config.get("folder", "/Morning Digest")
    # Strip .pdf extension — rmapi uses document names without extension
    doc_name = filename.replace(".pdf", "")
    rm.delete_file(f"{folder}/{doc_name}")


def _send_skipped_email(
    config: dict, ragtime: RagtimeClient,
    email_data: dict, date: str, feedback_base_url: str,
) -> None:
    """Fetch the full email body, generate PDF, and deliver."""
    from integrations.email_clients import create_client

    # Reconstruct just enough of an EmailItem to generate the PDF
    account = next(
        (a for a in config["email"]["accounts"] if a["id"] == email_data.get("account_id", "")),
        None,
    )

    body_text = ""
    body_html = ""
    if account:
        try:
            client = create_client(account)
            client.authenticate()
            body_text, body_html = client.fetch_full_body(email_data["message_id"])
        except Exception as e:
            logger.warning(f"Failed to fetch body: {e}")

    email_item = EmailItem(
        message_id=email_data.get("message_id", ""),
        thread_id=email_data.get("thread_id", ""),
        account_id=email_data.get("account_id", ""),
        sender_name=email_data["sender_name"],
        sender_email=email_data["sender_email"],
        subject=email_data["subject"],
        snippet=email_data.get("snippet", ""),
        received_date=datetime.now(),
        importance_score=email_data.get("importance_score", 0),
        importance_reason=email_data.get("importance_reason", ""),
        suggested_action=email_data.get("suggested_action", ""),
        body_text=body_text,
        body_html=body_html,
        is_new_sender=email_data.get("is_new_sender", False),
    )

    output_dir = f"/tmp/digest/{date}"
    pdf_path = email_pdf.generate(email_item, output_dir=output_dir, feedback_base_url=feedback_base_url)
    _deliver_pdfs(config, [pdf_path])


def _archive_remarkable(config: dict, today: str) -> None:
    """Move yesterday's PDFs to /Morning Digest/Archive/YYYY-MM-DD/."""
    delivery = config.get("delivery", {})
    rm_config = delivery.get("remarkable", {})
    if not rm_config.get("enabled", False):
        return

    from integrations.remarkable import RemarkableClient

    rm = RemarkableClient(rmapi_path=rm_config.get("rmapi_path", "rmapi"))
    folder = rm_config.get("folder", "/Morning Digest")
    archive_base = f"{folder}/Archive"
    rm.ensure_folder(archive_base)

    files = rm.list_files(folder)
    if not files:
        return

    # Determine archive date — use yesterday if we're running in the morning
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    archive_folder = f"{archive_base}/{yesterday}"

    moved = 0
    for filename in files:
        fname = filename.strip()
        if fname.endswith("/") or fname == "Archive":
            continue
        try:
            rm.ensure_folder(archive_folder)
            rm.move_file(f"{folder}/{fname}", archive_folder)
            moved += 1
        except Exception as e:
            logger.warning(f"Failed to archive {fname}: {e}")

    if moved:
        logger.info(f"Archived {moved} items to {archive_folder}")


def _deliver_pdfs(config: dict, pdf_paths: list[str]) -> None:
    delivery = config.get("delivery", {})

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


# ── Feedback processing ──────────────────────────────────────────────

def _process_feedback_submissions(ragtime: RagtimeClient) -> int:
    if not SUBMISSIONS_DIR.exists():
        return 0

    count = 0
    for submission_file in SUBMISSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(submission_file.read_text())
            feedback_type = data.get("type", "")

            if feedback_type == "article":
                _process_article_feedback(data, ragtime)
            elif feedback_type == "sender":
                _process_sender_feedback(data, ragtime)
            elif feedback_type == "email":
                _process_email_feedback(data, ragtime)

            PROCESSED_DIR.mkdir(exist_ok=True)
            submission_file.rename(PROCESSED_DIR / submission_file.name)
            count += 1
        except Exception as e:
            logger.error(f"Error processing feedback {submission_file.name}: {e}")

    return count


def _process_skipped_items(ragtime: RagtimeClient) -> int:
    if not META_DIR.exists():
        return 0

    SKIPPED_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    count = 0

    for meta_file in META_DIR.glob("*.json"):
        feedback_id = meta_file.stem

        if any((d / f"{feedback_id}.json").exists()
               for d in [SUBMISSIONS_DIR, PROCESSED_DIR, SKIPPED_DIR, REVIEWED_DIR]):
            continue

        age_hours = (now - datetime.fromtimestamp(meta_file.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 20:
            continue

        try:
            data = json.loads(meta_file.read_text())
            _store_skip_signal(data, ragtime)
            meta_file.rename(SKIPPED_DIR / meta_file.name)
            count += 1
        except Exception as e:
            logger.warning(f"Error processing skip for {feedback_id}: {e}")

    return count


def _process_article_feedback(data: dict, ragtime: RagtimeClient) -> None:
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
    from models.sender_feedback import SenderFeedback

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
            type="preference", component="contacts",
        )


def _process_email_feedback(data: dict, ragtime: RagtimeClient) -> None:
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


def _store_skip_signal(meta: dict, ragtime: RagtimeClient) -> None:
    item_type = meta.get("type", "")
    if item_type == "article":
        ragtime.remember(
            f"Skipped article (no feedback): '{meta.get('title', '')}' "
            f"from {meta.get('source_domain', '')}. Topic: [{meta.get('topic_tag', '')}]. Weak negative.",
            type="preference", component="articles",
        )
    elif item_type == "sender":
        ragtime.remember(
            f"Skipped sender classification: {meta.get('sender_name', '')} "
            f"<{meta.get('sender_email', '')}>. Low priority.",
            type="context", component="contacts",
        )
    elif item_type == "email":
        ragtime.remember(
            f"Skipped email: '{meta.get('subject', '')}' from "
            f"{meta.get('sender_name', '')}. Weak negative.",
            type="context", component="contacts",
        )


# ── Review/triage helpers ────────────────────────────────────────────

def _find_unengaged() -> list[dict]:
    if not META_DIR.exists():
        return []

    unengaged = []
    for meta_file in sorted(META_DIR.glob("*.json")):
        fid = meta_file.stem

        if any((d / f"{fid}.json").exists()
               for d in [SUBMISSIONS_DIR, PROCESSED_DIR, SKIPPED_DIR, REVIEWED_DIR]):
            continue

        age_hours = (datetime.now() - datetime.fromtimestamp(meta_file.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 4:
            continue

        try:
            data = json.loads(meta_file.read_text())
            data["feedback_id"] = fid
            data["age_hours"] = round(age_hours, 1)
            unengaged.append(data)
        except Exception:
            continue

    return unengaged


def _triage_article(item: dict) -> str | None:
    print(f"\n  {item.get('title', 'unknown')}")
    print(f"    {item.get('source_domain', '')} · [{item.get('topic_tag', '')}] · {item['age_hours']}h ago")
    choice = input("    [s]kipped / [b]usy / [r]ead / [enter] skip: ").strip().lower()
    return choice if choice in ("s", "b", "r") else None


def _triage_sender(item: dict) -> str | None:
    print(f"\n  {item.get('sender_name', '')} <{item.get('sender_email', '')}>")
    print(f"    Subject: {item.get('subject', '')}")
    print("    [s]kipped / [b]usy / [n]ever surface / [a]lways read / [enter] skip")
    choice = input("    > ").strip().lower()
    return choice if choice in ("s", "b", "n", "a") else None


def _triage_email(item: dict) -> str | None:
    print(f"\n  From {item.get('sender_name', '')}: {item.get('subject', '')}")
    choice = input("    [s]kipped / [b]usy / [d]one / [r]ead / [enter] skip: ").strip().lower()
    return choice if choice in ("s", "b", "d", "r") else None


def _store_article_triage(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    title = item.get("title", "")
    topic = item.get("topic_tag", "")
    domain = item.get("source_domain", "")

    signals = {
        "s": (f"Review: skipped article '{title}' from {domain}. Topic: [{topic}]. Not interested.", "preference"),
        "b": (f"Review: didn't get to article '{title}' from {domain}. Topic: [{topic}]. No signal.", "context"),
        "r": (f"Review: read but didn't rate article '{title}' from {domain}. Topic: [{topic}]. Weak positive.", "preference"),
    }
    text, mem_type = signals[choice]
    ragtime.remember(text, type=mem_type, component="articles" if mem_type == "preference" else "run-history")


def _store_sender_triage(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    name = item.get("sender_name", "")
    email = item.get("sender_email", "")

    if choice == "s":
        ragtime.remember(f"Review: skipped classifying {name} <{email}>. Low priority.", type="context", component="contacts")
    elif choice == "n":
        ragtime.remember(f"SUPPRESS emails from {name} <{email}>. User marked as never surface.", type="preference", component="contacts")
        ragtime.remember(f"{name} <{email}>: Importance: never. Classified via daily review.", type="context", component="contacts")
    elif choice == "a":
        ragtime.remember(f"{name} <{email}>: Importance: always. Classified via daily review.", type="context", component="contacts")
    elif choice == "b":
        ragtime.remember(f"Review: didn't get to classifying {name} <{email}>. No signal.", type="context", component="run-history")


def _store_email_triage(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    sender = item.get("sender_name", "")
    email_addr = item.get("sender_email", "")
    subject = item.get("subject", "")

    signals = {
        "s": f"Review: skipped email '{subject}' from {sender} <{email_addr}>. Reduce score for similar.",
        "d": f"Review: handled email '{subject}' from {sender} <{email_addr}> outside digest. Positive signal.",
        "r": f"Review: read email '{subject}' from {sender} <{email_addr}> but didn't act. Worth reading.",
        "b": f"Review: didn't get to email '{subject}' from {sender}. No signal.",
    }
    component = "run-history" if choice == "b" else "contacts"
    ragtime.remember(signals[choice], type="context", component=component)


def _mark_reviewed(feedback_id: str) -> None:
    meta_file = META_DIR / f"{feedback_id}.json"
    if meta_file.exists():
        REVIEWED_DIR.mkdir(parents=True, exist_ok=True)
        meta_file.rename(REVIEWED_DIR / meta_file.name)


if __name__ == "__main__":
    main()
