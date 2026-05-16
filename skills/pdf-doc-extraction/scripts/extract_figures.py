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

# Re-export from the shared vision backends module (same pattern as ocr_page.py).
import importlib.util as _ilu
from pathlib import Path as _Path
import sys as _sys

_vb_path = _Path(__file__).resolve().parent / "_vision_backends.py"
_vb_spec = _ilu.spec_from_file_location("_vision_backends", _vb_path)
_vision_backends = _ilu.module_from_spec(_vb_spec)
_sys.modules["_vision_backends"] = _vision_backends
_vb_spec.loader.exec_module(_vision_backends)

atomic_write_json = _vision_backends.atomic_write_json

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
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


def extract_figures_from_page(
    doc,
    page_index_zero: int,
    *,
    header_fraction: float,
    header_min_height: float,
    redaction_thresholds: tuple[float, float],
    min_area_px: int,
    nearby_text_max_chars: int,
) -> tuple[list[dict], list[dict]]:
    """Return (figures, dropped_header_decorations) for one page.

    Each figure dict carries:
      page_number, page_index_within, bbox_normalized, image_bytes,
      raw_caption_candidate, nearby_text, page_text_verbatim, redacted,
      width_px, height_px, size_bytes, extraction_method

    page_text_verbatim is computed once per page and shared across every
    figure on that page (caller deduplicates).

    Caller is responsible for writing PNGs and computing asset_sha256.
    """
    page = doc[page_index_zero]
    page_w = page.rect.width
    page_h = page.rect.height
    stddev_max, mean_max = redaction_thresholds
    page_text = page_text_verbatim(page)

    figures: list[dict] = []
    dropped: list[dict] = []
    image_index = 0

    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            bbox = page.get_image_bbox(img_info)
        except (ValueError, RuntimeError):
            continue
        if bbox.is_empty:
            continue
        bbox_norm = (
            bbox.x0 / page_w,
            bbox.y0 / page_h,
            bbox.x1 / page_w,
            bbox.y1 / page_h,
        )
        # Render to PNG once for both header check (size_bytes for audit log)
        # and for the figure entry itself.
        try:
            pix = fitz.Pixmap(doc, xref)
            png_bytes = pix.tobytes("png")
        except Exception:  # noqa: BLE001 - skip uncroppable images
            continue

        if is_header_decoration(
            bbox_norm, top_fraction=header_fraction, min_height=header_min_height
        ):
            dropped.append({
                "page_number": page_index_zero + 1,
                "bbox_normalized": [round(v, 4) for v in bbox_norm],
                "size_bytes": len(png_bytes),
                "reason": "header_band",
            })
            continue

        redacted = is_redaction(
            png_bytes,
            stddev_max=stddev_max,
            mean_max=mean_max,
            min_area_px=min_area_px,
        )
        nearby, candidate = nearby_text_for_bbox(
            page,
            (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            max_chars=nearby_text_max_chars,
        )
        image_index += 1
        figures.append({
            "page_number": page_index_zero + 1,
            "page_index_within": image_index,
            "bbox_normalized": [round(v, 4) for v in bbox_norm],
            "image_bytes": png_bytes,
            "raw_caption_candidate": candidate,
            "nearby_text": nearby,
            "page_text_verbatim": page_text,
            "redacted": redacted,
            "width_px": pix.width,
            "height_px": pix.height,
            "size_bytes": len(png_bytes),
            "extraction_method": "native_extract_image",
        })

    return figures, dropped


def hash_thresholds(thresholds: dict) -> str:
    """SHA-256 hex of a JSON-canonical thresholds dict (key-order invariant)."""
    canon = json.dumps(thresholds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


def compute_pdf_sha256(pdf_path: Path) -> str:
    """Prefer <stem>.meta.json::sha256 if present (cheap); else hash the PDF."""
    pdf_path = Path(pdf_path)
    # Phase 1's convention is unclear: try both <stem>.pdf.meta.json AND
    # <stem>.meta.json (stripping .pdf). Order matches the more-specific name first.
    candidates = [
        pdf_path.with_suffix(pdf_path.suffix + ".meta.json"),
        pdf_path.with_suffix(".meta.json"),
    ]
    for c in candidates:
        if c.is_file():
            try:
                meta_obj = json.loads(c.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sha = meta_obj.get("sha256")
            if isinstance(sha, str) and len(sha) == 64:
                return sha
    h = hashlib.sha256()
    with pdf_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_figure_assets(figures: list[dict], assets_dir: Path) -> list[dict]:
    """Write non-redacted PNGs to assets_dir and return enriched JSON-safe dicts.

    Returns a new list with image_bytes stripped and these fields populated:
      - figure_id: pN_fM
      - asset_path: <assets_dir.name>/figure_pN_fM.png (or None if redacted)
      - asset_sha256: sha256 of the PNG bytes (or None if redacted)
      - raw_caption_candidate_tier: 1
      - page_text_verbatim_tier: 1
      - nearby_text_tier: None (captioner-context only)
      - captioner / description / content_type / description_tier: pre-filled
        for redactions, None otherwise (captioner fills in later).
      - prompt_hash: None
      - error: None

    Filenames: figure_pN_fM.png.
    """
    assets_dir = Path(assets_dir)
    has_real = any(not f.get("redacted") for f in figures)
    if has_real:
        assets_dir.mkdir(parents=True, exist_ok=True)

    out: list[dict] = []
    for f in figures:
        entry = {k: v for k, v in f.items() if k != "image_bytes"}
        entry["figure_id"] = f"p{f['page_number']}_f{f['page_index_within']}"
        # Tier markers per the spec sentinel convention
        entry["raw_caption_candidate_tier"] = 1
        entry["page_text_verbatim_tier"] = 1
        entry["nearby_text_tier"] = None
        entry["prompt_hash"] = None
        entry["error"] = None

        if f.get("redacted"):
            entry["asset_path"] = None
            entry["asset_sha256"] = None
            entry["captioner"] = "skipped:redacted"
            entry["description"] = "[REDACTED: (b)(4)]"
            entry["content_type"] = "redaction"
            entry["description_tier"] = None
        else:
            fname = f"figure_p{f['page_number']}_f{f['page_index_within']}.png"
            (assets_dir / fname).write_bytes(f["image_bytes"])
            entry["asset_path"] = f"{assets_dir.name}/{fname}"
            entry["asset_sha256"] = hashlib.sha256(f["image_bytes"]).hexdigest()
            entry["captioner"] = None
            entry["description"] = None
            entry["content_type"] = None
            entry["description_tier"] = None  # captioner sets to 2 on success
        out.append(entry)
    return out


SCHEMA_VERSION = "1.0"
EXTRACTOR_VERSION = "extract_figures.py@2026-05-15"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract figure rasters from a PDF (Phase 3a).",
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="Output dir; <stem>.figures.json + <stem>.assets/ written here")
    parser.add_argument("--header-fraction", type=float, default=0.15)
    parser.add_argument("--header-min-height", type=float, default=0.08)
    parser.add_argument("--redaction-stddev", type=float, default=15.0)
    parser.add_argument("--redaction-mean-max", type=float, default=245.0)
    parser.add_argument("--min-area-px", type=int, default=400)
    parser.add_argument("--nearby-text-max-chars", type=int, default=2500)
    parser.add_argument("--force", action="store_true",
                        help="Rewrite existing figures.json + assets")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / f"{args.pdf.stem}.figures.json"
    assets_dir = args.out / f"{args.pdf.stem}.assets"

    if json_path.exists() and not args.force:
        if not args.quiet:
            print(json.dumps({
                "figures_json": str(json_path),
                "status": "skipped:already_exists",
                "hint": "pass --force to re-extract",
            }, indent=2))
        return 0

    thresholds = {
        "header_fraction": args.header_fraction,
        "header_min_height": args.header_min_height,
        "redaction_stddev": args.redaction_stddev,
        "redaction_mean_max": args.redaction_mean_max,
        "min_area_px": args.min_area_px,
        "nearby_text_max_chars": args.nearby_text_max_chars,
    }
    thresholds_hash = hash_thresholds(thresholds)
    pdf_sha = compute_pdf_sha256(args.pdf)
    substance, substance_source = infer_substance(args.pdf)

    all_figures: list[dict] = []
    all_dropped: list[dict] = []
    redacted_count = 0
    with fitz.open(args.pdf) as doc:
        page_count = doc.page_count
        for i in range(page_count):
            page_figs, page_dropped = extract_figures_from_page(
                doc, i,
                header_fraction=args.header_fraction,
                header_min_height=args.header_min_height,
                redaction_thresholds=(args.redaction_stddev, args.redaction_mean_max),
                min_area_px=args.min_area_px,
                nearby_text_max_chars=args.nearby_text_max_chars,
            )
            for f in page_figs:
                if f.get("redacted"):
                    redacted_count += 1
            all_figures.extend(page_figs)
            all_dropped.extend(page_dropped)

    enriched = write_figure_assets(all_figures, assets_dir)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_file": args.pdf.name,
        "source_pdf_sha256": pdf_sha,
        "extraction_date": _utc_now_iso(),
        "extractor_version": EXTRACTOR_VERSION,
        "extractor_thresholds": thresholds,
        "extractor_thresholds_hash": thresholds_hash,
        "substance": substance,
        "substance_source": substance_source,
        "page_count": page_count,
        "figure_count": len(enriched),
        "redacted_count": redacted_count,
        "dropped_header_decorations": all_dropped,
        "captioning_date": None,
        "captioning_engine": None,
        "captioning_seconds": None,
        "figures": enriched,
    }
    atomic_write_json(json_path, payload)

    if not args.quiet:
        print(json.dumps({
            "figures_json": str(json_path),
            "pdf": str(args.pdf),
            "page_count": page_count,
            "figure_count": len(enriched),
            "redacted_count": redacted_count,
            "dropped_header_decorations_count": len(all_dropped),
            "substance": substance,
            "substance_source": substance_source,
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
