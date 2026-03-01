"""Daily review — quick triage of items you didn't engage with.

Run this at the end of your day (or whenever) to tell the system
why you skipped things. This produces stronger signals than the
automatic skip detection.

Usage:
    python review.py
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from integrations.ragtime import RagtimeClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

FEEDBACK_DIR = Path("data/feedback")
META_DIR = FEEDBACK_DIR / "meta"
SUBMISSIONS_DIR = FEEDBACK_DIR / "submissions"
PROCESSED_DIR = FEEDBACK_DIR / "processed"
SKIPPED_DIR = FEEDBACK_DIR / "skipped"
REVIEWED_DIR = FEEDBACK_DIR / "reviewed"


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    config = load_config()
    ragtime = RagtimeClient(
        project_path=config["ragtime"]["project_path"],
        namespace=config["ragtime"]["namespace"],
    )

    REVIEWED_DIR.mkdir(parents=True, exist_ok=True)

    # Find unengaged items: meta files with no submission, processed, skipped, or reviewed file
    unengaged = _find_unengaged()

    if not unengaged:
        print("\nNothing to review — you engaged with everything or it's too recent.")
        return

    # Group by type
    articles = [u for u in unengaged if u["type"] == "article"]
    senders = [u for u in unengaged if u["type"] == "sender"]
    emails = [u for u in unengaged if u["type"] == "email"]

    total = len(unengaged)
    print(f"\n{'═' * 50}")
    print(f"  Daily Review — {total} items to triage")
    print(f"{'═' * 50}")
    print(f"  {len(articles)} articles, {len(senders)} new senders, {len(emails)} emails")
    print()
    print("  For each item, choose:")
    print("    [s] Skipped — not interested (negative signal)")
    print("    [b] Busy — didn't get to it (neutral, no penalty)")
    print("    [r] Read it — read but didn't bother rating (weak positive)")
    print("    [d] Done — already handled the email (positive)")
    print("    [enter] Skip this review item")
    print()

    reviewed = 0

    if articles:
        print(f"{'─' * 50}")
        print(f"  Articles ({len(articles)})")
        print(f"{'─' * 50}")
        for item in articles:
            result = _review_article(item)
            if result:
                _store_article_review(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    if senders:
        print(f"\n{'─' * 50}")
        print(f"  New Senders ({len(senders)})")
        print(f"{'─' * 50}")
        for item in senders:
            result = _review_sender(item)
            if result:
                _store_sender_review(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    if emails:
        print(f"\n{'─' * 50}")
        print(f"  Emails ({len(emails)})")
        print(f"{'─' * 50}")
        for item in emails:
            result = _review_email(item)
            if result:
                _store_email_review(item, result, ragtime)
                _mark_reviewed(item["feedback_id"])
                reviewed += 1

    print(f"\n{'═' * 50}")
    print(f"  Reviewed {reviewed} items. Signals stored in ragtime.")
    print(f"{'═' * 50}\n")


def _find_unengaged() -> list[dict]:
    """Find meta files with no corresponding feedback."""
    if not META_DIR.exists():
        return []

    unengaged = []
    for meta_file in sorted(META_DIR.glob("*.json")):
        fid = meta_file.stem

        # Skip if already handled
        if any((d / f"{fid}.json").exists() for d in [SUBMISSIONS_DIR, PROCESSED_DIR, SKIPPED_DIR, REVIEWED_DIR]):
            continue

        # Skip if less than 4 hours old
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


def _review_article(item: dict) -> str | None:
    title = item.get("title", "unknown")
    topic = item.get("topic_tag", "")
    domain = item.get("source_domain", "")

    print(f"\n  {title}")
    print(f"  {domain} · {topic} · {item['age_hours']}h ago")
    choice = input("  [s]kipped / [b]usy / [r]ead / [enter] skip: ").strip().lower()

    return choice if choice in ("s", "b", "r") else None


def _review_sender(item: dict) -> str | None:
    name = item.get("sender_name", "")
    email = item.get("sender_email", "")
    subject = item.get("subject", "")

    print(f"\n  {name} <{email}>")
    print(f"  Subject: {subject}")

    # For senders, offer quick classification too
    print("  [s]kipped / [b]usy / [n]ever surface / [a]lways read / [enter] skip")
    choice = input("  > ").strip().lower()

    return choice if choice in ("s", "b", "n", "a") else None


def _review_email(item: dict) -> str | None:
    sender = item.get("sender_name", "")
    subject = item.get("subject", "")

    print(f"\n  From {sender}: {subject}")
    choice = input("  [s]kipped / [b]usy / [d]one / [r]ead / [enter] skip: ").strip().lower()

    return choice if choice in ("s", "b", "d", "r") else None


def _store_article_review(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    title = item.get("title", "")
    topic = item.get("topic_tag", "")
    domain = item.get("source_domain", "")

    if choice == "s":
        ragtime.remember(
            f"Review: skipped article '{title}' from {domain}. "
            f"Topic: [{topic}]. User explicitly not interested.",
            type="preference", component="articles",
        )
    elif choice == "b":
        ragtime.remember(
            f"Review: didn't get to article '{title}' from {domain}. "
            f"Topic: [{topic}]. No signal — user was busy.",
            type="context", component="run-history",
        )
    elif choice == "r":
        ragtime.remember(
            f"Review: read but didn't rate article '{title}' from {domain}. "
            f"Topic: [{topic}]. Weak positive — interesting enough to read.",
            type="preference", component="articles",
        )


def _store_sender_review(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    name = item.get("sender_name", "")
    email = item.get("sender_email", "")

    if choice == "s":
        ragtime.remember(
            f"Review: skipped classifying {name} <{email}>. Low priority sender.",
            type="context", component="contacts",
        )
    elif choice == "n":
        ragtime.remember(
            f"SUPPRESS emails from {name} <{email}>. User marked as never surface.",
            type="preference", component="contacts",
        )
        ragtime.remember(
            f"{name} <{email}>: Importance: never. Classified via daily review.",
            type="context", component="contacts",
        )
    elif choice == "a":
        ragtime.remember(
            f"{name} <{email}>: Importance: always. Classified via daily review.",
            type="context", component="contacts",
        )
    elif choice == "b":
        ragtime.remember(
            f"Review: didn't get to classifying {name} <{email}>. No signal.",
            type="context", component="run-history",
        )


def _store_email_review(item: dict, choice: str, ragtime: RagtimeClient) -> None:
    sender = item.get("sender_name", "")
    email_addr = item.get("sender_email", "")
    subject = item.get("subject", "")

    if choice == "s":
        ragtime.remember(
            f"Review: skipped email '{subject}' from {sender} <{email_addr}>. "
            f"Not worth surfacing — reduce score for similar.",
            type="context", component="contacts",
        )
    elif choice == "d":
        ragtime.remember(
            f"Review: handled email '{subject}' from {sender} <{email_addr}> outside digest. "
            f"Correctly surfaced — positive signal for this sender.",
            type="context", component="contacts",
        )
    elif choice == "r":
        ragtime.remember(
            f"Review: read email '{subject}' from {sender} <{email_addr}> but didn't act. "
            f"Worth reading but didn't need action.",
            type="context", component="contacts",
        )
    elif choice == "b":
        ragtime.remember(
            f"Review: didn't get to email '{subject}' from {sender}. No signal.",
            type="context", component="run-history",
        )


def _mark_reviewed(feedback_id: str) -> None:
    """Move meta file to reviewed."""
    meta_file = META_DIR / f"{feedback_id}.json"
    if meta_file.exists():
        meta_file.rename(REVIEWED_DIR / meta_file.name)


if __name__ == "__main__":
    main()
