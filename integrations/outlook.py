"""Microsoft Outlook integration via Microsoft Graph API."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import msal
import requests

from models.email_item import EmailItem

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "Mail.ReadWrite"]


class OutlookClient:
    def __init__(self, account_id: str, client_id: str, tenant_id: str, credentials_file: str):
        self.account_id = account_id
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.credentials_file = credentials_file
        self.access_token: str | None = None

    def authenticate(self) -> None:
        """Authenticate via MSAL device code or cached token."""
        cache = msal.SerializableTokenCache()
        cache_path = Path(self.credentials_file)

        if cache_path.exists():
            cache.deserialize(cache_path.read_text())

        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )

        accounts = app.get_accounts()
        result = None

        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])

        if not result:
            flow = app.initiate_device_flow(scopes=SCOPES)
            logger.info(f"Outlook auth: {flow['message']}")
            print(flow["message"])
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            self.access_token = result["access_token"]
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(cache.serialize())
            logger.info(f"Outlook authenticated for {self.account_id}")
        else:
            raise RuntimeError(f"Outlook auth failed: {result.get('error_description', 'unknown')}")

    def fetch_recent_emails(self, since_hours: int = 24) -> list[EmailItem]:
        """Fetch emails received in the last N hours."""
        since = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat() + "Z"
        url = f"{GRAPH_BASE}/me/messages"
        params = {
            "$filter": f"receivedDateTime ge {since}",
            "$select": "id,conversationId,from,toRecipients,subject,bodyPreview,receivedDateTime",
            "$top": 50,
            "$orderby": "receivedDateTime desc",
        }

        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        data = response.json()

        emails = []
        for msg in data.get("value", []):
            sender = msg.get("from", {}).get("emailAddress", {})
            recipients = [
                r["emailAddress"]["address"]
                for r in msg.get("toRecipients", [])
                if "emailAddress" in r
            ]

            emails.append(EmailItem(
                message_id=msg["id"],
                thread_id=msg.get("conversationId", ""),
                account_id=self.account_id,
                sender_name=sender.get("name", ""),
                sender_email=sender.get("address", ""),
                subject=msg.get("subject", "(no subject)"),
                snippet=msg.get("bodyPreview", ""),
                received_date=datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00")),
                recipients=recipients,
            ))

        logger.info(f"Fetched {len(emails)} emails from {self.account_id}")
        return emails

    def fetch_full_body(self, message_id: str) -> tuple[str, str]:
        """Fetch full email body. Returns (plain_text, html)."""
        url = f"{GRAPH_BASE}/me/messages/{message_id}"
        params = {"$select": "body"}

        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()

        body = response.json().get("body", {})
        content = body.get("content", "")
        content_type = body.get("contentType", "text")

        if content_type == "html":
            return "", content
        return content, ""

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}
