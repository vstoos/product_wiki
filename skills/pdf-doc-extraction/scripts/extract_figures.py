"""Extract embedded figure rasters from a PDF with redaction detection.

Walks each page's get_images() result, drops agency-logo header decorations
(logged to dropped_header_decorations[]), flags FOI (b)(4) redactions by
pixel statistics, captures page_text_verbatim (document-ordered, Tier-1-
eligible) plus nearby_text (closest-first, captioner-context only), and
writes:

  <out>/<stem>.assets/figure_pN_fM.png  - one PNG per non-redacted figure
  <out>/<stem>.figures.json             - sidecar describing every figure
                                          (atomic write via tmp + os.replace)

The sidecar carries source_pdf_sha256 + extractor_thresholds_hash so
Phase 3b (caption_figure.py) can refuse stale captioning runs.

Usage:
  python extract_figures.py --pdf <path>.pdf --out <dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF


CAPTION_PREFIX_RE = re.compile(r"^\s*(figure|fig\.|table)\s*\d+", re.IGNORECASE)


# Recognized agency directory names. Substance is the directory ABOVE one
# of these. If the path doesn't contain any of these, path inference
# returns None.
AGENCY_DIRS = {"FDA", "EMA", "HC", "PMDA", "TGA"}


def load_substance_metadata(pdf_path: Path) -> dict | None:
    """Walk parents of pdf_path looking for <substance>/metadata.json.

    Returns parsed dict on success, None if no metadata.json is found or
    parse fails.
    """
    pdf_path = Path(pdf_path).resolve()
    for parent in pdf_path.parents:
        candidate = parent / "metadata.json"
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    return None


def infer_substance(pdf_path: Path) -> tuple[str | None, str]:
    """Resolve substance name + provenance source.

    Precedence:
      1. <substance>/metadata.json::inn  -> ("<inn>", "metadata_json")
      2. Path heuristic: <substance>/<AGENCY>/file.pdf -> ("<substance>", "path_inference")
      3. Otherwise -> (None, "none")
    """
    md = load_substance_metadata(pdf_path)
    if md and isinstance(md.get("inn"), str) and md["inn"].strip():
        return md["inn"].strip(), "metadata_json"
    parts = Path(pdf_path).resolve().parts
    for i, part in enumerate(parts):
        if part in AGENCY_DIRS and i > 0:
            return parts[i - 1], "path_inference"
    return None, "none"


def is_header_decoration(
    bbox_norm: tuple[float, float, float, float],
    *,
    top_fraction: float,
    min_height: float,
) -> bool:
    """True if bbox is in the top band AND short enough to be a logo/banner.

    bbox_norm is (x0, y0, x1, y1) with all coordinates in [0, 1] relative
    to page width/height. Origin is top-left (PyMuPDF convention).
    """
    _, y0, _, y1 = bbox_norm
    height = y1 - y0
    return y0 < top_fraction and height < min_height


def is_redaction(
    image_png_bytes: bytes,
    *,
    stddev_max: float,
    mean_max: float,
    min_area_px: int,
) -> bool:
    """True if the image looks like an FOI (b)(4) gray-fill redaction.

    Computes mean + std-dev across raw pixel bytes (no PIL dep). FDA (b)(4)
    redactions are typically gray rectangles with very low variance; we
    require all of:
      - pixel area >= min_area_px (avoid flagging tiny icons)
      - per-channel std-dev < stddev_max (uniform fill)
      - per-channel mean < mean_max (not a white page-background tile)

    Uses fitz.Pixmap to decode bytes -> raw RGB samples. Non-(b)(4)
    redactions (white-fill, bordered) are NOT covered in v1 - see spec
    Non-goals section (Phase 3.2).
    """
    pix = fitz.Pixmap(image_png_bytes)
    area = pix.width * pix.height
    if area < min_area_px:
        return False
    samples = pix.samples
    if len(samples) == 0:
        return False
    total = 0
    sq = 0
    for b in samples:
        total += b
        sq += b * b
    count = len(samples)
    mean = total / count
    var = max(0.0, sq / count - mean * mean)
    stddev = var ** 0.5
    return stddev < stddev_max and mean < mean_max


def page_text_verbatim(page) -> str:
    """Return the page's full text in document order (PyMuPDF page.get_text()).

    This is the Tier-1-eligible page-text field per spec - preserves document
    order so any 15-20-word substring appears contiguously and can be
    verbatim-anchored. Distinct from nearby_text_for_bbox which reorders.
    """
    return page.get_text("text")


def nearby_text_for_bbox(
    page,
    bbox_pdf: tuple[float, float, float, float],
    *,
    max_chars: int,
) -> tuple[str, str]:
    """Return (nearby_text, raw_caption_candidate) for a figure bbox.

    Pulls ALL text blocks on the page, ranks each by minimal vertical gap
    to the figure bbox, concatenates closest-first up to max_chars.
    raw_caption_candidate is the first block matching CAPTION_PREFIX_RE
    (truncated to 200 chars).

    Output is captioner-context only - NOT Tier-1-eligible (the closest-
    first ordering means substrings may not appear contiguously on the
    source page). Use page_text_verbatim() for Tier-1 anchoring.
    """
    fy0, fy1 = bbox_pdf[1], bbox_pdf[3]
    blocks = page.get_text("blocks")
    scored: list[tuple[float, str]] = []
    candidate = ""
    for block in blocks:
        if len(block) < 5:
            continue
        by0, by1, text = block[1], block[3], block[4]
        if not isinstance(text, str) or not text.strip():
            continue
        if by1 < fy0:
            gap = fy0 - by1
        elif by0 > fy1:
            gap = by0 - fy1
        else:
            gap = 0.0  # overlapping/inside the figure region
        text_clean = text.strip()
        if not candidate and CAPTION_PREFIX_RE.match(text_clean):
            candidate = text_clean[:200]
        scored.append((gap, text_clean))
    scored.sort(key=lambda t: t[0])  # closest first
    out_parts: list[str] = []
    used = 0
    for _, text in scored:
        addition = text if not out_parts else " " + text
        if used + len(addition) > max_chars:
            remaining = max_chars - used
            if remaining > 0:
                out_parts.append(addition[:remaining])
                used = max_chars
            break
        out_parts.append(addition)
        used += len(addition)
    return "".join(out_parts), candidate


def main(argv: list[str] | None = None) -> int:
    """Stub - populated in Task 10."""
    raise NotImplementedError("main() implemented in Task 10")


if __name__ == "__main__":
    sys.exit(main())
