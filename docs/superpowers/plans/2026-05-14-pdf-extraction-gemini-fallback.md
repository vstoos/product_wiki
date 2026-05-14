# Phase 2b — Gemini Cloud Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `transcribe_gemini` as a sibling backend to `transcribe_lmstudio` in `ocr_page.py`. Wire `--engine gemini` for cloud OCR via the Gemini REST API, with round-robin across (api_key, model) pairs for free-tier rate-limit avoidance.

**Architecture:** Extend the existing single-file CLI. Sibling function, no class abstraction yet. Round-robin happens at the call site (in `process_pages`), keeping `transcribe_gemini` itself stateless. On HTTP 429, advance to the next pair and retry.

**Tech Stack:** Same stdlib-only HTTP (`urllib.request`). Gemini REST `generateContent` endpoint. Gemini's content format (`parts` with `text` + `inline_data`).

**Spec ref:** `docs/superpowers/specs/2026-05-14-pdf-extraction-ocr-pass-design.md` (Phase 2b is the named follow-up).

---

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `skills/pdf-doc-extraction/scripts/ocr_page.py` | Modify | Add `transcribe_gemini`, `_advance_round_robin`, dispatch logic in `process_pages`, `--engine gemini` / `--api-key` / `--gemini-models` CLI flags |
| `skills/pdf-doc-extraction/tests/test_ocr_page.py` | Modify | Add gemini transcribe + round-robin + e2e tests |
| `skills/pdf-doc-extraction/SKILL.md` | Modify | Add gemini row to tools, document `--engine gemini` invocation |
| `skills/pdf-doc-extraction/README.md` | Modify | Add gemini quick-start |

No new deps.

---

### Task 1: `transcribe_gemini` (sibling function + 3 tests)

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Append 3 failing tests to `test_ocr_page.py`**

```python


def test_transcribe_gemini_sends_inline_data_payload():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({
            "candidates": [{"content": {"parts": [{"text": "OCR_TEXT"}]}}]
        })

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ocr_page.transcribe_gemini(
            b"\x89PNG_FAKE",
            api_key="KEY123",
            model="gemma-3-27b-it",
            timeout=60,
            prompt="describe",
        )
    assert result == "OCR_TEXT"
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert "gemma-3-27b-it:generateContent" in captured["url"]
    assert "key=KEY123" in captured["url"]
    parts = captured["body"]["contents"][0]["parts"]
    text_parts = [p for p in parts if "text" in p]
    inline_parts = [p for p in parts if "inline_data" in p]
    assert len(text_parts) == 1 and text_parts[0]["text"] == "describe"
    assert len(inline_parts) == 1
    assert inline_parts[0]["inline_data"]["mime_type"] == "image/png"
    assert inline_parts[0]["inline_data"]["data"]  # non-empty base64


def test_transcribe_gemini_concatenates_multi_part_response():
    # Gemini may emit thinking + answer as separate parts; we take all text.
    body = {"candidates": [{"content": {"parts": [
        {"text": "thinking..."},
        {"text": "ACTUAL ANSWER"},
    ]}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        result = ocr_page.transcribe_gemini(
            b"\x89PNG", api_key="K", model="m", timeout=60, prompt="x",
        )
    # Concatenation order matches part order; the answer is whatever the model emitted last
    assert "ACTUAL ANSWER" in result


def test_transcribe_gemini_omits_text_part_when_prompt_empty():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({
            "candidates": [{"content": {"parts": [{"text": "OUT"}]}}]
        })

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ocr_page.transcribe_gemini(
            b"\x89PNG", api_key="K", model="m", timeout=60, prompt="",
        )
    parts = captured["body"]["contents"][0]["parts"]
    types = ["text" if "text" in p else "inline_data" for p in parts]
    assert types == ["inline_data"]
```

- [ ] **Step 2: Run tests; verify 3 FAIL** with `AttributeError: ... 'transcribe_gemini'`.

- [ ] **Step 3: Append to `scripts/ocr_page.py`**

