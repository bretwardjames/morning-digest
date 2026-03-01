"""Morning Digest — sender onboarding interview.

Reads the last 5 days of emails from all configured accounts, groups by sender,
has Claude pre-categorize them, then walks the user through an interactive
review to seed ragtime with sender context before the first digest run.

Usage:
    python init.py
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime

import anthropic
import yaml

from integrations.email_clients import create_client
from integrations.ragtime import RagtimeClient
from models.email_item import EmailItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 5 * 24  # 5 days


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    print("\n=== Morning Digest — Sender Onboarding ===\n")
    print("This will read your last 5 days of email, group senders,")
    print("and ask you to confirm or correct how I've categorized them.")
    print("Your answers get stored in ragtime so the daily digest knows")
    print("which emails actually matter to you.\n")

    config = load_config()
    ragtime = RagtimeClient(
        project_path=config["ragtime"]["project_path"],
        namespace=config["ragtime"]["namespace"],
    )

    # 1. Fetch emails from all accounts
    all_emails = _fetch_all_emails(config)
    if not all_emails:
        print("No emails found. Check your account credentials and try again.")
        return

    # 2. Group by sender
    sender_profiles = _aggregate_senders(all_emails)
    print(f"\nFound {len(sender_profiles)} unique senders across {len(all_emails)} emails.\n")

    # 3. Have Claude pre-categorize
    print("Analyzing senders...\n")
    categories = _categorize_senders(sender_profiles)

    # 4. Interactive review
    confirmed = _run_interview(categories, sender_profiles)

    # 5. Store in ragtime
    stored = 0
    for sender_key, profile in confirmed.items():
        memory = _format_sender_memory(profile)
        ragtime.remember(memory, type="context", component="contacts")
        stored += 1

    print(f"\n=== Done! Stored {stored} sender profiles in ragtime. ===")
    print("Your daily digest will use these to score email importance.")
    print("Run `python main.py` to generate your first digest.\n")


def _fetch_all_emails(config: dict) -> list[EmailItem]:
    """Fetch last 5 days of emails from all configured accounts."""
    all_emails = []

    for account in config["email"]["accounts"]:
        print(f"  Connecting to {account['id']}...")
        try:
            client = create_client(account)
            client.authenticate()
            emails = client.fetch_recent_emails(since_hours=LOOKBACK_HOURS)
            all_emails.extend(emails)
            print(f"  ✓ {account['id']}: {len(emails)} emails")
        except Exception as e:
            print(f"  ✗ {account['id']}: {e}")
            logger.error(f"Failed to fetch from {account['id']}: {e}")

    return all_emails


def _aggregate_senders(emails: list[EmailItem]) -> dict[str, dict]:
    """Group emails by sender, build a profile for each.

    Returns dict keyed by sender_email with:
        name, email, count, accounts, subjects, latest_date
    """
    grouped: dict[str, list[EmailItem]] = defaultdict(list)
    for email in emails:
        grouped[email.sender_email].append(email)

    profiles = {}
    for sender_email, sender_emails in grouped.items():
        sender_emails.sort(key=lambda e: e.received_date, reverse=True)
        profiles[sender_email] = {
            "name": sender_emails[0].sender_name,
            "email": sender_email,
            "count": len(sender_emails),
            "accounts": list({e.account_id for e in sender_emails}),
            "subjects": [e.subject for e in sender_emails[:5]],
            "snippets": [e.snippet[:100] for e in sender_emails[:3]],
            "latest_date": sender_emails[0].received_date.isoformat(),
        }

    return dict(sorted(profiles.items(), key=lambda x: x[1]["count"], reverse=True))


def _categorize_senders(profiles: dict[str, dict]) -> dict:
    """Send sender profiles to Claude for pre-categorization.

    Returns Claude's categorization as a dict with category keys mapping
    to lists of sender emails with reasoning.
    """
    # Build a compact summary for Claude
    sender_list = []
    for email, p in profiles.items():
        sender_list.append({
            "email": email,
            "name": p["name"],
            "count": p["count"],
            "subjects": p["subjects"],
            "accounts": p["accounts"],
        })

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Categorize these email senders based on their names, email addresses, and
subject lines. Group them into these categories:

- **vip**: Likely a real person the user works with or knows personally.
  These emails probably need to be read.
- **regular**: Real person but lower frequency or less clear relationship.
  Might be important sometimes.
- **newsletter**: Newsletters, digests, or content subscriptions.
  Rarely urgent, sometimes interesting.
- **automated**: System notifications, receipts, alerts, no-reply addresses.
  Almost never needs human attention.
- **unknown**: Can't tell from the metadata alone.

Senders to categorize:
{json.dumps(sender_list, indent=2)}

Return JSON with this structure:
{{
  "vip": [{{"email": "...", "name": "...", "reason": "why you think this"}}],
  "regular": [...],
  "newsletter": [...],
  "automated": [...],
  "unknown": [...]
}}

Return ONLY valid JSON.""",
        }],
    )

    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = "\n".join(text.split("\n")[:-1])
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError:
                continue

    logger.error("Failed to parse Claude's categorization")
    return {"unknown": [{"email": e, "name": p["name"], "reason": "categorization failed"} for e, p in profiles.items()]}


