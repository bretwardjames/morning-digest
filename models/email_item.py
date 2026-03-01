from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailItem:
    message_id: str
    thread_id: str
    account_id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received_date: datetime
    importance_score: float = 0.0
    importance_reason: str = ""
    suggested_action: str = ""
    body_text: str = ""
    body_html: str = ""
    is_new_sender: bool = False
    recipients: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """URL-safe slug from subject for filenames."""
        import re
        slug = self.subject.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")[:60]

    @property
    def filename(self) -> str:
        """Generate filename: email_account_slug.pdf (no date — date lives in archive folders)."""
        return f"email_{self.account_id}_{self.slug}.pdf"
