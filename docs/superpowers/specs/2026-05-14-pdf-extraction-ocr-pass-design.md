# Phase 2 — OCR pass for problem pages

**Skill:** `pdf-doc-extraction`
**Date:** 2026-05-14
**Status:** approved (design)
**Predecessor:** Phase 1 (`scripts/extract_text.py`) — shipped, flags problem pages
**Successor:** Phase 4 (`scripts/assemble_md.py`) — planned, will merge text + OCR

## Goal

Make Phase 1's `is_problem: true` flag actionable. Take the per-page list of low-text-density pages from `<stem>.extract.json`, render each as a PNG, run a local vision model via LMStudio's OpenAI-compatible HTTP endpoint, and write the transcribed text to a sidecar JSON file (`<stem>.ocr.json`).

Phase 2 does NOT modify Phase 1 outputs. The final merged markdown is produced by Phase 4 (`assemble_md.py`).

## Non-goals (deferred to later phases)

- Gemini API round-robin backend (Phase 2b — sibling function in the same script)
- Figure / image extraction (Phase 3)
- Vision-model figure captions (Phase 3)
- Final markdown assembly that splices OCR text back into Phase 1's `<stem>.md` (Phase 4)
- Re-extraction of tables on OCR'd pages (Phase 3+, paired with figure tooling)
- Concurrency / parallel page workers (KISS — serial for v1)

## Hard constraints