```python


GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"


def transcribe_gemini(
    image_png_bytes: bytes,
    *,
    api_key: str,
    model: str,
    timeout: int,
    prompt: str = OCR_PROMPT,
) -> str:
    """POST the image to Gemini's generateContent endpoint. Returns text.

    One image per request. If `prompt` is empty, the request is image-only.
    Raises HTTPError on non-2xx responses (caller handles 429 routing).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    parts: list[dict] = []
    if prompt:
        parts.append({"text": prompt})
    parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
    }
    url = GEMINI_ENDPOINT.format(model=model, api_key=api_key)
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    # Gemini returns candidates[0].content.parts as a list; concatenate text parts.
    out_parts = body["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in out_parts if "text" in p)
    return text.strip()
```

- [ ] **Step 4: Run tests; verify 3 PASS**.

- [ ] **Step 5: Run full suite**; expect all green (currently 48 + 3 = 51 passing).

- [ ] **Step 6: Commit**

```
feat(pdf-extraction): transcribe_gemini sibling backend

Stdlib urllib POST to Gemini's generateContent endpoint. Same image-only
behaviour when prompt is empty. Concatenates multi-part responses (Gemini
emits thinking + answer as separate text parts).
```

---

### Task 2: Round-robin dispatcher + 429 retry

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Append failing tests**

```python


def test_gemini_round_robin_advances_on_429():
    import urllib.error

    pairs_seen = []

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        pairs_seen.append((api_key, model))
        if api_key == "K1":
            raise urllib.error.HTTPError("u", 429, "rate limit", None, None)
        return f"ok-from-{api_key}"

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        text = ocr_page._gemini_with_round_robin(
            b"\x89PNG",
            pairs=[("K1", "m1"), ("K2", "m2")],
            timeout=60,
            prompt="x",
        )
    assert text == "ok-from-K2"
    assert pairs_seen == [("K1", "m1"), ("K2", "m2")]


def test_gemini_round_robin_raises_when_all_pairs_429():
    import urllib.error

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        raise urllib.error.HTTPError("u", 429, "rate limit", None, None)

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        with pytest.raises(RuntimeError) as ei:
            ocr_page._gemini_with_round_robin(
                b"\x89PNG",
                pairs=[("K1", "m1"), ("K2", "m2")],
                timeout=60,
                prompt="x",
            )
    assert "all gemini" in str(ei.value).lower()


def test_gemini_round_robin_propagates_non_429_errors():
    import urllib.error

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        raise urllib.error.HTTPError("u", 500, "server error", None, None)

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        with pytest.raises(urllib.error.HTTPError):
            ocr_page._gemini_with_round_robin(
                b"\x89PNG",
                pairs=[("K1", "m1")],
                timeout=60,
                prompt="x",
            )
```

- [ ] **Step 2: Run tests; verify 3 FAIL** with AttributeError.

- [ ] **Step 3: Append helper to `ocr_page.py`** (placed after `transcribe_gemini`)

```python


def _gemini_with_round_robin(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> str:
    """Try each (api_key, model) pair in order. Advance on HTTP 429, raise otherwise.

    Raises RuntimeError if every pair returns 429.
    """
    last_429: Exception | None = None
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
            if e.code == 429:
                last_429 = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs returned 429 ({len(pairs)} tried)"
    ) from last_429
```

- [ ] **Step 4: Run tests; verify 3 PASS**.

- [ ] **Step 5: Run full suite**; expect 54 passing.

- [ ] **Step 6: Commit**

```
feat(pdf-extraction): gemini round-robin with 429 retry

Rotate (api_key, model) pairs; advance on 429 only. Non-429 errors
propagate (caller's per-page containment records them). Exhaustion of
all pairs raises RuntimeError.
```

---

### Task 3: Wire `--engine gemini` into `process_pages` and `main`

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/ocr_page.py`
- Modify: `skills/pdf-doc-extraction/tests/test_ocr_page.py`

- [ ] **Step 1: Append failing tests**

```python


