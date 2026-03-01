from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SenderFeedback:
    """Feedback collected from the sender onboarding form on email PDFs."""

    source_filename: str
    sender_name: str = ""
    sender_email: str = ""
    who_is_this: str = ""
    importance: str = ""  # "always" | "sometimes" | "rarely" | "never"
    context: str = ""
    was_email_worth_surfacing: str = ""  # "yes" | "no"
    parsed_at: datetime = field(default_factory=datetime.now)
    raw_fields: dict = field(default_factory=dict)

    def to_ragtime_memory(self) -> str:
        """Format as a ragtime contact memory string."""
        parts = [f"{self.sender_name} <{self.sender_email}>:"]

        if self.who_is_this:
            parts.append(f'"{self.who_is_this}".')

        parts.append(f"Importance: {self.importance}.")

        if self.context:
            parts.append(f'Context: "{self.context}".')

        if self.was_email_worth_surfacing:
            parts.append(f"First email surfaced was: {self.was_email_worth_surfacing}.")

        parts.append(f"Classified: {self.parsed_at.strftime('%Y-%m-%d')}.")

        return " ".join(parts)
