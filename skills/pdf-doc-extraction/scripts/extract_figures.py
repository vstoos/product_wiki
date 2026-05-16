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
import sys
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF


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


def main(argv: list[str] | None = None) -> int:
    """Stub - populated in Task 10."""
    raise NotImplementedError("main() implemented in Task 10")


if __name__ == "__main__":
    sys.exit(main())
