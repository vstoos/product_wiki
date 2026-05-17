"""Phase 4 - assemble <stem>.hybrid.md from Phase 1/2/3 sidecars.

Reads:
  <out>/<stem>.md            (Phase 1 PyMuPDF text, with <!-- page: N --> markers)
  <out>/<stem>.extract.json  (Phase 1 metadata: page_count, problem_pages)
  <out>/<stem>.ocr.json      (Phase 2, optional)
  <out>/<stem>.figures.json  (Phase 3, optional - captioned in place by Phase 3b)

Writes:
  <out>/<stem>.hybrid.md       primary output - anchored markdown
  <out>/<stem>.assembly.json   ALCOA metadata: which sidecars used, page-source counts, timing

Usage:
  python assemble_md.py --pdf <path>.pdf --out <dir>
"""
from __future__ import annotations

# Reuse atomic_write_json from the shared vision-backends module so all
# sidecar writes in this skill go through the same tmp+rename codepath.
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
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
ASSEMBLER_VERSION = "assemble_md.py@2026-05-17"

# Page marker emitted by extract_text.py: <!-- page: N -->
PAGE_MARKER_RE = re.compile(r"^<!--\s*page:\s*(\d+)\s*-->\s*$", re.MULTILINE)
# Problem-page comment we strip from parsed bodies (we re-emit our own).
PROBLEM_PAGE_COMMENT_RE = re.compile(r"<!--\s*problem-page:[^>]*-->\s*\n?")
# YAML frontmatter delimiter.
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Parsing Phase 1 .md
# ---------------------------------------------------------------------------

def parse_phase1_md(md_text: str) -> dict[int, str]:
    """Split a Phase 1 <stem>.md into {page_number: body, ...}.

    Strips:
      - YAML frontmatter (if present)
      - Inline <!-- problem-page: ... --> comments (we re-emit based on
        current OCR state).

    Returns bodies stripped of leading/trailing whitespace.
    """
    # Strip YAML frontmatter
    body = FRONTMATTER_RE.sub("", md_text, count=1)

    # Find all page markers with their match positions
    matches = list(PAGE_MARKER_RE.finditer(body))
    if not matches:
        return {}

    pages: dict[int, str] = {}
    for i, m in enumerate(matches):
        pn = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end]
        # Drop the inline problem-page comment if present
        chunk = PROBLEM_PAGE_COMMENT_RE.sub("", chunk)
        pages[pn] = chunk.strip()
    return pages


# ---------------------------------------------------------------------------
# Per-page body selection (OCR vs PyMuPDF)
# ---------------------------------------------------------------------------

def select_page_body(
    *,
    page_number: int,
    pymupdf_text: str,
    is_problem: bool,
    ocr_entry: dict[str, Any] | None,
) -> tuple[str, str]:
    """Pick the best body for a page. Returns (body, source_label).

    source_label is one of: pymupdf_clean, ocr_ok, ocr_failed, ocr_not_run.

    Rules:
      - clean page (not in problem_pages)        -> pymupdf_clean
      - problem page + ocr_entry.status == ok    -> ocr_ok  (REPLACES pymupdf)
      - problem page + ocr_entry.status == error -> ocr_failed (annotate + keep pymupdf)
      - problem page + ocr_entry is None         -> ocr_not_run (annotate + keep pymupdf)
    """
    if not is_problem:
        return pymupdf_text, "pymupdf_clean"

    if ocr_entry is not None and ocr_entry.get("status") == "ok":
        return ocr_entry.get("text", ""), "ocr_ok"

    if ocr_entry is not None:
        err = ocr_entry.get("error", "unknown error")
        body = f"<!-- ocr-failed: {err} -->\n{pymupdf_text}".rstrip()
        return body, "ocr_failed"

    body = f"<!-- problem-page: low text density, OCR not run -->\n{pymupdf_text}".rstrip()
    return body, "ocr_not_run"