- **No PaddleOCR.** Caused Windows / WSL / Docker conflicts in prior work.
- **No new Python dependencies.** Stdlib `urllib.request` for HTTP, existing `fitz` (PyMuPDF) for page→PNG rendering, existing `pytest` for tests.
- **Cheap, OCR-specialized model by default.** `glm-ocr` (≈2B, OCR-specialized, >150 tps output on user's RTX 3090, few seconds for prompt processing). Escalate only on demonstrated failure. `gemma-4-e2b-it` (2B general vision) is the documented alternative.
- **One image per request.** Each page is a fresh HTTP POST with its own message array; no conversation context carried between pages. Avoids accidental cross-page contamination and matches LMStudio's per-request prompt-processing cost model.
- **No live model calls in tests.** All HTTP is mocked.
- **Don't OCR pages with clean text.** Process only pages from `extract.json::problem_pages`, unless `--pages` overrides.
- **Don't modify the input PDF or Phase 1 outputs.** All writes go to a new sidecar.
- **Per-page failures are recorded, not fatal.** A bad page logs `status: "error"` and continues; the rest of the run completes.

## CLI contract

```bash
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --extract-json <substance>/<AGENCY>/<file>.extract.json \
  --out <substance>/<AGENCY>/ \
  [--engine lmstudio]              # default; only backend in Phase 2
  [--model glm-ocr]         # backend default
  [--host http://localhost:1234]   # LMStudio host
  [--dpi 200]                      # PNG render DPI
  [--pages "3,5,7-9"]              # override problem-page list
  [--force]                        # bypass cache
  [--timeout 120]                  # per-page HTTP timeout (seconds)
  [--quiet]                        # suppress stdout summary
```

### Page selection

1. If `--pages` is given, use that list (parsed: comma-separated ints and/or `N-M` ranges, 1-indexed).
2. Else if `--extract-json` is given, load it and use `problem_pages`.
3. Else error: at least one of `--pages` or `--extract-json` must be present.

`--all-pages` is intentionally not supported in v1; use `--pages 1-N` if needed.

### Cache behaviour

- If `<stem>.ocr.json` exists at `<out>/<stem>.ocr.json`:
  - Load it.
  - Identify pages already present with `status: "ok"`.
  - Process only the requested pages NOT in that set.
  - Merge new results into the existing file, preserving `pages` ordering by `page_number`.
- If `--force` is set, ignore the existing file; reprocess every requested page.
- Pages whose existing entry has `status: "error"` are always re-attempted on a rerun (treated the same as missing). `--force` only changes behaviour for `status: "ok"` pages.

## Output: `<stem>.ocr.json`

```json
{
  "source_file": "SUPPL_011_210951Orig1s011lbl.pdf",
  "engine": "lmstudio",
  "model": "glm-ocr",
  "host": "http://localhost:1234",
  "dpi": 200,
  "ocr_date": "2026-05-14T10:23:00Z",
  "total_seconds": 8.4,
  "pages": [
    {
      "page_number": 12,
      "text": "...transcribed text...",
      "char_count": 1843,
      "duration_sec": 4.2,
      "status": "ok"
    },
    {
      "page_number": 13,
      "text": "",
      "char_count": 0,
      "duration_sec": 1.1,
      "status": "error",
      "error": "HTTP 503 from backend"
    }
  ]
}
```

Pages are sorted by `page_number` (1-indexed). `total_seconds` is wall-clock for the run. `ocr_date` is UTC ISO 8601.

## Architecture (single file)

`scripts/ocr_page.py` exposes:

| Function | Responsibility |
|---|---|
| `parse_page_spec(spec: str) -> list[int]` | Parse `"3,5,7-9"` → `[3, 5, 7, 8, 9]`. Validates ints, ranges, deduplicates, sorts. |
| `select_pages(args, extract_metadata) -> list[int]` | Apply page-selection precedence (`--pages` > `--extract-json::problem_pages`). |
| `render_page_png(pdf_path: Path, page_number: int, dpi: int) -> bytes` | PyMuPDF render → PNG bytes (1-indexed page in, 0-indexed internally). |
| `transcribe_lmstudio(image_png_bytes, *, host, model, timeout) -> str` | POST to `<host>/v1/chat/completions` with vision payload. Returns text. Raises on HTTP error. |
| `process_pages(pdf_path, page_numbers, backend_kwargs, dpi) -> list[dict]` | Loop, call render + transcribe per page, build `pages[]` entries. Catches per-page exceptions → `status: error`. |
| `load_existing_cache(json_path) -> dict \| None` | Read `<stem>.ocr.json` if present. |
| `merge_with_cache(new_pages, existing) -> list[dict]` | Combine new + existing, dedup by `page_number` (new wins). |
| `write_output(json_path, payload) -> None` | Write `<stem>.ocr.json`. |
| `main(argv) -> int` | CLI entry. |

No class abstraction. When Phase 2b adds Gemini, it's a sibling `transcribe_gemini(...)` function plus `--engine` dispatch in `process_pages`. No refactor.

## LMStudio backend details

OpenAI-compatible chat completions endpoint:

```
POST {host}/v1/chat/completions
Content-Type: application/json

{
  "model": "<model>",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "<OCR_PROMPT>"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,<b64>"}}
    ]
  }],
  "temperature": 0.0,
  "max_tokens": 4096
}
```

Response shape (OpenAI-compatible): `response["choices"][0]["message"]["content"]` → string.

Implementation uses `urllib.request.Request` + `urllib.request.urlopen` (stdlib). Timeout from `--timeout`. Errors (network, non-200, malformed JSON) raise; the caller catches per-page.

### OCR prompt (constant in source)

```
Transcribe all readable text from this document page image.

Rules:
- Preserve line breaks where they appear meaningful (between paragraphs).
- Preserve tables: HTML <table> if complex (rowspans, nested headers);
  GFM pipe table if simple.
- Preserve special characters literally (degree-sign, mu, plus-minus,
  less-equal, greater-equal, en-dash, em-dash, right-arrow, checkbox-checked,
  checkbox-empty). Do not convert these to words or booleans.
- Preserve redaction markers: (b)(4) stays as (b)(4).
- Do not add commentary, headers, or section labels you cannot see.
- If the page is blank or unreadable, output exactly: [BLANK PAGE]
```

The model is told to emit the actual glyphs verbatim from the image. The prompt itself uses descriptive names for the special characters so the source file stays ASCII-safe.

## Test plan (TDD)

Tests live in `skills/pdf-doc-extraction/tests/test_ocr_page.py`. All HTTP is mocked via `unittest.mock.patch("urllib.request.urlopen", ...)`. The existing `chemr_pdf` and `suppl11_pdf` fixtures provide real PDFs for render tests; if missing (CI without test data), tests `pytest.skip`.

| Test | What it verifies |
|---|---|
| `test_parse_page_spec_basic` | `"3,5,7-9"` → `[3, 5, 7, 8, 9]`; dedup; sort. |
| `test_parse_page_spec_invalid` | `"3,abc"` raises `ValueError`. |
| `test_render_page_png_returns_png_bytes` | `render_page_png(suppl11, 1, 200)` → bytes starting with PNG magic `\x89PNG\r\n\x1a\n`. |
| `test_transcribe_lmstudio_posts_correct_payload` | Mock `urlopen`, assert request body has `model`, vision content array, base64-encoded PNG. |
| `test_transcribe_lmstudio_returns_response_text` | Mock returns canned OpenAI response; function returns the `content` string. |
| `test_transcribe_lmstudio_raises_on_http_error` | Mock raises `HTTPError`; function propagates. |
| `test_process_pages_records_per_page_errors` | Mock `transcribe` to raise on page 2 of 3; result has `status:"error"` for page 2 and `status:"ok"` for 1 and 3. |
| `test_select_pages_prefers_pages_over_extract_json` | Both supplied → `--pages` wins. |
| `test_select_pages_falls_back_to_extract_json` | Only `--extract-json` → uses `problem_pages`. |
| `test_cache_skips_already_ok_pages` | Existing `.ocr.json` with page 5 ok; rerun for pages [5, 7]; only 7 gets transcribed. |
| `test_force_reprocesses_cached_pages` | Same as above with `--force`; both pages transcribed. |
| `test_cli_writes_ocr_json` | End-to-end: CLI invocation writes a `.ocr.json` with the expected keys; mock backend returns canned text. |

## Model selection update for SKILL.md

The model-selection table in `SKILL.md` is updated:

| Decision | Default | Escalate to | Never |
|---|---|---|---|
| Per-page text vs OCR routing | **Haiku** | Sonnet only after Haiku gives clearly wrong output twice | Opus |
| OCR of scanned pages | **`glm-ocr` via LMStudio (≈2B, OCR-specialized, >150 tps on RTX 3090)** | `gemma-4-e2b-it` (2B general vision) or `gemma-4-e4b-it` (4B) after `glm-ocr` produces clearly wrong output twice | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
| Vision captions for figures (Phase 3) | **Gemini API round-robin on Gemma 4 (free tier)** OR LMStudio Gemma 4 | Sonnet vision sparingly | Opus vision |

Gemini round-robin is documented as **Phase 2b — planned next**.

## Observability / report format

After processing, emit JSON summary on stdout (suppress with `--quiet`):

```json
{
  "ocr_json": "<path>",
  "pdf": "<path>",
  "engine": "lmstudio",
  "model": "glm-ocr",
  "pages_requested": 6,
  "pages_processed": 5,
  "pages_skipped_cached": 1,
  "pages_failed": 0,
  "total_seconds": 8.4
}
```

The wiki agent can fold this into its run report.

## Review questions resolved during design

| Question | Decision | Reasoning |
|---|---|---|
| Cloud (Gemini) backend in Phase 2 or 2b? | **2b.** | LMStudio covers the immediate need; round-robin adds rate-limit handling that complicates TDD. |
| Class-based backend abstraction now? | **No.** | Two backends → premature. Sibling functions + `--engine` ladder is enough until 3+. |
| Rewrite `<stem>.md` in place? | **No.** | Couples phases; breaks composability. Phase 4 is the assembler. |
| HTTP client: `requests` or stdlib? | **stdlib `urllib.request`.** | Avoid a dep for one POST. |
| Concurrency? | **Serial.** | LMStudio is single-process-bound; Phase 2b can add workers if Gemini round-robin needs it. |
| Default DPI? | **200.** | Reference brief recommends 200; 150 trades quality for speed. Configurable. |
| Page indexing? | **1-indexed externally, 0-indexed internally**, single conversion at the boundary. | Matches Phase 1; matches reference brief's #1 source-of-bugs warning. |

## Open follow-ups (not blocking)

- Phase 2b: Gemini round-robin backend (1 sibling function + `--engine gemini`).
- Phase 3: figure / table raster extraction → `<stem>.assets/`.
- Phase 4: `assemble_md.py` orchestrator that produces final `<stem>.md` from Phase 1 + 2 + 3 outputs.
- Backfill: 31 unextracted FDA / HC / PMDA / TGA PDFs in `apalutamide/` once Phase 4 is shipped.
