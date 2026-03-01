"""Gmail API wrapper for reading emails."""

import base64
import logging
from datetime import datetime, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from models.email_item import EmailItem

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailClient:
    def __init__(self, account_id: str, credentials_file: str):
        self.account_id = account_id
        self.credentials_file = credentials_file
        self.token_file = f"credentials/{account_id}_token.json"
        self.service = None

    def authenticate(self) -> None:
        """Authenticate with Gmail API. Opens browser on first run."""
        creds = None
        token_path = Path(self.token_file)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)
        logger.info(f"Gmail authenticated for {self.account_id}")

    def fetch_recent_emails(self, since_hours: int = 24) -> list[EmailItem]:
        """Fetch emails received in the last N hours."""
        after_timestamp = int((datetime.now() - timedelta(hours=since_hours)).timestamp())
        query = f"after:{after_timestamp}"

        results = self.service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for msg_ref in messages:
            msg = self.service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "")
            sender_name, sender_email = self._parse_sender(sender)

            emails.append(EmailItem(
                message_id=msg["id"],
                thread_id=msg.get("threadId", ""),
                account_id=self.account_id,
                sender_name=sender_name,
                sender_email=sender_email,
                subject=headers.get("Subject", "(no subject)"),
                snippet=msg.get("snippet", ""),
                received_date=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
                recipients=[headers.get("To", "")],
            ))

        logger.info(f"Fetched {len(emails)} emails from {self.account_id}")
        return emails

    def fetch_full_body(self, message_id: str) -> tuple[str, str]:
        """Fetch full email body. Returns (plain_text, html)."""
        msg = self.service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        plain_text = ""
        html = ""

        payload = msg.get("payload", {})
        parts = payload.get("parts", [payload])

        for part in parts:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")
            if not body_data:
                continue

            decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

            if mime_type == "text/plain":
                plain_text = decoded
            elif mime_type == "text/html":
                html = decoded

        return plain_text, html

    @staticmethod
    def _parse_sender(from_header: str) -> tuple[str, str]:
        """Parse 'Display Name <email@example.com>' into (name, email)."""
        if "<" in from_header and ">" in from_header:
            name = from_header.split("<")[0].strip().strip('"')
            email = from_header.split("<")[1].split(">")[0]
            return name, email
        return "", from_header.strip()
