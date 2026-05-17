"""OCR scanned/problem pages of a PDF via llama.cpp's OpenAI-compatible API.

Reads problem-page list from a Phase 1 <stem>.extract.json (or explicit --pages),
renders each page to PNG, POSTs it to a local vision model, and writes
<stem>.ocr.json next to the PDF. Phase 4 (assemble_md.py) will merge OCR text
into the final markdown.

Usage:
  python ocr_page.py --pdf <path>.pdf --extract-json <path>.extract.json --out <dir>
"""
from __future__ import annotations

# Re-export from the shared vision backends module so test code (which
# does `ocr_page.X`) continues to work without changes, and so future
# scripts (caption_figure.py) can import the same backends.
import importlib.util as _ilu
from pathlib import Path as _Path
import sys as _sys

_vb_path = _Path(__file__).resolve().parent / "_vision_backends.py"
_vb_spec = _ilu.spec_from_file_location("_vision_backends", _vb_path)
_vision_backends = _ilu.module_from_spec(_vb_spec)
_sys.modules["_vision_backends"] = _vision_backends
_vb_spec.loader.exec_module(_vision_backends)

OCR_PROMPT = _vision_backends.OCR_PROMPT
OCR_MODEL_PATTERN = _vision_backends.OCR_MODEL_PATTERN
GEMINI_ENDPOINT = _vision_backends.GEMINI_ENDPOINT
transcribe_llama_cpp = _vision_backends.transcribe_llama_cpp
transcribe_gemini = _vision_backends.transcribe_gemini
resolve_prompt = _vision_backends.resolve_prompt
check_model_loaded = _vision_backends.check_model_loaded

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF


def _gemini_with_round_robin(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> str:
    """Try each (api_key, model) pair in order. Retry on transient failures.

    Advances to the next pair on HTTP 429 (rate limit) or HTTP 5xx
    (transient server error). Non-transient HTTPError codes propagate.
    Raises RuntimeError if every pair is exhausted, carrying the last error.

    Thin wrapper over transcribe_gemini that lives here so that
    patch.object(ocr_page, 'transcribe_gemini') is intercepted correctly
    in tests that mock the HTTP layer.
    """
    last_err: Exception | None = None
    for api_key, model in pairs:
        try:
            return transcribe_gemini(
                image_png_bytes,
                api_key=api_key,
                model=model,
                timeout=timeout,
                prompt=prompt,
            )
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                last_err = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs exhausted ({len(pairs)} tried); last={last_err}"
    ) from last_err


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