def test_cli_gemini_dispatches_to_gemini_backend(suppl11_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ENV_KEY")
    captured_calls = []

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        captured_calls.append(url)
        if "/v1/models" in url:
            # /v1/models is for LMStudio model check; gemini path doesn't use it
            return _MockResponse({"data": []})
        if "generativelanguage.googleapis.com" in url:
            return _MockResponse({"candidates": [{"content": {"parts": [{"text": "GEM"}]}}]})
        raise AssertionError(f"unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--engine", "gemini",
            "--gemini-models", "gemma-3-27b-it",
            "--skip-model-check",
            "--quiet",
        ])
    assert rc == 0
    gem_calls = [u for u in captured_calls if "generativelanguage" in u]
    assert len(gem_calls) == 1
    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert payload["engine"] == "gemini"
    assert payload["pages"][0]["text"] == "GEM"
    assert payload["pages"][0]["status"] == "ok"


def test_cli_gemini_requires_api_key(suppl11_pdf, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    rc = ocr_page.main([
        "--pdf", str(suppl11_pdf),
        "--pages", "1",
        "--out", str(tmp_path),
        "--engine", "gemini",
        "--gemini-models", "gemma-3-27b-it",
        "--skip-model-check",
        "--quiet",
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err or "--api-key" in err


def test_cli_gemini_requires_models(suppl11_pdf, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    rc = ocr_page.main([
        "--pdf", str(suppl11_pdf),
        "--pages", "1",
        "--out", str(tmp_path),
        "--engine", "gemini",
        "--skip-model-check",
        "--quiet",
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "--gemini-models" in err
```

- [ ] **Step 2: Run tests; verify 3 FAIL**.

- [ ] **Step 3: Update `ocr_page.py`** in 4 places:

**A.** Add `os` import near top:

```python
import os
```

**B.** Update `--engine` choices and add new flags in `main()`:

```python
    parser.add_argument(
        "--engine", default="lmstudio", choices=["lmstudio", "gemini"],
        help="OCR backend",
    )
    # ... existing flags ...
    parser.add_argument(
        "--api-key", action="append", default=None,
        help="Gemini API key. Repeatable for round-robin across multiple keys. "
             "If omitted, falls back to GEMINI_API_KEY env var.",
    )
    parser.add_argument(
        "--gemini-models",
        default=None,
        help="Comma-separated Gemini model names (required for --engine gemini). "
             "Example: 'gemma-3-27b-it,gemma-3-12b-it'.",
    )
```

**C.** In `main()` after `parser.parse_args` and before `process_pages` call: validate + build pairs:

```python
    gemini_pairs: list[tuple[str, str]] = []
    if args.engine == "gemini":
        keys = list(args.api_key or [])
        env_key = os.environ.get("GEMINI_API_KEY")
        if not keys and env_key:
            keys = [env_key]
        if not keys:
            print("error: --engine gemini requires --api-key or GEMINI_API_KEY env var",
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
        # Round-robin pairs: cross product, then rotate per call
        gemini_pairs = [(k, m) for k in keys for m in models]
```

**D.** Update `process_pages` signature and dispatch:

```python
def process_pages(
    *,
    pdf_path: Path,
    page_numbers: list[int],
    dpi: int,
    engine: str = "lmstudio",
    host: str = "http://localhost:1234",
    model: str = "glm-ocr",
    timeout: int = 120,
    prompt: str = OCR_PROMPT,
    gemini_pairs: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Render and transcribe each page. Per-page errors are recorded, not raised."""
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
                # Rotate pairs after each successful call to spread load
                pairs = pairs[1:] + pairs[:1]
            else:
                text = transcribe_lmstudio(
                    png, host=host, model=model, timeout=timeout, prompt=prompt
                )
            results.append({
                "page_number": pn,
                "text": text,
                "char_count": len(text),
                "duration_sec": round(time.monotonic() - t0, 3),
                "status": "ok",
            })
        except Exception as e:  # noqa: BLE001
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

**E.** In `main()`, update the `process_pages(...)` call to pass new args:

```python
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
```

**F.** Skip the LMStudio `check_model_loaded` probe when `args.engine != "lmstudio"`:

```python
    if to_do and args.engine == "lmstudio" and not args.skip_model_check:
        warning = check_model_loaded(host=args.host, model=args.model)
        if warning and not args.quiet:
            print(f"WARNING: {warning}", file=sys.stderr)
```

- [ ] **Step 4: Run tests; verify 3 PASS** + the older `test_process_pages_records_per_page_errors` still passes (it doesn't pass `engine`, so it must default to `"lmstudio"` and continue to work).

- [ ] **Step 5: Run full suite**; expect 57 passing.

- [ ] **Step 6: Commit**

```
feat(pdf-extraction): --engine gemini dispatch with round-robin pairs

main() validates --api-key (or GEMINI_API_KEY env) and --gemini-models,
builds (key, model) cross-product pairs, and passes them to
process_pages. The LMStudio model-check probe is skipped when not using
the lmstudio engine. Exit code 2 on missing key/models.
```

---

### Task 4: Docs

**Files:**
- Modify: `skills/pdf-doc-extraction/SKILL.md`
- Modify: `skills/pdf-doc-extraction/README.md`

- [ ] **Step 1: SKILL.md - update model-selection table OCR row**

Find:
```
| OCR of scanned pages | **`glm-ocr` via LMStudio (≈2B, OCR-specialized, >150 tps on RTX 3090)** | `gemma-4-e2b-it` (2B general vision) or `gemma-4-e4b-it` (4B) after `glm-ocr` produces clearly wrong output twice. Gemini API round-robin is planned for Phase 2b. | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
```

Replace with:
```
| OCR of scanned pages | **`glm-ocr` via LMStudio (≈2B, OCR-specialized, >150 tps on RTX 3090)** | Gemini API free-tier Gemma models via `--engine gemini` when local is unavailable; or `gemma-4-e2b-it`/`gemma-4-e4b-it` via LMStudio for general vision. | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
```

- [ ] **Step 2: SKILL.md - add gemini invocation under "OCR pass (Phase 2)"**

Append after the existing OCR invocation block:

```markdown
**Gemini cloud fallback (Phase 2b)** — when local LMStudio isn't available
or you want a free-tier cloud benchmark:

```bash
export GEMINI_API_KEY=...   # or pass --api-key (repeatable)
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --extract-json <substance>/<AGENCY>/<file>.extract.json \
  --out <substance>/<AGENCY>/ \
  --engine gemini \
  --gemini-models "gemma-3-27b-it,gemma-3-12b-it"
```

The (key, model) cross-product is rotated per page to spread load. On HTTP
429, the dispatcher advances to the next pair and retries; only when every
pair returns 429 does the page record `status: error`.
```

- [ ] **Step 3: README.md - add gemini quick-start block**

After the existing OCR quick-start, add:

```markdown
### Cloud OCR via Gemini (Phase 2b)

When LMStudio isn't available:

```bash
export GEMINI_API_KEY=...
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/<file>.pdf \
  --extract-json apalutamide/FDA/<file>.extract.json \
  --out apalutamide/FDA/ \
  --engine gemini --gemini-models "gemma-3-27b-it,gemma-3-12b-it"
```

Pass `--api-key` multiple times to round-robin across multiple keys for
higher effective throughput on the free tier.
```

- [ ] **Step 4: Run full suite** to confirm no doc-related test breakage.

- [ ] **Step 5: Commit**

```
docs(pdf-extraction): document --engine gemini round-robin

Updates SKILL.md model-selection table and adds Gemini invocation block
to both SKILL.md and README.md.
```

---

## Self-Review

**Spec coverage:**
- "Phase 2b: sibling function + --engine dispatch" → Task 1 (sibling) + Task 3 (dispatch). Round-robin added (was an open spec question; design decision documented above).
- One-image-per-request → preserved (`transcribe_gemini` is a single POST per call).
- Per-page error containment → preserved (`process_pages` catches any exception including RuntimeError from exhaustion).

**Placeholder scan:** None. All code blocks complete.

**Type consistency:**
- `gemini_pairs: list[tuple[str, str]]` used in Tasks 2, 3 — same type.
- `_gemini_with_round_robin` and `transcribe_gemini` signatures match each other's kwarg names.
- `process_pages` keyword-only args; new `engine`, `gemini_pairs` defaulted so existing tests don't need updates.

**Scope check:** 4 tasks, all additions to one file + tests + docs. No refactors. Phase 3 deferred.

Ready for SDD execution.
