"""Content curator agent — discovers and selects articles via Claude + web_search."""

import json
import logging
from datetime import datetime

import anthropic
import trafilatura

from integrations.ragtime import RagtimeClient
from models.article import Article

logger = logging.getLogger(__name__)

READING_SPEED_WPM = 238


def find_articles(config: dict, ragtime: RagtimeClient) -> list[Article]:
    """Discover and select articles matching user preferences.

    Uses Claude with web_search to find recent articles, then fetches
    and filters them to fit the target reading window.
    """
    # 1. Get feedback signals from ragtime
    feedback_signals = ragtime.search("article preferences liked disliked")
    signals_text = "\n".join(
        s.get("text", str(s)) for s in feedback_signals
    ) if feedback_signals else "No feedback history yet."

    # 2. Build topic description for Claude
    topics = config["content"]["topics"]
    topic_desc = ""
    for name, info in topics.items():
        angles = ", ".join(info["angles"])
        topic_desc += f"- {name} (weight {info['weight']}): {angles}\n"

    target_minutes = config["content"]["target_reading_minutes"]
    excluded = config["content"]["sources"].get("excluded_domains", [])
    preferred = config["content"]["sources"].get("preferred_domains", [])

    # 3. Call Claude with web_search tool
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        tools=[{"type": "web_search_20250305"}],
        messages=[{
            "role": "user",
            "content": f"""You are a content curator. Find articles published in the last 48 hours
matching these topic preferences:

{topic_desc}

Feedback signals from past digests:
{signals_text}

Target reading window: {target_minutes} minutes total.
Estimated read time formula: word_count / {READING_SPEED_WPM} minutes.

Return a JSON array: [{{"title": "", "url": "", "topic_tag": "", "estimated_minutes": 0, "reason": ""}}]
Select enough articles to fill ~{target_minutes} minutes. Prioritize higher-weight topics.
Exclude: purely partisan opinion pieces, content from {excluded}.
Prefer content from: {preferred if preferred else "no preference"}.

IMPORTANT: Return ONLY valid JSON. No markdown fences, no explanation.""",
        }],
    )

    # 4. Parse Claude's response
    articles_json = _extract_json_from_response(response)
    if not articles_json:
        logger.error("Failed to parse articles from Claude response")
        return []

    # 5. Fetch and validate each article
    min_words = config["content"]["sources"].get("min_word_count", 300)
    max_words = config["content"]["sources"].get("max_word_count", 5000)
    articles = []

    for item in articles_json:
        try:
            downloaded = trafilatura.fetch_url(item["url"])
            if not downloaded:
                logger.warning(f"Failed to fetch: {item['url']}")
                continue

            text = trafilatura.extract(downloaded, include_comments=False)
            if not text:
                continue

            word_count = len(text.split())
            if word_count < min_words or word_count > max_words:
                logger.info(f"Skipping {item['title']}: {word_count} words (out of range)")
                continue

            articles.append(Article(
                title=item["title"],
                url=item["url"],
                topic_tag=item.get("topic_tag", "general"),
                word_count=word_count,
                estimated_minutes=round(word_count / READING_SPEED_WPM, 1),
                reason=item.get("reason", ""),
                source_domain=item["url"].split("/")[2] if "/" in item["url"] else "",
                body_text=text,
            ))
        except Exception as e:
            logger.warning(f"Error processing {item.get('url', '?')}: {e}")
            continue

    # 6. Trim to target reading window
    articles = _fit_reading_window(articles, target_minutes, tolerance=5)
    logger.info(f"Selected {len(articles)} articles, ~{sum(a.estimated_minutes for a in articles):.0f} min total")
    return articles


def _fit_reading_window(articles: list[Article], target: int, tolerance: int) -> list[Article]:
    """Select articles that fit within the target reading window."""
    # Sort by topic weight proxy (topic_tag ordering) and recency
    selected = []
    total_minutes = 0.0

    for article in articles:
        if total_minutes + article.estimated_minutes <= target + tolerance:
            selected.append(article)
            total_minutes += article.estimated_minutes

    return selected


def _extract_json_from_response(response) -> list[dict] | None:
    """Extract JSON array from Claude's response, handling mixed content blocks."""
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = "\n".join(text.split("\n")[:-1])
            text = text.strip()

            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                continue

    return None
