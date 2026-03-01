"""Remarkable annotation extraction — reads pen strokes and maps them to PDF text.

Gesture types:
  - Circle: closed curved shape → "want more of this"
  - Underline: straight horizontal stroke → remember text verbatim with source
  - Cross-out: two intersecting strokes forming an X → negative signal

Coordinate mapping:
  The Remarkable uses continuous scroll for annotated PDFs. All strokes are in
  a single .rm file. The x-axis is centered (0 = page center, range ±702).
  The y-axis starts at 0 (top) and extends downward, crossing page boundaries
  at intervals of page_height_pts * (226/72).

Requires: rmscene, pymupdf, numpy
"""

import logging
import math
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

import numpy as np
import pymupdf
from rmscene import read_blocks, SceneLineItemBlock

logger = logging.getLogger(__name__)

RM_WIDTH = 1404
RM_DPI = 226
SCALE = 72.0 / RM_DPI  # 0.3186 — converts RM pixels to PDF points

GestureType = Literal["circle", "underline", "crossout", "unknown"]


@dataclass
class Stroke:
    points: list[tuple[float, float]]
    pen_type: int = 0
    color: int = 0


@dataclass
class Annotation:
    gesture: GestureType
    text: str
    page_index: int
    source_title: str = ""
    source_domain: str = ""
    source_url: str = ""


def process_document(rm_zip_path: str, original_pdf_path: str | None = None) -> list[Annotation]:
    """Process a downloaded Remarkable document and extract annotations."""
    rm_data_list, pdf_data = _unpack_rmdoc(rm_zip_path)

    if pdf_data is None and original_pdf_path:
        pdf_data = Path(original_pdf_path).read_bytes()

    if pdf_data is None:
        logger.error("No PDF found in archive")
        return []

    if not rm_data_list:
        logger.info("No annotation files found")
        return []

    doc = pymupdf.open(stream=pdf_data, filetype="pdf")
    annotations = []

    for rm_data in rm_data_list:
        strokes = _parse_rm_strokes(rm_data)

        # Classify individual strokes, then detect crossouts from pairs
        singles = []
        for s in strokes:
            gesture = _classify_single_stroke(s)
            singles.append((s, gesture))

        # Find X-shaped crossouts: pairs of straight-ish strokes that intersect
        crossout_indices = _find_crossout_pairs(singles)

        for i, (stroke, gesture) in enumerate(singles):
            if i in crossout_indices:
                gesture = "crossout"
            if gesture == "unknown":
                continue

            ann = _extract_annotation(stroke, gesture, doc)
            if ann and ann.text.strip():
                annotations.append(ann)

    doc.close()

    # Deduplicate crossouts (both strokes of an X produce the same text region)
    annotations = _dedup_crossouts(annotations)
    return annotations


def _unpack_rmdoc(zip_path: str) -> tuple[list[bytes], bytes | None]:
    """Unpack a .rmdoc file."""
    rm_data_list: list[bytes] = []
    pdf_data: bytes | None = None

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".rm"):
                rm_data_list.append(zf.read(name))
            elif name.endswith(".pdf"):
                pdf_data = zf.read(name)

    return rm_data_list, pdf_data


def _parse_rm_strokes(rm_data: bytes) -> list[Stroke]:
    """Parse strokes from a .rm v6 file."""
    strokes = []
    try:
        for block in read_blocks(BytesIO(rm_data)):
            if not isinstance(block, SceneLineItemBlock):
                continue
            line = block.item.value
            if line is None or not line.points:
                continue
            strokes.append(Stroke(
                points=[(p.x, p.y) for p in line.points],
                pen_type=line.tool.value if hasattr(line.tool, "value") else 0,
                color=line.color.value if hasattr(line.color, "value") else 0,
            ))
    except Exception as e:
        logger.warning(f"Error parsing .rm file: {e}")
    return strokes


# ── Single-stroke classification ─────────────────────────────────────

def _classify_single_stroke(stroke: Stroke) -> GestureType:
    """Classify a stroke on its own. Crossouts are detected separately via pairs."""
    pts = stroke.points
    if len(pts) < 3:
        return "unknown"

    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])

    bbox_w = float(xs.max() - xs.min())
    bbox_h = float(ys.max() - ys.min())
    aspect = bbox_w / (bbox_h + 1e-9)

    dx, dy = np.diff(xs), np.diff(ys)
    path_len = float(np.sum(np.sqrt(dx**2 + dy**2)))
    displacement = math.sqrt((xs[-1] - xs[0])**2 + (ys[-1] - ys[0])**2)
    straightness = displacement / (path_len + 1e-9)

    bbox_diag = math.sqrt(bbox_w**2 + bbox_h**2)
    closure = 1.0 - (displacement / (bbox_diag + 1e-9))

    # Circle: closed, non-straight shape
    if closure > 0.55 and straightness < 0.5 and aspect < 4.0:
        return "circle"

    # Underline: any straight-ish, wide stroke
    if straightness > 0.70 and aspect > 3:
        return "underline"

    return "unknown"


# ── Crossout detection (two intersecting strokes) ────────────────────