# ---------------------------------------------------------------------------
# Figure block rendering
# ---------------------------------------------------------------------------

def render_figure_block(entry: dict[str, Any]) -> str:
    """Render one figure entry from <stem>.figures.json as a markdown block.

    Five cases, switched on content_type + redacted:
      - "redaction"            -> heading + > *[REDACTED: (b)(4)]*  (no image)
      - "table"                -> ### Table heading + image + raw HTML description
      - "error"                -> ### Figure heading + image + > *Caption error*: ...
      - "figure" + description -> ### Figure heading + image + > *Caption*: description
      - default (uncaptioned)  -> ### Figure heading + image only
    """
    fid = entry["figure_id"]
    content_type = entry.get("content_type")
    redacted = entry.get("redacted", False)
    raw_caption = (entry.get("raw_caption_candidate") or "").strip()
    description = entry.get("description")
    asset_path = entry.get("asset_path")
    error = entry.get("error")

    # Redactions: no image, no asset_path
    if content_type == "redaction" or redacted:
        return f"### Figure {fid}\n\n> *{description or '[REDACTED: (b)(4)]'}*"

    # Table: caption-style heading, image, raw description as HTML
    if content_type == "table":
        return (
            f"### Table {fid}\n\n"
            f"![Table {fid}]({asset_path})\n\n"
            f"{description or ''}".rstrip()
        )

    # Common figure heading (with optional inline caption suffix)
    if raw_caption:
        heading = f"### Figure {fid} — {raw_caption}"
    else:
        heading = f"### Figure {fid}"

    image_line = f"![Figure {fid}]({asset_path})" if asset_path else ""

    parts = [heading, "", image_line] if image_line else [heading]

    # Error: special blockquote
    if content_type == "error":
        parts.extend(["", f"> *Caption error*: {error or 'unknown error'}"])
        return "\n".join(parts)

    # Captioned figure: > *Caption*: description
    if description:
        parts.extend(["", f"> *Caption*: {description}"])
        return "\n".join(parts)

    # Uncaptioned (no description, no error): heading + image only
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sidecar discovery
# ---------------------------------------------------------------------------

def discover_sidecars(
    *,
    pdf: Path,
    out_dir: Path,
    md_path: Path | None = None,
    extract_json_path: Path | None = None,
    ocr_json_path: Path | None = None,
    figures_json_path: Path | None = None,
) -> dict[str, Path | None]:
    """Resolve the four sidecar paths. Required: md, extract_json.

    Raises FileNotFoundError if a required sidecar is missing.
    Returns None for missing optional sidecars (ocr_json, figures_json).
    """
    stem = pdf.stem
    md = md_path if md_path is not None else out_dir / f"{stem}.md"
    ej = extract_json_path if extract_json_path is not None else out_dir / f"{stem}.extract.json"
    oj = ocr_json_path if ocr_json_path is not None else out_dir / f"{stem}.ocr.json"
    fj = figures_json_path if figures_json_path is not None else out_dir / f"{stem}.figures.json"

    missing = [p for p in (md, ej) if not p.exists()]
    if missing:
        names = ", ".join(p.name for p in missing)
        raise FileNotFoundError(f"required sidecar(s) missing: {names}")

    return {
        "md": md,
        "extract_json": ej,
        "ocr_json": oj if oj.exists() else None,
        "figures_json": fj if fj.exists() else None,
    }


# ---------------------------------------------------------------------------
# Assemble - end-to-end (no disk I/O)
# ---------------------------------------------------------------------------

@dataclass
class AssemblyResult:
    hybrid_md: str
    page_sources: dict[str, int]
    figure_counts: dict[str, int]


def _classify_figure(entry: dict[str, Any]) -> str:
    """Return one of: captioned, uncaptioned, redacted, errored."""
    if entry.get("redacted") or entry.get("content_type") == "redaction":
        return "redacted"
    if entry.get("content_type") == "error":
        return "errored"
    if entry.get("description"):
        return "captioned"
    return "uncaptioned"


