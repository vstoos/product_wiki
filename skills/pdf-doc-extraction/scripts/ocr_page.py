"""OCR scanned/problem pages of a PDF via LMStudio's OpenAI-compatible API.

Reads problem-page list from a Phase 1 <stem>.extract.json (or explicit --pages),
renders each page to PNG, POSTs it to a local vision model, and writes
<stem>.ocr.json next to the PDF. Phase 4 (assemble_md.py) will merge OCR text
into the final markdown.

Usage:
  python ocr_page.py --pdf <path>.pdf --extract-json <path>.extract.json --out <dir>
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request
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