def process_pages(
    *,
    pdf_path: Path,
    page_numbers: list[int],
    dpi: int,
    engine: str = "llama-cpp",
    host: str = "http://127.0.0.1:8080",
    model: str = "LightOnOCR-2-1B-ocr-soup-BF16.gguf",
    timeout: int = 120,
    prompt: str = OCR_PROMPT,
    gemini_pairs: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Render and transcribe each page. Per-page errors are recorded, not raised.

    Returns one dict per requested page, in input order:
      {page_number, text, char_count, duration_sec, status, [error]}
    """
    results: list[dict] = []
    pairs = list(gemini_pairs or [])
    for pn in page_numbers:
        t0 = time.monotonic()
        try:
            png = render_page_png(pdf_path, page_number=pn, dpi=dpi)
            if engine == "gemini":
                if not pairs:
                    raise RuntimeError("engine=gemini requires non-empty gemini_pairs")
                text = _gemini_with_round_robin(
                    png, pairs=pairs, timeout=timeout, prompt=prompt
                )
                # Rotate after each successful call to spread load
                pairs = pairs[1:] + pairs[:1]
            else:
                text = transcribe_llama_cpp(
                    png, host=host, model=model, timeout=timeout, prompt=prompt
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
        description="OCR scanned/problem pages of a PDF via llama.cpp."
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
        "--engine", default="llama-cpp", choices=["llama-cpp", "gemini"],
        help="OCR backend",
    )
    parser.add_argument("--model", default="LightOnOCR-2-1B-ocr-soup-BF16.gguf")
    parser.add_argument("--host", default="http://127.0.0.1:8080")
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
    parser.add_argument(
        "--prompt",
        default=None,
        help="Override the OCR prompt. Empty string -> image-only request. "
             "Default: auto-empty for OCR-specialized models (name matches /ocr/i), "
             "OCR_PROMPT for general vision models.",
    )
    parser.add_argument("--skip-model-check", action="store_true",
                        help="Skip the early /v1/models probe that warns if the "
                             "requested model isn't loaded by llama-server.")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--api-key", action="append", default=None,
        help="Gemini API key. Repeatable for round-robin across multiple keys. "
             "If omitted, falls back to GEMINI_API_KEY or GOOGLE_API_KEY env var.",
    )
    parser.add_argument(
        "--gemini-models",
        default=None,
        help="Comma-separated Gemini model names (required for --engine gemini). "
             "Example: 'gemma-4-31b-it,gemma-4-26b-a4b-it'.",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    ocr_json_path = args.out / f"{args.pdf.stem}.ocr.json"

    gemini_pairs: list[tuple[str, str]] = []
    if args.engine == "gemini":
        keys = list(args.api_key or [])
        # Prefer GEMINI_API_KEY but accept GOOGLE_API_KEY (Google's canonical
        # name, used by their own SDKs). Either env var works.
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not keys and env_key:
            keys = [env_key]
        if not keys:
            print("error: --engine gemini requires --api-key or "
                  "GEMINI_API_KEY/GOOGLE_API_KEY env var",
                  file=sys.stderr)
            return 2
        if not args.gemini_models:
            print("error: --engine gemini requires --gemini-models (comma-separated)",
                  file=sys.stderr)
            return 2
        models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]
        if not models:
            print("error: --gemini-models is empty after parsing", file=sys.stderr)
            return 2
        gemini_pairs = [(k, m) for k in keys for m in models]

    extract_metadata = None
    if args.extract_json is not None:
        extract_metadata = json.loads(args.extract_json.read_text(encoding="utf-8"))

    requested = select_pages(pages_spec=args.pages, extract_metadata=extract_metadata)
    cache = load_existing_cache(ocr_json_path)
    to_do = pages_to_process(requested=requested, cache=cache, force=args.force)

    # For prompt resolution, use the actual model that will receive the request:
    # - llama-cpp engine -> args.model (default LightOnOCR-2-1B-ocr-soup-BF16.gguf)
    # - gemini engine    -> first --gemini-models entry (e.g. gemma-4-31b-it)
    prompt_model = (
        gemini_pairs[0][1] if args.engine == "gemini" and gemini_pairs else args.model
    )
    prompt, prompt_mode = resolve_prompt(user_prompt=args.prompt, model=prompt_model)

    if to_do and args.engine == "llama-cpp" and not args.skip_model_check:
        warning = check_model_loaded(host=args.host, model=args.model)
        if warning and not args.quiet:
            print(f"WARNING: {warning}", file=sys.stderr)

    t0 = time.monotonic()
    new_pages = process_pages(
        pdf_path=args.pdf,
        page_numbers=to_do,
        dpi=args.dpi,
        engine=args.engine,
        host=args.host,
        model=args.model,
        timeout=args.timeout,
        prompt=prompt,
        gemini_pairs=gemini_pairs,
    )
    total_seconds = round(time.monotonic() - t0, 3)

    merged_pages = merge_with_cache(new_pages=new_pages, cache=cache)
    payload = {
        "source_file": args.pdf.name,
        "engine": args.engine,
        "model": args.model,
        "host": args.host,
        "dpi": args.dpi,
        "prompt_mode": prompt_mode,
        "ocr_date": _utc_now_iso(),
        "total_seconds": total_seconds,
        "pages": merged_pages,
    }
    if args.engine == "gemini":
        payload["gemini_models"] = args.gemini_models or ""
    ocr_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.quiet:
        failed = sum(1 for p in new_pages if p["status"] == "error")
        summary = {
            "ocr_json": str(ocr_json_path),
            "pdf": str(args.pdf),
            "engine": args.engine,
            "model": args.model,
            "prompt_mode": prompt_mode,
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
