"""OCR scanned/problem pages of a PDF via LMStudio's OpenAI-compatible API.

Reads problem-page list from a Phase 1 <stem>.extract.json (or explicit --pages),
renders each page to PNG, POSTs it to a local vision model, and writes
<stem>.ocr.json next to the PDF. Phase 4 (assemble_md.py) will merge OCR text
into the final markdown.

Usage:
  python ocr_page.py --pdf <path>.pdf --extract-json <path>.extract.json --out <dir>
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF


def parse_page_spec(spec: str) -> list[int]:
    """Parse '3,5,7-9' -> [3, 5, 7, 8, 9]. Deduped, sorted, 1-indexed.

    Raises ValueError on malformed input. Empty string returns [].
    """
    if not spec or not spec.strip():
        return []
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
            if lo > hi:
                raise ValueError(f"invalid range {part!r}: lo > hi")
            pages.update(range(lo, hi + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def select_pages(
    pages_spec: str | None,
    extract_metadata: dict | None,
) -> list[int]:
    """Choose pages to OCR.

    Precedence: explicit --pages > extract.json::problem_pages.
    At least one source must be provided.
    """
    if pages_spec is not None:
        return parse_page_spec(pages_spec)
    if extract_metadata is None:
        raise ValueError("either --pages or --extract-json must be provided")
    problem_pages = extract_metadata.get("problem_pages", [])
    return sorted(set(int(p) for p in problem_pages))


def render_page_png(pdf_path: Path, page_number: int, dpi: int) -> bytes:
    """Render the given 1-indexed page to PNG bytes at the given DPI.

    Raises IndexError if page_number is out of range.
    """
    if page_number < 1:
        raise ValueError(f"page_number must be >= 1, got {page_number}")
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        if page_number > doc.page_count:
            raise IndexError(f"page {page_number} out of range (doc has {doc.page_count} pages)")
        page = doc[page_number - 1]  # 1-indexed -> 0-indexed
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")


OCR_PROMPT = (
    "Transcribe all readable text from this document page image.\n"
    "\n"
    "Rules:\n"
    "- Preserve line breaks where they appear meaningful (between paragraphs).\n"
    "- Preserve tables: HTML <table> if complex (rowspans, nested headers); "
    "GFM pipe table if simple.\n"
    "- Preserve special characters literally (degree-sign, mu, plus-minus, "
    "less-equal, greater-equal, en-dash, em-dash, right-arrow, "
    "checkbox-checked, checkbox-empty). Do not convert these to words or booleans.\n"
    "- Preserve redaction markers: (b)(4) stays as (b)(4).\n"
    "- Do not add commentary, headers, or section labels you cannot see.\n"
    "- If the page is blank or unreadable, output exactly: [BLANK PAGE]\n"
)


def transcribe_lmstudio(
    image_png_bytes: bytes,
    *,
    host: str,
    model: str,
    timeout: int,
) -> str:
    """POST the image to a local LMStudio OpenAI-compatible vision endpoint.

    Returns the model's response content, stripped of leading/trailing whitespace.
    Raises on HTTP errors, network errors, and malformed responses.

    One image per request: no conversation context is carried between pages.
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    req = urllib.request.Request(
        url=f"{host.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    return body["choices"][0]["message"]["content"].strip()


def process_pages(
    *,
    pdf_path: Path,
    page_numbers: list[int],
    dpi: int,
    host: str,
    model: str,
    timeout: int,
) -> list[dict]:
    """Render and transcribe each page. Per-page errors are recorded, not raised.

    Returns one dict per requested page, in input order:
      {page_number, text, char_count, duration_sec, status, [error]}
    """
    results: list[dict] = []
    for pn in page_numbers:
        t0 = time.monotonic()
        try:
            png = render_page_png(pdf_path, page_number=pn, dpi=dpi)
            text = transcribe_lmstudio(
                png, host=host, model=model, timeout=timeout
            )
            results.append({
                "page_number": pn,
                "text": text,
                "char_count": len(text),
                "duration_sec": round(time.monotonic() - t0, 3),
                "status": "ok",
            })
        except Exception as e:  # noqa: BLE001 - per-page containment is the point
            results.append({
                "page_number": pn,
                "text": "",
                "char_count": 0,
                "duration_sec": round(time.monotonic() - t0, 3),
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            })
    return results


def load_existing_cache(json_path: Path) -> dict | None:
    """Load an existing <stem>.ocr.json if present, else None."""
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text(encoding="utf-8"))


