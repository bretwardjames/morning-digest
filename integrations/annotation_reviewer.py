"""Annotation reviewer — downloads Remarkable documents, extracts pen annotations,
and stores them as ragtime signals.

Gesture mapping:
  - Circle: "I want more content like this" → preference signal
  - Underline: "Remember this verbatim" → stored with source attribution
  - Cross-out: "Less of this" → negative preference signal
"""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from integrations.annotations import Annotation, process_document
from integrations.ragtime import RagtimeClient
from integrations.remarkable import RemarkableClient

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
ANNOTATIONS_DIR = Path("data/annotations")


def review_annotations(config: dict, ragtime: RagtimeClient, target_date: str) -> list[Annotation]:
    """Download documents from Remarkable archive, extract and store annotations.

    Args:
        config: App config
        ragtime: Ragtime client
        target_date: Date string (YYYY-MM-DD) to review

    Returns:
        List of all extracted annotations
    """
    # Skip if already processed
    record_path = ANNOTATIONS_DIR / f"{target_date}.json"
    if record_path.exists():
        logger.info(f"Annotations for {target_date} already processed")
        return _load_annotation_record(target_date)

    rm_config = config.get("delivery", {}).get("remarkable", {})
    if not rm_config.get("enabled", False):
        logger.info("Remarkable not enabled, skipping annotation review")
        return []

    rm = RemarkableClient(rmapi_path=rm_config.get("rmapi_path", "rmapi"))
    folder = rm_config.get("folder", "/Morning Digest")
    archive_folder = f"{folder}/Archive/{target_date}"

    # Load the manifest for this date to get source metadata
    manifest = _load_manifest(target_date)

    # List documents in the archive folder
    try:
        files = rm.list_files(archive_folder)
    except Exception as e:
        logger.warning(f"Could not list archive folder {archive_folder}: {e}")
        return []

    if not files:
        logger.info(f"No files in {archive_folder}")
        return []

    all_annotations = []
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    for filename in files:
        fname = filename.strip()
        if fname.endswith("/") or not fname:
            continue

        doc_path = f"{archive_folder}/{fname}"
        logger.info(f"Downloading {doc_path} for annotation extraction")

        with tempfile.TemporaryDirectory() as tmpdir:
            rmdoc_path = _download_document(rm, doc_path, tmpdir)
            if not rmdoc_path:
                continue

            annotations = process_document(rmdoc_path)

            # Enrich annotations with source metadata from the manifest
            source_meta = _find_source_meta(fname, manifest)
            for ann in annotations:
                ann.source_title = source_meta.get("title", fname)
                ann.source_domain = source_meta.get("source_domain", "")
                ann.source_url = source_meta.get("url", "")

            # Store each annotation in ragtime
            for ann in annotations:
                _store_annotation_signal(ann, ragtime)

            all_annotations.extend(annotations)

    # Save annotation record
    if all_annotations:
        _save_annotation_record(target_date, all_annotations)

    return all_annotations


def _download_document(rm: RemarkableClient, doc_path: str, tmpdir: str) -> str | None:
    """Download a document from Remarkable as a .rmdoc file.

    rmapi get downloads to the current working directory, so we cd to tmpdir.
    """
    # rmapi get outputs a .rmdoc file in the current directory
    result = rm._run(["get", doc_path], capture=True)
    if result is None or result.returncode != 0:
        logger.warning(f"Failed to download {doc_path}")
        return None

    # Find the .rmdoc file that was downloaded (in cwd)
    cwd = Path(".")
    rmdoc_files = list(cwd.glob("*.rmdoc"))
    if not rmdoc_files:
        # Try zip extension too
        rmdoc_files = list(cwd.glob("*.zip"))

    if rmdoc_files:
        # Move the most recent one to tmpdir
        rmdoc = max(rmdoc_files, key=lambda f: f.stat().st_mtime)
        dest = Path(tmpdir) / rmdoc.name
        shutil.move(str(rmdoc), str(dest))
        return str(dest)

    logger.warning(f"Could not find downloaded file for {doc_path}")
    return None


def _find_source_meta(filename: str, manifest: dict | None) -> dict:
    """Find the source metadata for a document by matching filename."""
    if not manifest:
        return {}

    clean = filename.strip()

    for article in manifest.get("articles", []):
        pdf_name = article.get("pdf_filename", "").replace(".pdf", "")
        if pdf_name and pdf_name in clean:
            return article

    for email in manifest.get("emails_sent", []):
        pdf_name = email.get("pdf_filename", "").replace(".pdf", "")
        if pdf_name and pdf_name in clean:
            return {
                "title": email.get("subject", ""),
                "source_domain": email.get("sender_email", ""),
                "url": "",
            }

    return {}


def _store_annotation_signal(ann: Annotation, ragtime: RagtimeClient) -> None:
    """Store an annotation as the appropriate ragtime signal."""
    source_label = f"'{ann.source_title}'"
    if ann.source_domain:
        source_label += f" ({ann.source_domain})"
    if ann.source_url:
        source_label += f" [{ann.source_url}]"

    if ann.gesture == "circle":
        ragtime.remember(
            f"WANT MORE: User circled text in {source_label}: "
            f'"{ann.text}". Strong interest in this type of content.',
            type="preference", component="articles",
        )
    elif ann.gesture == "underline":
        ragtime.remember(
            f"HIGHLIGHT: User underlined in {source_label}: "
            f'"{ann.text}". Remember this verbatim.',
            type="context", component="articles",
        )
    elif ann.gesture == "crossout":
        ragtime.remember(
            f"LESS OF THIS: User crossed out text in {source_label}: "
            f'"{ann.text}". Negative signal — reduce similar content.',
            type="preference", component="articles",
        )


def _load_manifest(date: str) -> dict | None:
    path = RUNS_DIR / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_annotation_record(date: str, annotations: list[Annotation]) -> None:
    record = {
        "date": date,
        "annotations": [
            {
                "gesture": a.gesture,
                "text": a.text,
                "page_index": a.page_index,
                "source_title": a.source_title,
                "source_domain": a.source_domain,
                "source_url": a.source_url,
            }
            for a in annotations
        ],
    }
    path = ANNOTATIONS_DIR / f"{date}.json"
    path.write_text(json.dumps(record, indent=2))
    logger.info(f"Saved {len(annotations)} annotations to {path}")


def _load_annotation_record(date: str) -> list[Annotation]:
    path = ANNOTATIONS_DIR / f"{date}.json"
    if not path.exists():
        return []
    record = json.loads(path.read_text())
    return [
        Annotation(
            gesture=a["gesture"],
            text=a["text"],
            page_index=a["page_index"],
            source_title=a.get("source_title", ""),
            source_domain=a.get("source_domain", ""),
            source_url=a.get("source_url", ""),
        )
        for a in record.get("annotations", [])
    ]
