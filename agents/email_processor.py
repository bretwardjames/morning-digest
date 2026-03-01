"""Email processor agent — reads accounts, scores importance via Claude."""

import json
import logging

import anthropic

from integrations.email_clients import create_client
from integrations.ragtime import RagtimeClient
from models.email_item import EmailItem

logger = logging.getLogger(__name__)

IMPORTANCE_THRESHOLD = 7
NEW_SENDER_THRESHOLD = 4  # Lower bar — surface new senders for classification


def get_important_emails(
    config: dict, ragtime: RagtimeClient,
) -> tuple[list[EmailItem], list[EmailItem]]:
    """Fetch emails from all accounts, score importance.

    Returns:
        (surfaced, skipped) — surfaced emails have full bodies fetched,
        skipped emails have metadata + scores only (for the briefing).
    """
    all_emails: list[EmailItem] = []

    # 1. Fetch from each account
    for account in config["email"]["accounts"]:
        try:
            client = create_client(account)
            client.authenticate()
            emails = client.fetch_recent_emails()
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Failed to fetch from {account['id']}: {e}")
            continue

    if not all_emails:
        logger.info("No emails found across any account")
        return [], []

    # 2. Flag new senders (no ragtime context)
    for email in all_emails:
        sender_context = ragtime.search(email.sender_email)
        if not sender_context or not sender_context[0].get("text", "").strip():
            email.is_new_sender = True

    # 3. Score importance (metadata only, no full bodies)
    scored = _score_emails(all_emails, config, ragtime)

    # 4. Split into surfaced and skipped
    surfaced = []
    skipped = []
    for e in scored:
        threshold = NEW_SENDER_THRESHOLD if e.is_new_sender else IMPORTANCE_THRESHOLD
        if e.importance_score >= threshold:
            surfaced.append(e)
        else:
            skipped.append(e)

    new_count = sum(1 for e in surfaced if e.is_new_sender)
    logger.info(f"{new_count} of {len(surfaced)} surfaced emails are from new senders")

    # 5. Fetch full bodies for surfaced emails only
    for email in surfaced:
        try:
            account = next(a for a in config["email"]["accounts"] if a["id"] == email.account_id)
            client = create_client(account)
            client.authenticate()
            plain, html = client.fetch_full_body(email.message_id)
            email.body_text = plain
            email.body_html = html
        except Exception as e:
            logger.warning(f"Failed to fetch body for {email.subject}: {e}")

    surfaced.sort(key=lambda e: e.importance_score, reverse=True)
    skipped.sort(key=lambda e: e.importance_score, reverse=True)
    logger.info(f"Found {len(surfaced)} important, {len(skipped)} skipped out of {len(all_emails)} total")
    return surfaced, skipped


def _score_emails(emails: list[EmailItem], config: dict, ragtime: RagtimeClient) -> list[EmailItem]:
    """Score email importance using Claude. Only sends metadata, not full bodies."""
    criteria = config["email"]["importance_criteria"]

    # Build metadata summaries for Claude
    email_summaries = []
    for i, email in enumerate(emails):
        # Check ragtime for sender context
        sender_context = ragtime.search(email.sender_email)
        context_text = sender_context[0].get("text", "") if sender_context else "No prior contact history."

        email_summaries.append({
            "index": i,
            "from": f"{email.sender_name} <{email.sender_email}>",
            "subject": email.subject,
            "snippet": email.snippet[:200],
            "date": email.received_date.isoformat(),
            "account": email.account_id,
            "sender_context": context_text,
        })

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Score these emails for importance on a scale of 1-10.

Importance criteria:
{json.dumps(criteria, indent=2)}

Emails to score:
{json.dumps(email_summaries, indent=2)}

Return a JSON array: [{{"index": 0, "score": 7, "reason": "...", "suggested_action": "read|reply|ignore"}}]
Return ONLY valid JSON.""",
        }],
    )

    # Parse scores and apply to emails
    for block in response.content:
        if block.type == "text":
            try:
                text = block.text.strip()
                if text.startswith("```"):
                    text = "\n".join(text.split("\n")[1:])
                if text.endswith("```"):
                    text = "\n".join(text.split("\n")[:-1])

                scores = json.loads(text.strip())
                for score_item in scores:
                    idx = score_item["index"]
                    if 0 <= idx < len(emails):
                        emails[idx].importance_score = score_item["score"]
                        emails[idx].importance_reason = score_item.get("reason", "")
                        emails[idx].suggested_action = score_item.get("suggested_action", "")
                break
            except (json.JSONDecodeError, KeyError):
                continue

    return emails