def _run_interview(categories: dict, profiles: dict[str, dict]) -> dict[str, dict]:
    """Walk the user through each category for confirmation, then do deep-dive on VIPs."""
    confirmed = {}
    category_labels = {
        "vip": ("VIP — people who matter", "always"),
        "regular": ("Regular contacts", "sometimes"),
        "newsletter": ("Newsletters & subscriptions", "rarely"),
        "automated": ("Automated / system emails", "never"),
        "unknown": ("Couldn't categorize", "unknown"),
    }

    # Phase 1: Batch review by category
    for category, (label, default_importance) in category_labels.items():
        senders = categories.get(category, [])
        if not senders:
            continue

        print(f"\n{'─' * 60}")
        print(f"  {label} ({len(senders)} senders)")
        print(f"{'─' * 60}")

        for s in senders:
            email = s["email"]
            name = s.get("name", "")
            reason = s.get("reason", "")
            p = profiles.get(email, {})
            count = p.get("count", 0)
            subjects = p.get("subjects", [])

            print(f"\n  {name} <{email}>")
            print(f"  {count} emails in 5 days | Reason: {reason}")
            if subjects:
                print(f"  Recent: {subjects[0]}")

        print(f"\n  Default importance for this group: {default_importance}")
        response = input("  Accept all? [Y/n/pick] ").strip().lower()

        if response in ("", "y", "yes"):
            # Accept all as-is
            for s in senders:
                email = s["email"]
                p = profiles.get(email, {})
                confirmed[email] = {
                    **p,
                    "category": category,
                    "importance": default_importance,
                    "context": s.get("reason", ""),
                }
        elif response == "pick":
            # Review one by one
            for s in senders:
                email = s["email"]
                name = s.get("name", "")
                p = profiles.get(email, {})
                confirmed[email] = _interview_single_sender(email, name, p, category, default_importance)
        else:
            # "n" — skip this category, mark as unknown
            for s in senders:
                email = s["email"]
                p = profiles.get(email, {})
                confirmed[email] = {
                    **p,
                    "category": "unknown",
                    "importance": "unknown",
                    "context": "",
                }

    # Phase 2: Deep-dive on VIPs
    vips = {k: v for k, v in confirmed.items() if v.get("importance") == "always"}
    if vips:
        print(f"\n{'═' * 60}")
        print(f"  Deep-dive: {len(vips)} VIP senders")
        print(f"  Add context so the digest knows WHY they matter.")
        print(f"{'═' * 60}")

        for email, profile in vips.items():
            name = profile.get("name", email)
            print(f"\n  {name} <{email}>")
            subjects = profile.get("subjects", [])
            if subjects:
                print(f"  Recent subjects:")
                for subj in subjects[:3]:
                    print(f"    • {subj}")

            context = input("  Who is this person / why do their emails matter?\n  > ").strip()
            if context:
                confirmed[email]["context"] = context

    return confirmed


def _interview_single_sender(
    email: str, name: str, profile: dict, suggested_category: str, suggested_importance: str
) -> dict:
    """Interview the user about a single sender."""
    print(f"\n    {name} <{email}>")
    subjects = profile.get("subjects", [])
    if subjects:
        for subj in subjects[:2]:
            print(f"      • {subj}")

    print(f"    Suggested: {suggested_category} ({suggested_importance})")
    imp = input("    Importance? [always/sometimes/rarely/never/skip] ").strip().lower()

    if imp == "skip" or not imp:
        imp = suggested_importance

    context = ""
    if imp in ("always", "sometimes"):
        context = input("    Any context? > ").strip()

    return {
        **profile,
        "category": suggested_category if imp == suggested_importance else "override",
        "importance": imp,
        "context": context,
    }


def _format_sender_memory(profile: dict) -> str:
    """Format a confirmed sender profile as a ragtime memory string."""
    name = profile.get("name", "")
    email = profile.get("email", "")
    importance = profile.get("importance", "unknown")
    context = profile.get("context", "")
    count = profile.get("count", 0)
    category = profile.get("category", "unknown")
    latest = profile.get("latest_date", "")

    parts = [f"{name} <{email}>: Category: {category}. Importance: {importance}."]

    if context:
        parts.append(f'Context: "{context}".')

    parts.append(f"Frequency: {count} emails in last 5 days. Last seen: {latest}.")

    return " ".join(parts)


if __name__ == "__main__":
    main()
