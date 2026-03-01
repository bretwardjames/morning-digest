"""Minimal feedback web app — receives QR code submissions from phone.

Each article/email PDF contains a QR code with a unique feedback URL.
User scans it on their phone, fills a short form, and the response
gets stored as JSON for the next digest run to parse into ragtime.

Usage:
    python -m feedback.app
    # or: flask --app feedback.app run --port 5151
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from flask import Blueprint, Flask, request, render_template, abort

logger = logging.getLogger(__name__)

app = Flask(__name__)
bp = Blueprint("feedback", __name__)

FEEDBACK_DIR = Path(__file__).parent.parent / "data" / "feedback"


@bp.route("/article/<feedback_id>", methods=["GET", "POST"])
def article_feedback(feedback_id: str):
    """Article feedback form — rating, preference, and freeform text."""
    meta = _load_meta(feedback_id)
    if not meta:
        abort(404)

    if request.method == "POST":
        submission = {
            "feedback_id": feedback_id,
            "type": "article",
            "submitted_at": datetime.now().isoformat(),
            "title": meta.get("title", ""),
            "topic_tag": meta.get("topic_tag", ""),
            "source_domain": meta.get("source_domain", ""),
            "rating": int(request.form.get("rating", 0)),
            "want_more": request.form.get("want_more", "neutral"),
            "liked": request.form.get("liked", ""),
            "disliked": request.form.get("disliked", ""),
            "tags": request.form.getlist("tags"),
        }
        _save_submission(feedback_id, submission)
        return render_template("thanks.html")

    return render_template("article_form.html", meta=meta, feedback_id=feedback_id)


@bp.route("/sender/<feedback_id>", methods=["GET", "POST"])
def sender_feedback(feedback_id: str):
    """New sender classification form."""
    meta = _load_meta(feedback_id)
    if not meta:
        abort(404)

    if request.method == "POST":
        submission = {
            "feedback_id": feedback_id,
            "type": "sender",
            "submitted_at": datetime.now().isoformat(),
            "sender_name": meta.get("sender_name", ""),
            "sender_email": meta.get("sender_email", ""),
            "account_id": meta.get("account_id", ""),
            "who_is_this": request.form.get("who_is_this", ""),
            "importance": request.form.get("importance", "unknown"),
            "context": request.form.get("context", ""),
            "worth_surfacing": request.form.get("worth_surfacing", ""),
        }
        _save_submission(feedback_id, submission)
        return render_template("thanks.html")

    return render_template("sender_form.html", meta=meta, feedback_id=feedback_id)


@bp.route("/email/<feedback_id>", methods=["GET", "POST"])
def email_feedback(feedback_id: str):
    """Known-sender email feedback — was it worth surfacing."""
    meta = _load_meta(feedback_id)
    if not meta:
        abort(404)

    if request.method == "POST":
        submission = {
            "feedback_id": feedback_id,
            "type": "email",
            "submitted_at": datetime.now().isoformat(),
            "sender_name": meta.get("sender_name", ""),
            "sender_email": meta.get("sender_email", ""),
            "subject": meta.get("subject", ""),
            "worth_surfacing": request.form.get("worth_surfacing", ""),
            "notes": request.form.get("notes", ""),
        }
        _save_submission(feedback_id, submission)
        return render_template("thanks.html")

    return render_template("email_form.html", meta=meta, feedback_id=feedback_id)


def _load_meta(feedback_id: str) -> dict | None:
    """Load the metadata file for a feedback ID."""
    meta_path = FEEDBACK_DIR / "meta" / f"{feedback_id}.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def _save_submission(feedback_id: str, data: dict) -> None:
    """Save a feedback submission as JSON."""
    submissions_dir = FEEDBACK_DIR / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    out_path = submissions_dir / f"{feedback_id}.json"
    out_path.write_text(json.dumps(data, indent=2))
    logger.info(f"Saved feedback: {out_path}")


URL_PREFIX = "/digest-feedback"

app.register_blueprint(bp, url_prefix=URL_PREFIX)

if __name__ == "__main__":
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    (FEEDBACK_DIR / "meta").mkdir(exist_ok=True)
    (FEEDBACK_DIR / "submissions").mkdir(exist_ok=True)
    app.run(host="0.0.0.0", port=5151, debug=True)