def assemble(
    *,
    stem: str,
    source_pdf_name: str,
    source_pdf_sha256: str | None,
    phase1_md_text: str,
    extract_metadata: dict[str, Any],
    ocr_data: dict[str, Any] | None,
    figures_data: dict[str, Any] | None,
) -> AssemblyResult:
    """Build the .hybrid.md text and computed counts. No disk I/O."""
    page_count = int(extract_metadata.get("page_count", 0))
    problem_pages = set(int(p) for p in extract_metadata.get("problem_pages", []))

    pymupdf_bodies = parse_phase1_md(phase1_md_text)

    # Index OCR pages by page_number
    ocr_by_pn: dict[int, dict[str, Any]] = {}
    if ocr_data is not None:
        for p in ocr_data.get("pages", []):
            ocr_by_pn[int(p["page_number"])] = p

    # Index figures by page_number, then sort each list by page_index_within
    figs_by_pn: dict[int, list[dict[str, Any]]] = {}
    figure_total = 0
    figure_counts = {
        "total": 0,
        "captioned": 0,
        "uncaptioned": 0,
        "redacted": 0,
        "errored": 0,
    }
    if figures_data is not None:
        for f in figures_data.get("figures", []):
            pn = int(f["page_number"])
            figs_by_pn.setdefault(pn, []).append(f)
            figure_total += 1
            cls = _classify_figure(f)
            figure_counts[cls] += 1
        figure_counts["total"] = figure_total
        for pn in figs_by_pn:
            figs_by_pn[pn].sort(key=lambda f: int(f.get("page_index_within", 0)))

    page_sources = {
        "pymupdf_clean": 0,
        "ocr_ok": 0,
        "ocr_failed": 0,
        "ocr_not_run": 0,
    }

    page_blocks: list[str] = []
    for pn in range(1, page_count + 1):
        body, source = select_page_body(
            page_number=pn,
            pymupdf_text=pymupdf_bodies.get(pn, ""),
            is_problem=pn in problem_pages,
            ocr_entry=ocr_by_pn.get(pn),
        )
        page_sources[source] += 1

        block_lines = [f'<a id="p{pn}"></a>', f"## Page {pn}", ""]
        if body:
            block_lines.append(body)
        for fig in figs_by_pn.get(pn, []):
            block_lines.append("")
            block_lines.append(render_figure_block(fig))
        page_blocks.append("\n".join(block_lines))

    assembled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha_suffix = f", source_pdf_sha256={source_pdf_sha256}" if source_pdf_sha256 else ""
    header = (
        f"<!-- doc_meta: pages={page_count}, "
        f"ocr_pages={page_sources['ocr_ok']}, "
        f"figure_count={figure_counts['total']}, "
        f"source_pdf={source_pdf_name}{sha_suffix}, "
        f"assembled_at={assembled_at} -->"
    )

    hybrid_md = header + "\n\n" + "\n\n".join(page_blocks) + "\n"
    return AssemblyResult(
        hybrid_md=hybrid_md,
        page_sources=page_sources,
        figure_counts=figure_counts,
    )


# ---------------------------------------------------------------------------
# sha256 lookup (no PDF re-hashing here - that's Phase 1/3's job)
# ---------------------------------------------------------------------------

