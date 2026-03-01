from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Feedback:
    source_filename: str
    was_read: bool = False
    rating: int | None = None
    liked_text: str = ""
    disliked_text: str = ""
    want_more: str = ""  # "more" | "less" | "neutral"
    topic_tags: list[str] = field(default_factory=list)
    other_tag: str = ""
    parsed_at: datetime = field(default_factory=datetime.now)
    raw_fields: dict = field(default_factory=dict)

    @property
    def is_positive(self) -> bool:
        return (self.rating is not None and self.rating >= 7) or self.want_more == "more"

    @property
    def is_negative(self) -> bool:
        return (self.rating is not None and self.rating <= 4) or self.want_more == "less"

    def to_ragtime_memory(self) -> str:
        """Format feedback as a ragtime memory string."""
        signal = "more" if self.is_positive else "less" if self.is_negative else "neutral"
        tags = ", ".join(self.topic_tags) if self.topic_tags else "untagged"

        parts = [f"Rating: {self.rating}/10" if self.rating else "Unrated"]
        if self.liked_text:
            parts.append(f'Liked: "{self.liked_text}"')
        if self.disliked_text:
            parts.append(f'Disliked: "{self.disliked_text}"')
        parts.append(f"Signal: {signal} of [{tags}]")

        return f"Article feedback for {self.source_filename}. " + ". ".join(parts) + "."
