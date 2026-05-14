# PDF Extraction Phase 2 — OCR Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/ocr_page.py` that transcribes flagged problem pages from a PDF using a local LMStudio vision model and writes a `<stem>.ocr.json` sidecar that Phase 4 will later splice into the final markdown.

**Architecture:** Single-file CLI with stdlib-only HTTP, in-function backends (no class abstraction), 1-indexed pages externally / 0-indexed internally with a single conversion point, per-page error containment, cache-aware reruns. Tests mock `urllib.request.urlopen`; no live model calls in the suite.

**Tech Stack:** Python 3 stdlib (`urllib.request`, `base64`, `json`, `argparse`, `pathlib`, `dataclasses` if used), PyMuPDF (`fitz`) for PDF → PNG rendering, pytest, `unittest.mock.patch` for HTTP fakes. LMStudio's OpenAI-compatible chat completions endpoint at `http://localhost:1234/v1/chat/completions` is the runtime dependency.

**Spec:** `docs/superpowers/specs/2026-05-14-pdf-extraction-ocr-pass-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `skills/pdf-doc-extraction/scripts/ocr_page.py` | Create | The OCR CLI: page parsing, PNG render, LMStudio HTTP, per-page processing, cache merge, output write, argparse main. |
| `skills/pdf-doc-extraction/tests/test_ocr_page.py` | Create | Unit + integration tests with mocked HTTP. Uses `importlib.util.spec_from_file_location` loader to match Phase 1 test style. |
| `skills/pdf-doc-extraction/SKILL.md` | Modify | Update tool table (Phase 2 OCR row → shipped), model-selection table (OCR row → LMStudio default), invocation example for OCR. |
| `skills/pdf-doc-extraction/README.md` | Modify | Add `ocr_page.py` to the tools list with a quick-start example. |
| `skills/pdf-doc-extraction/requirements.txt` | Untouched | No new deps. |

Each module-level function in `ocr_page.py` is pure (one responsibility, no hidden state). The CLI `main()` wires them together. When Phase 2b adds Gemini, it inserts one sibling `transcribe_gemini(...)` function plus an `if args.engine == ...` arm in `process_pages` — no refactor.

---

### Task 1: Scaffold `ocr_page.py` + first failing test (parse_page_spec)

**Files:**
- Create: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Create: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Create empty `ocr_page.py` shell**

`skills/pdf-doc-extraction/scripts/ocr_page.py`:

```python
"""OCR scanned/problem pages of a PDF via LMStudio's OpenAI-compatible API.

Reads problem-page list from a Phase 1 <stem>.extract.json (or explicit --pages),
renders each page to PNG, POSTs it to a local vision model, and writes
<stem>.ocr.json next to the PDF. Phase 4 (assemble_md.py) will merge OCR text
into the final markdown.

Usage:
  python ocr_page.py --pdf <path>.pdf --extract-json <path>.extract.json --out <dir>
"""
from __future__ import annotations

