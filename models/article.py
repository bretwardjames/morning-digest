from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    title: str
    url: str
    topic_tag: str
    word_count: int
    estimated_minutes: float
    reason: str
    source_domain: str
    published_date: datetime | None = None
    body_text: str = ""
    author: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """URL-safe slug from title for filenames."""
        import re
        slug = self.title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")[:60]

    @property
    def filename(self) -> str:
        """Generate standardized filename: YYYY-MM-DD_topic_slug.pdf"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return f"{date_str}_{self.topic_tag}_{self.slug}.pdf"
