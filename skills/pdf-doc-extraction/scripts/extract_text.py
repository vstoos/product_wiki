"""Extract per-page text from a PDF using PyMuPDF.

Output:
  <out>/<stem>.md            — YAML frontmatter + per-page <!-- page: N --> markers + text
  <out>/<stem>.extract.json  — extraction metadata (pages, problem_pages, engine, timing)

Usage:
  python extract_text.py --pdf path/to/file.pdf --out path/to/output_dir/
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# Ensure this module is registered in sys.modules for dataclass compatibility
_this_module = sys.modules.get(__name__)
if _this_module is None:
    import types
    _this_module = types.ModuleType(__name__)
    sys.modules[__name__] = _this_module

ENGINE_NAME = "pymupdf"
PROBLEM_PAGE_CHAR_THRESHOLD = 100  # below this, page is flagged for downstream OCR


@dataclass
class PageResult:
    page_number: int  # 1-indexed
    text: str
    char_count: int
    is_problem: bool  # too few chars -> likely scanned, needs OCR


def extract(pdf_path: Path) -> dict[str, Any]:
    """Open a PDF and return per-page text + metadata.

    Returns:
      {
        "pages": [PageResult(...).__dict__, ...],
        "metadata": {
            "source_file": str,
            "page_count": int,
            "engine": "pymupdf",
            "engine_version": str,
            "problem_page_count": int,
            "problem_pages": [int, ...],  # 1-indexed
            "extraction_seconds": float,
        }
      }
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    t0 = time.monotonic()
    pages: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            char_count = len(text.strip())
            pages.append(
                asdict(
                    PageResult(
                        page_number=i,
                        text=text,
                        char_count=char_count,
                        is_problem=char_count < PROBLEM_PAGE_CHAR_THRESHOLD,
                    )
                )
            )
    elapsed = time.monotonic() - t0

    problem_pages = [p["page_number"] for p in pages if p["is_problem"]]
    metadata = {
        "source_file": pdf_path.name,
        "page_count": len(pages),
        "engine": ENGINE_NAME,
        "engine_version": fitz.__doc__.splitlines()[0] if fitz.__doc__ else "unknown",
        "problem_page_count": len(problem_pages),
        "problem_pages": problem_pages,
        "extraction_seconds": round(elapsed, 3),
    }
    return {"pages": pages, "metadata": metadata}


def render_markdown(result: dict[str, Any]) -> str:
    """Render the extraction result as YAML-frontmatter + per-page markdown."""
    md = result["metadata"]
    lines = [
        "---",
        f'source_file: "{md["source_file"]}"',
        f'page_count: {md["page_count"]}',
        f'engine: "{md["engine"]}"',
        f'engine_version: "{md["engine_version"]}"',
        f'problem_page_count: {md["problem_page_count"]}',
        f'extraction_seconds: {md["extraction_seconds"]}',
        "---",
    ]
    for page in result["pages"]:
        lines.append(f'<!-- page: {page["page_number"]} -->')
        if page["is_problem"]:
            lines.append(f'<!-- problem-page: low text density ({page["char_count"]} chars), needs OCR -->')
        lines.append("")
        lines.append(page["text"].strip() if page["text"].strip() else "")
        lines.append("")
    return "\n".join(lines)


def write_outputs(pdf_path: Path, out_dir: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    """Write <stem>.md and <stem>.extract.json to out_dir. Returns paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.extract.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result["metadata"], indent=2), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract per-page text from a PDF using PyMuPDF.")
    parser.add_argument("--pdf", type=Path, required=True, help="Input PDF path")
    parser.add_argument("--out", type=Path, required=True, help="Output directory (created if missing)")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary")
    args = parser.parse_args(argv)

    result = extract(args.pdf)
    md_path, json_path = write_outputs(args.pdf, args.out, result)

    if not args.quiet:
        summary = {
            "md": str(md_path),
            "json": str(json_path),
            **result["metadata"],
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