import sys
```

- [ ] **Step 2: Write the failing test for `parse_page_spec`**

`skills/pdf-doc-extraction/tests/test_ocr_page.py`:

```python
"""Tests for ocr_page.py. HTTP is mocked; no live model calls."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ocr_page.py"


def _load_ocr_page():
    spec = importlib.util.spec_from_file_location("ocr_page", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ocr_page"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_page_spec_basic():
    ocr_page = _load_ocr_page()
    assert ocr_page.parse_page_spec("3,5,7-9") == [3, 5, 7, 8, 9]


def test_parse_page_spec_dedupes_and_sorts():
    ocr_page = _load_ocr_page()
    assert ocr_page.parse_page_spec("5,1,3-5") == [1, 3, 4, 5]


def test_parse_page_spec_rejects_invalid():
    ocr_page = _load_ocr_page()
    with pytest.raises(ValueError):
        ocr_page.parse_page_spec("3,abc")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v`
Expected: 3 FAILs with `AttributeError: module 'ocr_page' has no attribute 'parse_page_spec'`.

- [ ] **Step 4: Implement `parse_page_spec` in `ocr_page.py`**

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Verify Phase 1 tests still pass**

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: All Phase 1 + Phase 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): scaffold ocr_page.py + parse_page_spec

First step of Phase 2 OCR pass: parse the user's --pages spec
('3,5,7-9') into a sorted, deduped 1-indexed list. Stdlib-only.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `select_pages` — choose which pages to OCR

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing tests for page selection precedence**

Append to `test_ocr_page.py`:

```python


def test_select_pages_prefers_explicit_pages():
    ocr_page = _load_ocr_page()
    result = ocr_page.select_pages(pages_spec="3,5", extract_metadata={"problem_pages": [10, 20]})
    assert result == [3, 5]


def test_select_pages_falls_back_to_extract_metadata():
    ocr_page = _load_ocr_page()
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": [10, 20]})
    assert result == [10, 20]


def test_select_pages_requires_one_source():
    ocr_page = _load_ocr_page()
    with pytest.raises(ValueError):
        ocr_page.select_pages(pages_spec=None, extract_metadata=None)


def test_select_pages_empty_problem_pages_returns_empty():
    ocr_page = _load_ocr_page()
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": []})
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v`
Expected: 4 new tests FAIL with `AttributeError: module 'ocr_page' has no attribute 'select_pages'`.

- [ ] **Step 3: Implement `select_pages`**

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v`
Expected: All 7 Phase 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): select_pages with --pages > extract.json precedence

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `render_page_png` — PDF page to PNG bytes

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing test using the existing `suppl11_pdf` fixture**

Append to `test_ocr_page.py`:

```python


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_page_png_returns_png_bytes(suppl11_pdf):
    ocr_page = _load_ocr_page()
    data = ocr_page.render_page_png(suppl11_pdf, page_number=1, dpi=150)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 1000  # a real page render should be > 1 KB


def test_render_page_png_invalid_page_raises(suppl11_pdf):
    ocr_page = _load_ocr_page()
    with pytest.raises((IndexError, ValueError)):
        ocr_page.render_page_png(suppl11_pdf, page_number=9999, dpi=150)
```

(`suppl11_pdf` fixture already exists in `conftest.py` from Phase 1; it `pytest.skip`s if the apalutamide test corpus is missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k render`
Expected: FAIL with `AttributeError: module 'ocr_page' has no attribute 'render_page_png'` (or SKIP if no test data).

- [ ] **Step 3: Implement `render_page_png`**

Add to imports at the top of `ocr_page.py`:

```python
from pathlib import Path

import fitz  # PyMuPDF
```

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k render`
Expected: 2 PASS (or SKIP if no test data — that is acceptable).

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): render_page_png via PyMuPDF (1-indexed in)

Single conversion to 0-indexed at the boundary. Raises IndexError
for out-of-range pages.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `transcribe_lmstudio` — POST to LMStudio with mocked HTTP

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing tests for the HTTP call**

Append to `test_ocr_page.py`:

```python


import json as _json
from unittest.mock import patch


class _MockResponse:
    """Minimal context-manager response for urlopen."""

    def __init__(self, body_dict, status: int = 200):
        self._body = _json.dumps(body_dict).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_transcribe_lmstudio_sends_vision_payload():
    ocr_page = _load_ocr_page()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _MockResponse({"choices": [{"message": {"content": "TRANSCRIBED"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG\r\n\x1a\nFAKEBYTES",
            host="http://localhost:1234",
            model="glm-ocr",
            timeout=60,
        )
    assert result == "TRANSCRIBED"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["timeout"] == 60
    body = captured["body"]
    assert body["model"] == "glm-ocr"
    assert body["temperature"] == 0.0
    content = body["messages"][0]["content"]
    types = [item["type"] for item in content]
    assert "text" in types and "image_url" in types
    img_item = next(c for c in content if c["type"] == "image_url")
    assert img_item["image_url"]["url"].startswith("data:image/png;base64,")


def test_transcribe_lmstudio_strips_trailing_whitespace():
    ocr_page = _load_ocr_page()
    body = {"choices": [{"message": {"content": "  hello world  \n"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
        )
    assert result == "hello world"


def test_transcribe_lmstudio_propagates_http_error():
    ocr_page = _load_ocr_page()
    import urllib.error
    err = urllib.error.HTTPError(
        url="x", code=503, msg="unavailable", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            ocr_page.transcribe_lmstudio(
                b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k transcribe`
Expected: FAIL with `AttributeError: module 'ocr_page' has no attribute 'transcribe_lmstudio'`.

- [ ] **Step 3: Implement `transcribe_lmstudio` and `OCR_PROMPT`**

Add to imports at the top of `ocr_page.py`:

```python
import base64
import json
import urllib.request
```

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k transcribe`
Expected: 3 PASS.

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): transcribe_lmstudio via stdlib urllib

OCR prompt with explicit rules for tables, special chars, redactions.
Stdlib-only HTTP. Tests mock urlopen; no live model in suite.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `process_pages` — orchestrate per-page transcription with error containment

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing tests for error containment and ordering**

Append to `test_ocr_page.py`:

```python


def test_process_pages_records_per_page_errors(suppl11_pdf):
    ocr_page = _load_ocr_page()

    call_count = {"n": 0}

    def fake_transcribe(image_bytes, *, host, model, timeout):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("backend exploded")
        return f"page-text-{call_count['n']}"

    with patch.object(ocr_page, "transcribe_lmstudio", side_effect=fake_transcribe):
        results = ocr_page.process_pages(
            pdf_path=suppl11_pdf,
            page_numbers=[1, 2, 3],
            dpi=100,
            host="http://localhost:1234",
            model="m",
            timeout=60,
        )

    assert [r["page_number"] for r in results] == [1, 2, 3]
    assert results[0]["status"] == "ok"
    assert results[0]["text"] == "page-text-1"
    assert results[1]["status"] == "error"
    assert "backend exploded" in results[1]["error"]
    assert results[1]["text"] == ""
    assert results[2]["status"] == "ok"
    assert results[2]["text"] == "page-text-3"
    for r in results:
        assert "duration_sec" in r
        assert "char_count" in r


def test_process_pages_empty_list_returns_empty():
    ocr_page = _load_ocr_page()
    results = ocr_page.process_pages(
        pdf_path=Path("nonexistent.pdf"),
        page_numbers=[],
        dpi=100,
        host="x",
        model="x",
        timeout=1,
    )
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k process_pages`
Expected: FAIL — `process_pages` not defined.

- [ ] **Step 3: Implement `process_pages`**

Add to imports near the top of `ocr_page.py`:

```python
import time
```

Append to `scripts/ocr_page.py`:

```python


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
        except Exception as e:  # noqa: BLE001 — per-page containment is the point
            results.append({
                "page_number": pn,
                "text": "",
                "char_count": 0,
                "duration_sec": round(time.monotonic() - t0, 3),
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k process_pages`
Expected: 2 PASS.

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): process_pages with per-page error containment

A single page failing does not abort the run; it is recorded with
status='error' and the loop continues.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Cache load + merge — skip already-OK pages on rerun

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing tests for cache behaviour**

Append to `test_ocr_page.py`:

```python


def test_load_existing_cache_missing_returns_none(tmp_path):
    ocr_page = _load_ocr_page()
    assert ocr_page.load_existing_cache(tmp_path / "missing.ocr.json") is None


def test_load_existing_cache_reads_json(tmp_path):
    ocr_page = _load_ocr_page()
    path = tmp_path / "stem.ocr.json"
    path.write_text(_json.dumps({"pages": [{"page_number": 5, "status": "ok", "text": "x"}]}))
    cache = ocr_page.load_existing_cache(path)
    assert cache is not None
    assert cache["pages"][0]["page_number"] == 5


def test_pages_to_process_excludes_cached_ok():
    ocr_page = _load_ocr_page()
    cache = {"pages": [
        {"page_number": 5, "status": "ok"},
        {"page_number": 7, "status": "error"},
    ]}
    to_do = ocr_page.pages_to_process(
        requested=[5, 6, 7, 8], cache=cache, force=False
    )
    # 5 is cached-ok -> skip; 7 is cached-error -> retry; 6, 8 are new
    assert to_do == [6, 7, 8]


def test_pages_to_process_force_reprocesses_all():
    ocr_page = _load_ocr_page()
    cache = {"pages": [
        {"page_number": 5, "status": "ok"},
        {"page_number": 7, "status": "error"},
    ]}
    assert ocr_page.pages_to_process(
        requested=[5, 6, 7], cache=cache, force=True
    ) == [5, 6, 7]


def test_pages_to_process_no_cache_returns_all():
    ocr_page = _load_ocr_page()
    assert ocr_page.pages_to_process(
        requested=[1, 2, 3], cache=None, force=False
    ) == [1, 2, 3]


def test_merge_with_cache_new_wins_over_old():
    ocr_page = _load_ocr_page()
    cache = {"pages": [
        {"page_number": 5, "status": "ok", "text": "OLD"},
        {"page_number": 7, "status": "error"},
    ]}
    new = [{"page_number": 7, "status": "ok", "text": "NEW"}]
    merged = ocr_page.merge_with_cache(new_pages=new, cache=cache)
    by_pn = {p["page_number"]: p for p in merged}
    assert by_pn[5]["text"] == "OLD"
    assert by_pn[7]["text"] == "NEW"
    assert [p["page_number"] for p in merged] == [5, 7]  # sorted by page_number


def test_merge_with_cache_no_cache_returns_new_sorted():
    ocr_page = _load_ocr_page()
    new = [{"page_number": 7, "text": "b"}, {"page_number": 3, "text": "a"}]
    merged = ocr_page.merge_with_cache(new_pages=new, cache=None)
    assert [p["page_number"] for p in merged] == [3, 7]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k "cache or pages_to_process or merge"`
Expected: 7 FAILs — functions not defined.

- [ ] **Step 3: Implement cache helpers**

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k "cache or pages_to_process or merge"`
Expected: 7 PASS.

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): cache load + merge for OCR rerun

OK pages are skipped on rerun; error pages are always retried; --force
ignores the cache entirely. Merge keeps results sorted by page number.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: CLI `main()` + end-to-end test

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Write failing end-to-end test**

Append to `test_ocr_page.py`:

```python


def test_cli_writes_ocr_json(suppl11_pdf, tmp_path):
    ocr_page = _load_ocr_page()

    # Provide a fake extract.json indicating page 1 is a problem page
    extract_json = tmp_path / f"{suppl11_pdf.stem}.extract.json"
    extract_json.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "problem_pages": [1],
        "page_count": 35,
    }))

    body = {"choices": [{"message": {"content": "FAKE OCR TEXT"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--extract-json", str(extract_json),
            "--out", str(tmp_path),
            "--engine", "lmstudio",
            "--model", "glm-ocr",
            "--quiet",
        ])
    assert rc == 0

    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    assert ocr_json_path.exists()
    payload = _json.loads(ocr_json_path.read_text())
    assert payload["engine"] == "lmstudio"
    assert payload["model"] == "glm-ocr"
    assert payload["dpi"] == 200
    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["page_number"] == 1
    assert payload["pages"][0]["status"] == "ok"
    assert payload["pages"][0]["text"] == "FAKE OCR TEXT"
    assert "ocr_date" in payload
    assert "total_seconds" in payload


def test_cli_cache_skips_already_ok_pages(suppl11_pdf, tmp_path):
    ocr_page = _load_ocr_page()

    # Pre-seed cache with page 1 already ok
    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    ocr_json_path.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "engine": "lmstudio",
        "model": "glm-ocr",
        "host": "http://localhost:1234",
        "dpi": 200,
        "pages": [{
            "page_number": 1, "text": "CACHED", "char_count": 6,
            "duration_sec": 0.1, "status": "ok",
        }],
    }))

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        return _MockResponse({"choices": [{"message": {"content": "FRESH"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--quiet",
        ])
    assert rc == 0
    assert call_count["n"] == 0  # cache hit, no HTTP call

    payload = _json.loads(ocr_json_path.read_text())
    assert payload["pages"][0]["text"] == "CACHED"


def test_cli_force_reprocesses_cached_page(suppl11_pdf, tmp_path):
    ocr_page = _load_ocr_page()
    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    ocr_json_path.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "engine": "lmstudio",
        "model": "glm-ocr",
        "host": "http://localhost:1234",
        "dpi": 200,
        "pages": [{
            "page_number": 1, "text": "CACHED", "char_count": 6,
            "duration_sec": 0.1, "status": "ok",
        }],
    }))

    body = {"choices": [{"message": {"content": "FRESH"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--force",
            "--quiet",
        ])
    assert rc == 0

    payload = _json.loads(ocr_json_path.read_text())
    assert payload["pages"][0]["text"] == "FRESH"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k cli`
Expected: 3 FAILs — `main` not defined.

- [ ] **Step 3: Implement `main()`**

Add to imports near the top of `ocr_page.py`:

```python
import argparse
from datetime import datetime, timezone
```

Append to `scripts/ocr_page.py`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_ocr_page.py -v -k cli`
Expected: 3 PASS.

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP — full suite green.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/ocr_page.py skills/pdf-doc-extraction/tests/test_ocr_page.py
git commit -m "feat(pdf-extraction): ocr_page.py CLI main() + end-to-end tests

Wires select_pages -> load_cache -> pages_to_process -> process_pages
-> merge -> write. Cache-aware rerun with --force override. Stdout
summary unless --quiet.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Update SKILL.md and README.md

**Files:**
- Modify: `skills/pdf-doc-extraction/SKILL.md`
- Modify: `skills/pdf-doc-extraction/README.md`

- [ ] **Step 1: Read current SKILL.md and README.md**

Run: `cat skills/pdf-doc-extraction/SKILL.md skills/pdf-doc-extraction/README.md`

- [ ] **Step 2: Update SKILL.md model-selection table**

In `skills/pdf-doc-extraction/SKILL.md`, replace the OCR row of the model-selection table:

Old row:
```
| OCR of scanned pages | **Gemini API round-robin on Gemma 4 models (free tier)**; planned local 2B models in future | Gemma 27B/31B if 4B output is unusable | Paid OCR (Azure DI) — only on explicit user request |
```

New row:
```
| OCR of scanned pages | **`glm-ocr` via LMStudio (≈2B, OCR-specialized, >150 tps on RTX 3090)** | `gemma-4-e2b-it` (2B general vision) or `gemma-4-e4b-it` (4B) after `glm-ocr` produces clearly wrong output twice. Gemini API round-robin is planned for Phase 2b. | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
```

- [ ] **Step 3: Update SKILL.md tools table**

Replace the `ocr_page.py` row:

Old row:
```
| `scripts/ocr_page.py` | planned | Gemma OCR for problem pages. Free-tier round-robin between Gemini API and OpenRouter. |
```

New row:
```
| `scripts/ocr_page.py` | shipped | LMStudio OCR for problem pages. Reads Phase 1's `<stem>.extract.json`, transcribes flagged pages, writes `<stem>.ocr.json`. Gemini API round-robin is Phase 2b. |
```

Also rename the heading `## Tools available (Phase 1)` to `## Tools available`.

- [ ] **Step 4: Add OCR invocation example to SKILL.md**

Below the existing `## How to invoke (Phase 1 only)` section, replace its content and heading with:

```markdown
## How to invoke

### Text extraction (Phase 1)

```bash
python skills/pdf-doc-extraction/scripts/extract_text.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/
```

Writes `<stem>.md` and `<stem>.extract.json` next to the PDF.

### OCR pass (Phase 2)

Requires LMStudio running locally with a vision-capable model loaded
(default: `glm-ocr`). Start LMStudio's local server on port 1234
before invoking.

```bash
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --extract-json <substance>/<AGENCY>/<file>.extract.json \
  --out <substance>/<AGENCY>/
```

Reads `problem_pages` from the extract sidecar, transcribes each, writes
`<stem>.ocr.json`. Override which pages to OCR with `--pages "3,5,7-9"`.
Rerun is cache-aware: ok-status pages are skipped unless `--force`.
```

- [ ] **Step 5: Update README.md tool table**

In `skills/pdf-doc-extraction/README.md`, change the `ocr_page.py` row from "planned" to "shipped" and add a quick-start block below it:

```markdown
### OCR a PDF's problem pages (Phase 2)

```bash
# Start LMStudio with glm-ocr loaded on port 1234, then:
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/
```
```

(Use whatever wording / heading style already exists in README.md; the goal is parity with the extract_text.py quick-start.)

- [ ] **Step 6: Run all tests to make sure docs edits didn't break anything**

Run: `pytest skills/pdf-doc-extraction/tests/ -v`
Expected: all PASS / SKIP.

- [ ] **Step 7: Commit**

```bash
git add skills/pdf-doc-extraction/SKILL.md skills/pdf-doc-extraction/README.md
git commit -m "docs(pdf-extraction): mark ocr_page.py shipped, add invocation example

Updates SKILL.md model-selection (LMStudio gemma-4-e2b default; Gemini
round-robin deferred to Phase 2b) and tools table. Adds OCR quick-start
to README.md.

Directed-By: V.Stus <v.stoos@gmail.com>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Smoke run on a real PDF with live LMStudio

**Files:**
- No code changes — this is a verification task.

**Pre-conditions:**
- LMStudio is running on `http://localhost:1234`.
- A vision model (`glm-ocr`) is loaded.
- The apalutamide test corpus is on disk.

- [ ] **Step 1: Pick a target PDF and force-OCR one page**

Find a PDF in the apalutamide corpus that has at least 1 problem page (if available) or pick `SUPPL_011_210951Orig1s011lbl.pdf` and force-OCR page 1 via `--pages 1`.

```bash
# Either: real problem pages from the extract sidecar
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/

# Or: force-OCR page 1 to verify the path end-to-end
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --pages 1 \
  --out apalutamide/FDA/
```

- [ ] **Step 2: Verify the output file**

```bash
ls -la apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.ocr.json
```

Expected: file exists, > 200 bytes.

Inspect the file (cat / Read tool) and verify:
- `engine: "lmstudio"`, `model: "glm-ocr"`
- `pages` array has one entry per requested page
- Each entry has `text`, `char_count`, `duration_sec`, `status: "ok"`
- `text` field is non-empty for non-blank pages

- [ ] **Step 3: Run a second time and verify cache hit**

```bash
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --pages 1 \
  --out apalutamide/FDA/
```

Expected: stdout summary shows `pages_skipped_cached: 1`, `pages_processed: 0`, `total_seconds < 0.1`.

- [ ] **Step 4: Verify `.ocr.json` is gitignored or in a gitignored dir**

`apalutamide/` is gitignored — the output should not appear in `git status`.

Run: `git status apalutamide/`
Expected: no output (or "nothing to commit, working tree clean" if checked under that path).

- [ ] **Step 5: Report the smoke result**

Note in the wrap-up: which PDF, which page(s), engine, model, char_count from the response, wall-clock time. No commit — the smoke artifacts are gitignored.

If the smoke run fails (LMStudio not reachable, model not loaded, etc.), document the error in the report and do not block — the unit tests already verify the code path.

---

## Self-Review

**Spec coverage check:**

| Spec section | Plan task(s) | Notes |
|---|---|---|
| CLI contract (flags) | Task 7 | All flags from spec wired in `main()`. |
| Page selection precedence | Task 2 | `select_pages` with `--pages` > `extract.json`. |
| Cache behaviour (skip ok, retry error, --force overrides) | Task 6, Task 7 | `pages_to_process` handles the logic; tests cover all three branches. |
| Output JSON shape | Task 7 | Verified in `test_cli_writes_ocr_json`. |
| Backend interface (LMStudio HTTP) | Task 4 | `transcribe_lmstudio` with stdlib urllib. |
| Prompt content | Task 4 | `OCR_PROMPT` constant. |
| Per-page error containment | Task 5 | `process_pages` catches all exceptions. |
| Test plan (all rows) | Tasks 1–7 | Every test in the spec table has a corresponding step. |
| SKILL.md model-selection update | Task 8 | Table edited inline. |
| README.md update | Task 8 | Quick-start block added. |
| No live HTTP in tests | Tasks 4, 5, 7 | All tests use `patch("urllib.request.urlopen", ...)`. |
| 1-indexed external / 0-indexed internal | Task 3 | Single conversion in `render_page_png`. |
| No new deps | n/a | `requirements.txt` untouched. |
| Smoke verification | Task 9 | Explicit verification task at the end. |

**Placeholder scan:** None. All code blocks contain complete, runnable code.

**Type consistency check:**
- `process_pages` returns `list[dict]`; `merge_with_cache` consumes `new_pages: list[dict]` and `cache.get("pages", [])` (also `list[dict]`). Consistent.
- `pages_to_process` takes `cache: dict | None`; `load_existing_cache` returns `dict | None`. Consistent.
- All page entries carry the same keys: `page_number, text, char_count, duration_sec, status, [error]`. Verified across Tasks 5, 6, 7.
- `select_pages` takes `extract_metadata: dict | None`; main() passes `json.loads(...)` result. Consistent.

**Scope check:** Plan covers Phase 2 OCR pass only. Gemini round-robin (Phase 2b), figure extraction (Phase 3), final markdown assembly (Phase 4) are out of scope.

All checks pass. Ready for execution.