def pages_to_process(
    *, requested: list[int], cache: dict | None, force: bool
) -> list[int]:
    """Return the subset of requested pages that actually need processing.

    Cached pages with status='ok' are skipped (unless --force).
    Cached pages with status='error' are always retried.
    """
    if force or cache is None:
        return list(requested)
    ok_pages = {
        p["page_number"]
        for p in cache.get("pages", [])
        if p.get("status") == "ok"
    }
    return [pn for pn in requested if pn not in ok_pages]


def merge_with_cache(*, new_pages: list[dict], cache: dict | None) -> list[dict]:
    """Combine new and cached page entries. New entries win on conflict.

    Result is sorted by page_number.
    """
    by_pn: dict[int, dict] = {}
    if cache is not None:
        for p in cache.get("pages", []):
            by_pn[p["page_number"]] = p
    for p in new_pages:
        by_pn[p["page_number"]] = p
    return [by_pn[pn] for pn in sorted(by_pn)]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR scanned/problem pages of a PDF via LMStudio."
    )
    parser.add_argument("--pdf", type=Path, required=True, help="Input PDF path")
    parser.add_argument(
        "--extract-json",
        type=Path,
        default=None,
        help="Phase 1 <stem>.extract.json (used unless --pages given)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory; <stem>.ocr.json is written here",
    )
    parser.add_argument(
        "--engine", default="lmstudio", choices=["lmstudio"],
        help="OCR backend (only 'lmstudio' in Phase 2)",
    )
    parser.add_argument("--model", default="glm-ocr")
    parser.add_argument("--host", default="http://localhost:1234")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument(
        "--pages",
        default=None,
        help="Override problem-page list, e.g. '3,5,7-9'",
    )
    parser.add_argument("--force", action="store_true",
                        help="Reprocess pages even if already cached as ok")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-page HTTP timeout (seconds)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    ocr_json_path = args.out / f"{args.pdf.stem}.ocr.json"

    extract_metadata = None
    if args.extract_json is not None:
        extract_metadata = json.loads(args.extract_json.read_text(encoding="utf-8"))

    requested = select_pages(pages_spec=args.pages, extract_metadata=extract_metadata)
    cache = load_existing_cache(ocr_json_path)
    to_do = pages_to_process(requested=requested, cache=cache, force=args.force)

    t0 = time.monotonic()
    new_pages = process_pages(
        pdf_path=args.pdf,
        page_numbers=to_do,
        dpi=args.dpi,
        host=args.host,
        model=args.model,
        timeout=args.timeout,
    )
    total_seconds = round(time.monotonic() - t0, 3)

    merged_pages = merge_with_cache(new_pages=new_pages, cache=cache)
    payload = {
        "source_file": args.pdf.name,
        "engine": args.engine,
        "model": args.model,
        "host": args.host,
        "dpi": args.dpi,
        "ocr_date": _utc_now_iso(),
        "total_seconds": total_seconds,
        "pages": merged_pages,
    }
    ocr_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.quiet:
        failed = sum(1 for p in new_pages if p["status"] == "error")
        summary = {
            "ocr_json": str(ocr_json_path),
            "pdf": str(args.pdf),
            "engine": args.engine,
            "model": args.model,
            "pages_requested": len(requested),
            "pages_processed": len(new_pages),
            "pages_skipped_cached": len(requested) - len(to_do),
            "pages_failed": failed,
            "total_seconds": total_seconds,
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