def lookup_source_sha256(
    *,
    figures_data: dict[str, Any] | None,
    pdf: Path,
) -> str | None:
    """Return source_pdf_sha256 if available cheaply, else None.

    Order:
      1. figures.json::source_pdf_sha256 (already computed by Phase 3a)
      2. <stem>.pdf.meta.json::sha256 or <stem>.meta.json::sha256
      3. None (we do NOT re-hash the PDF in Phase 4)
    """
    if figures_data is not None:
        sha = figures_data.get("source_pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    for candidate in (
        pdf.with_suffix(pdf.suffix + ".meta.json"),
        pdf.with_suffix(".meta.json"),
    ):
        if candidate.is_file():
            try:
                meta = json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sha = meta.get("sha256")
            if isinstance(sha, str) and len(sha) == 64:
                return sha
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4 - assemble Phase 1/2/3 sidecars into <stem>.hybrid.md."
    )
    parser.add_argument("--pdf", type=Path, required=True,
                        help="Input PDF (used for stem + sidecar lookup; never opened)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output dir; sidecars are auto-discovered here")
    parser.add_argument("--md", type=Path, default=None,
                        help="Override Phase 1 .md path")
    parser.add_argument("--extract-json", type=Path, default=None,
                        help="Override Phase 1 .extract.json path")
    parser.add_argument("--ocr-json", type=Path, default=None,
                        help="Override Phase 2 .ocr.json path")
    parser.add_argument("--figures-json", type=Path, default=None,
                        help="Override Phase 3 .figures.json path")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing <stem>.hybrid.md")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.pdf.stem
    hybrid_path = args.out / f"{stem}.hybrid.md"
    assembly_path = args.out / f"{stem}.assembly.json"

    if hybrid_path.exists() and not args.force:
        if not args.quiet:
            print(json.dumps({
                "hybrid_md": str(hybrid_path),
                "status": "skipped:already_exists",
                "hint": "pass --force to re-assemble",
            }, indent=2))
        return 0

    try:
        sidecars = discover_sidecars(
            pdf=args.pdf,
            out_dir=args.out,
            md_path=args.md,
            extract_json_path=args.extract_json,
            ocr_json_path=args.ocr_json,
            figures_json_path=args.figures_json,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    phase1_md_text = sidecars["md"].read_text(encoding="utf-8")
    extract_meta = json.loads(sidecars["extract_json"].read_text(encoding="utf-8"))
    ocr_data = (
        json.loads(sidecars["ocr_json"].read_text(encoding="utf-8"))
        if sidecars["ocr_json"] is not None else None
    )
    figures_data = (
        json.loads(sidecars["figures_json"].read_text(encoding="utf-8"))
        if sidecars["figures_json"] is not None else None
    )
    source_sha = lookup_source_sha256(figures_data=figures_data, pdf=args.pdf)

    t0 = time.monotonic()
    result = assemble(
        stem=stem,
        source_pdf_name=args.pdf.name,
        source_pdf_sha256=source_sha,
        phase1_md_text=phase1_md_text,
        extract_metadata=extract_meta,
        ocr_data=ocr_data,
        figures_data=figures_data,
    )
    assembly_seconds = round(time.monotonic() - t0, 3)

    hybrid_path.write_text(result.hybrid_md, encoding="utf-8")

    assembly_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_file": args.pdf.name,
        "source_pdf_sha256": source_sha,
        "assembly_date": _utc_now_iso(),
        "assembler_version": ASSEMBLER_VERSION,
        "page_count": int(extract_meta.get("page_count", 0)),
        "page_sources": result.page_sources,
        "figure_counts": result.figure_counts,
        "inputs": {
            "md": sidecars["md"].name,
            "extract_json": sidecars["extract_json"].name,
            "ocr_json": sidecars["ocr_json"].name if sidecars["ocr_json"] else None,
            "figures_json": sidecars["figures_json"].name if sidecars["figures_json"] else None,
        },
        "output": {
            "hybrid_md": hybrid_path.name,
            "size_bytes": hybrid_path.stat().st_size,
        },
        "assembly_seconds": assembly_seconds,
    }
    atomic_write_json(assembly_path, assembly_payload)

    if not args.quiet:
        summary = {
            "hybrid_md": str(hybrid_path),
            "pdf": str(args.pdf),
            "page_count": int(extract_meta.get("page_count", 0)),
            "page_sources": result.page_sources,
            "figure_counts": result.figure_counts,
            "assembly_seconds": assembly_seconds,
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
