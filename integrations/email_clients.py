"""Factory for creating email clients from account config."""

import os

from integrations.gmail import GmailClient
from integrations.outlook import OutlookClient


def create_client(account: dict) -> GmailClient | OutlookClient:
    """Create the appropriate email client based on account type."""
    if account["type"] == "gmail":
        return GmailClient(account["id"], account["credentials_file"])
    elif account["type"] == "outlook":
        return OutlookClient(
            account_id=account["id"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            tenant_id=os.environ["AZURE_TENANT_ID"],
            credentials_file=account["credentials_file"],
        )
    else:
        raise ValueError(f"Unknown account type: {account['type']}")