def _find_crossout_pairs(singles: list[tuple[Stroke, GestureType]]) -> set[int]:
    """Find pairs of strokes that form an X (crossout).

    Two strokes are an X if:
      1. Both are straight-ish (not circles/scribbles)
      2. Their bounding boxes overlap significantly
      3. Their line segments actually intersect
    """
    crossout_indices: set[int] = set()

    for i in range(len(singles)):
        for j in range(i + 1, len(singles)):
            s_i, g_i = singles[i]
            s_j, g_j = singles[j]

            # Both must be straight-ish strokes (underline or unknown with some length)
            if not _is_straight(s_i) or not _is_straight(s_j):
                continue

            # Bounding boxes must overlap
            if not _bboxes_overlap(s_i, s_j):
                continue

            # The line segments (start→end) must intersect
            if _segments_intersect(s_i, s_j):
                crossout_indices.add(i)
                crossout_indices.add(j)

    return crossout_indices


def _is_straight(stroke: Stroke) -> bool:
    """Check if a stroke is roughly a straight line."""
    if len(stroke.points) < 2:
        return False
    xs = np.array([p[0] for p in stroke.points])
    ys = np.array([p[1] for p in stroke.points])
    dx, dy = np.diff(xs), np.diff(ys)
    path_len = float(np.sum(np.sqrt(dx**2 + dy**2)))
    displacement = math.sqrt((xs[-1] - xs[0])**2 + (ys[-1] - ys[0])**2)
    return displacement / (path_len + 1e-9) > 0.60


def _bboxes_overlap(a: Stroke, b: Stroke) -> bool:
    """Check if two strokes' bounding boxes overlap."""
    a_xs = [p[0] for p in a.points]
    a_ys = [p[1] for p in a.points]
    b_xs = [p[0] for p in b.points]
    b_ys = [p[1] for p in b.points]

    return not (max(a_xs) < min(b_xs) or max(b_xs) < min(a_xs) or
                max(a_ys) < min(b_ys) or max(b_ys) < min(a_ys))


def _segments_intersect(a: Stroke, b: Stroke) -> bool:
    """Check if the line segments (start→end) of two strokes intersect.

    Uses the cross-product orientation method.
    """
    p1 = a.points[0]
    p2 = a.points[-1]
    p3 = b.points[0]
    p4 = b.points[-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    return False


def _dedup_crossouts(annotations: list[Annotation]) -> list[Annotation]:
    """Both strokes of an X produce annotations over the same region. Merge them."""
    deduped = []
    crossouts: list[Annotation] = []
    for ann in annotations:
        if ann.gesture == "crossout":
            # Check if we already have a crossout on the same page with overlapping words
            merged = False
            for existing in crossouts:
                if existing.page_index == ann.page_index:
                    words_a = set(existing.text.split())
                    words_b = set(ann.text.split())
                    overlap = len(words_a & words_b)
                    if overlap >= min(len(words_a), len(words_b)) * 0.5:
                        # Merge: use the intersection of words (tighter text)
                        common = words_a & words_b
                        # Preserve word order from the longer text
                        source = existing.text if len(existing.text) >= len(ann.text) else ann.text
                        existing.text = " ".join(w for w in source.split() if w in common)
                        merged = True
                        break
            if not merged:
                crossouts.append(ann)
                deduped.append(ann)
        else:
            deduped.append(ann)
    return deduped


# ── Coordinate mapping + text extraction ─────────────────────────────

def _extract_annotation(
    stroke: Stroke,
    gesture: GestureType,
    doc: pymupdf.Document,
) -> Annotation | None:
    """Map stroke to PDF coordinates and extract the text it covers."""
    xs = [p[0] for p in stroke.points]
    ys = [p[1] for p in stroke.points]
    mean_y = sum(ys) / len(ys)

    # Determine which page this stroke is on
    page_idx = 0
    rm_y_offset = 0.0
    for i in range(len(doc)):
        page_h_rm = doc.load_page(i).rect.height / SCALE
        if mean_y < rm_y_offset + page_h_rm:
            page_idx = i
            break
        rm_y_offset += page_h_rm
    else:
        page_idx = len(doc) - 1
        rm_y_offset = sum(doc.load_page(i).rect.height / SCALE for i in range(len(doc) - 1))

    page = doc.load_page(page_idx)

    # X offset to center RM canvas on the PDF page
    offset_x = (page.rect.width - RM_WIDTH * SCALE) / 2

    # Convert to PDF coordinates
    x0 = (min(xs) + RM_WIDTH / 2) * SCALE + offset_x
    x1 = (max(xs) + RM_WIDTH / 2) * SCALE + offset_x
    y0 = (min(ys) - rm_y_offset) * SCALE
    y1 = (max(ys) - rm_y_offset) * SCALE

    # Build search rectangle
    pad = 3
    if gesture == "underline":
        # Underline sits below text — search upward to capture the text line
        search_rect = pymupdf.Rect(x0 - pad, y0 - 22, x1 + pad, y1 + pad)
    elif gesture == "circle":
        # Circle encloses text — slight inward margin
        search_rect = pymupdf.Rect(x0 + pad, y0 + pad, x1 - pad, y1 - pad)
    else:
        # Crossout goes through text
        search_rect = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    words = [
        w for w in page.get_text("words")
        if pymupdf.Rect(w[:4]).intersects(search_rect)
    ]
    words.sort(key=lambda w: (w[1], w[0]))
    text = " ".join(w[4] for w in words)

    return Annotation(
        gesture=gesture,
        text=text,
        page_index=page_idx,
    )
