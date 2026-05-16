# Phase 3 — Figure Extraction + Vision Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-15-pdf-extraction-figures-and-captions-design.md` (revised second-pass 2026-05-16).

**Goal:** Ship `extract_figures.py` + `caption_figure.py` in the `pdf-doc-extraction` skill so we can pull embedded figure rasters from regulatory PDFs, capture page-ordered verbatim text for Tier-1 grounding + distance-ranked nearby text for the captioner, and produce vision-model captions via structured output (with table-as-figure detection, FOI redaction handling, content-hash idempotency, atomic writes, and an explicit captioning-model denylist).

**Architecture:** Two CLI tools sharing `_vision_backends.py`. Stage 3a (`extract_figures.py`) walks `page.get_images()`, drops header decorations (logged to `dropped_header_decorations[]`), detects `(b)(4)` redactions by pixel statistics, captures `page_text_verbatim` (document-ordered, Tier-1-eligible) + `nearby_text` (captioner-context only), atomically writes `<stem>.figures.json` + `<stem>.assets/figure_pN_fM.png` with `source_pdf_sha256` + `extractor_thresholds_hash` for idempotency. Stage 3b (`caption_figure.py`) verifies sidecar freshness against those hashes, then sends each non-redacted PNG via structured-output mode (`{type, content}`) through Gemini (default) or LMStudio (with `CAPTION_DENYLIST` enforcement), atomically writes descriptions + `captioner: "engine:model@YYYY-MM-DD"` + `prompt_hash` back.

**Tech Stack:** Python 3.11+, PyMuPDF (`fitz`), `urllib.request` for HTTP, `pytest` + `unittest.mock.patch` for tests, the existing `_vision_backends.py` for shared HTTP helpers + new structured-output helpers + shared atomic-write helper.

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `skills/pdf-doc-extraction/scripts/_vision_backends.py` | Modify | Add `CAPTION_PROMPT_TEMPLATE`, `CAPTION_DENYLIST`, `atomic_write_json`, plus structured-output helpers `transcribe_lmstudio_structured` and `transcribe_gemini_structured` returning `(type, content)` tuples. |
| `skills/pdf-doc-extraction/scripts/extract_figures.py` | Create | Phase 3a CLI: walk pages, filter, extract PNGs, write `<stem>.figures.json` atomically with hashes + audit log. |
| `skills/pdf-doc-extraction/scripts/caption_figure.py` | Create | Phase 3b CLI: freshness check, structured-output captioning, atomic write-back with model+date+prompt_hash. |
| `skills/pdf-doc-extraction/tests/test_extract_figures.py` | Create | Unit tests + corpus-calibrated redaction + header-filter audit-log tests + hash/atomic-write tests. |
| `skills/pdf-doc-extraction/tests/test_caption_figure.py` | Create | Unit tests + structured-output parse tests + freshness-check tests + denylist enforcement + rate-budget tests. |
| `skills/pdf-doc-extraction/tests/test_vision_backends.py` | Create | Unit tests for the new shared backends additions. |
| `skills/pdf-doc-extraction/tests/conftest.py` | Modify | Add `multidisc_pdf` fixture for figure-rich corpus. |
| `skills/pdf-doc-extraction/SKILL.md` | Modify | Mark both tools shipped, document Tier-1/Tier-2 contract, model-selection row. |
| `skills/pdf-doc-extraction/README.md` | Modify | Quick-starts. |

---

## Conventions all tasks follow

- **Module loading in tests** matches `test_ocr_page.py` lines 10-21: `importlib.util.spec_from_file_location(...)` + `sys.modules[name] = module` + `_spec.loader.exec_module(module)` — required for `patch.object(module, "name")` to intercept correctly.
- **Re-export pattern** for shared backends in `extract_figures.py` and `caption_figure.py` matches `ocr_page.py` lines 16-32: load `_vision_backends.py` via `importlib.util`, then rebind needed symbols at module top.
- **HTTP is mocked everywhere** via `_MockResponse` + `patch("urllib.request.urlopen", ...)` (see `test_ocr_page.py` lines 75-89).
- **No emojis in source files.** No special unicode in commit messages.
- **Commits are atomic per task** — each task ends with one `git commit`; don't bundle multiple tasks.
- **Don't widen scope inside a task.** If a task surfaces an issue belonging to another task, note it and move on.

---

## Task 1: `_vision_backends.py` — add `CAPTION_PROMPT_TEMPLATE`, `CAPTION_DENYLIST`, `atomic_write_json`

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/_vision_backends.py`
- Create: `skills/pdf-doc-extraction/tests/test_vision_backends.py`

- [ ] **Step 1: Write the failing tests**

Create `skills/pdf-doc-extraction/tests/test_vision_backends.py`:

```python
"""Tests for additions to _vision_backends.py shared across tools."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "_vision_backends.py"
_spec = importlib.util.spec_from_file_location("_vision_backends", SCRIPT)
vb = importlib.util.module_from_spec(_spec)
sys.modules["_vision_backends"] = vb
_spec.loader.exec_module(vb)


# --- CAPTION_PROMPT_TEMPLATE ---

def test_caption_prompt_template_exists():
    assert hasattr(vb, "CAPTION_PROMPT_TEMPLATE")
    assert isinstance(vb.CAPTION_PROMPT_TEMPLATE, str)


def test_caption_prompt_template_has_substitution_keys():
    t = vb.CAPTION_PROMPT_TEMPLATE
    assert "{substance}" in t
    assert "{nearby_text}" in t
    assert "{raw_caption_candidate}" in t


def test_caption_prompt_template_declares_structured_output():
    t = vb.CAPTION_PROMPT_TEMPLATE.lower()
    assert "json" in t
    assert '"type"' in t
    assert '"content"' in t
    assert "figure" in t
    assert "table" in t


def test_caption_prompt_template_values_policy_is_coherent():
    t = vb.CAPTION_PROMPT_TEMPLATE.lower()
    assert "discrete" in t
    assert "continuous" in t


# --- CAPTION_DENYLIST ---

def test_caption_denylist_is_a_set_of_strings():
    assert hasattr(vb, "CAPTION_DENYLIST")
    assert isinstance(vb.CAPTION_DENYLIST, (set, frozenset))
    for m in vb.CAPTION_DENYLIST:
        assert isinstance(m, str)


def test_caption_denylist_contains_known_ocr_specialists():
    assert "glm-ocr" in vb.CAPTION_DENYLIST
    assert "lightonocr-2-1b-ocr-soup" in vb.CAPTION_DENYLIST
    assert "deepseek-ocr" in vb.CAPTION_DENYLIST


# --- atomic_write_json ---

def test_atomic_write_json_creates_file(tmp_path):
    target = tmp_path / "out.json"
    vb.atomic_write_json(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}


def test_atomic_write_json_overwrites_atomically(tmp_path):
    target = tmp_path / "out.json"
    target.write_text(json.dumps({"original": True}), encoding="utf-8")
    vb.atomic_write_json(target, {"replaced": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"replaced": True}


def test_atomic_write_json_uses_tmp_sibling(tmp_path, monkeypatch):
    """Tmp file is a sibling of target. After successful replace, no .tmp left."""
    target = tmp_path / "out.json"
    vb.atomic_write_json(target, {"x": 1})
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_atomic_write_json_leaves_canonical_intact_on_failure(tmp_path, monkeypatch):
    """If os.replace raises, the canonical file is unchanged."""
    target = tmp_path / "out.json"
    target.write_text(json.dumps({"original": True}), encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        vb.atomic_write_json(target, {"replaced": True})
    # Canonical still has original content
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_vision_backends.py -v`

Expected: all tests FAIL — `CAPTION_PROMPT_TEMPLATE`, `CAPTION_DENYLIST`, `atomic_write_json` not defined.

- [ ] **Step 3: Add the three pieces to `_vision_backends.py`**

Open `skills/pdf-doc-extraction/scripts/_vision_backends.py`. After the `OCR_PROMPT = (...)` block (currently ending around line 31), insert:

```python
CAPTION_PROMPT_TEMPLATE = (
    "You will receive a figure image from a regulatory document. Output a JSON\n"
    "object with exactly two fields:\n"
    "  - \"type\": one of \"figure\" or \"table\"\n"
    "  - \"content\": see rules below\n"
    "\n"
    "Context:\n"
    "- Substance: {substance}\n"
    "- Nearby text from the surrounding document: {nearby_text}\n"
    "- Caption candidate (if found): {raw_caption_candidate}\n"
    "\n"
    "Rules for type=\"table\":\n"
    "- Use this type if the image is a scanned table (rows and columns of cell\n"
    "  data with headers, and no plotting elements).\n"
    "- \"content\" is an HTML <table> transcription using rowspan/colspan for\n"
    "  merged cells. Preserve cell text verbatim. No surrounding prose.\n"
    "\n"
    "Rules for type=\"figure\":\n"
    "- Use this type for plots, charts, schematics, photographs, micrographs.\n"
    "- \"content\" is a 3-5 sentence description.\n"
    "- State the figure type (PK plot, dissolution profile, Kaplan-Meier curve,\n"
    "  forest plot, scatter plot, schematic, photograph, etc.) in sentence 1.\n"
    "- State axis labels and units if visible.\n"
    "- Values policy:\n"
    "   * Discrete labeled data points (dissolution % at named timepoints,\n"
    "     mean +/- SD bars with annotated values, table-like overlays):\n"
    "     transcribe the values literally.\n"
    "   * Continuous curves (Kaplan-Meier survival, scatter, dose-response,\n"
    "     concentration-time profiles without per-point labels): describe\n"
    "     shape and inflection points; do NOT interpolate specific values.\n"
    "- Always describe trends and relationships visible in the data.\n"
    "- Be consistent with the caption candidate if one is provided.\n"
    "- Never invent. If the image is unreadable, set content to \"[UNREADABLE]\".\n"
    "\n"
    "Output: a single JSON object, no surrounding prose, no markdown fences.\n"
)


# Captioning-model denylist. Explicit set, NOT a regex (a regex like /ocr/i
# would falsely reject a future general vision model named e.g. "vision-ocr-1").
# The OCR_MODEL_PATTERN regex above stays in place for the Phase 2 prompt-
# selection heuristic, where false positives are harmless.
CAPTION_DENYLIST = frozenset({
    "glm-ocr",
    "lightonocr-2-1b-ocr-soup",
    "deepseek-ocr",
})
```

At the top of the file, add `import os` and `import tempfile` to the existing imports. Then add this helper near the end of the file (after `check_model_loaded`):

```python
def atomic_write_json(path, payload) -> None:
    """Write JSON to `path` atomically via a sibling tmp file + os.replace.

    Crash mid-write leaves the canonical file unchanged. Raises OSError on
    write/replace failure; in that case the caller should NOT assume the
    canonical content was updated.

    Path may be str or pathlib.Path. Payload is anything json.dumps can encode.
    """
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Use NamedTemporaryFile in the target's directory so os.replace is atomic
    # (must be on the same filesystem).
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except Exception:
        # Best-effort cleanup of the tmp file; canonical is unchanged.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_vision_backends.py -v`

Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/_vision_backends.py skills/pdf-doc-extraction/tests/test_vision_backends.py
git commit -m "feat(pdf-extraction): shared backends: CAPTION_PROMPT_TEMPLATE + CAPTION_DENYLIST + atomic_write_json"
```

---

## Task 2: `_vision_backends.py` — structured-output helpers

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/_vision_backends.py`
- Modify: `skills/pdf-doc-extraction/tests/test_vision_backends.py`

- [ ] **Step 1: Write the failing tests**

Append to `skills/pdf-doc-extraction/tests/test_vision_backends.py`:

```python
import json as _json
from unittest.mock import patch


class _MockResponse:
    def __init__(self, body_dict, status: int = 200):
        self._body = _json.dumps(body_dict).encode("utf-8")
        self.status = status
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


# --- transcribe_lmstudio_structured ---

def test_lmstudio_structured_returns_parsed_type_and_content():
    fake_body = {"choices": [{"message": {"content": '{"type":"figure","content":"A PK plot."}'}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t == "figure"
    assert c == "A PK plot."


def test_lmstudio_structured_returns_none_on_parse_failure():
    """Model emitted non-JSON text. Helper returns (None, raw_text), caller decides."""
    fake_body = {"choices": [{"message": {"content": "This is not JSON, sorry."}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t is None
    assert c == "This is not JSON, sorry."


def test_lmstudio_structured_returns_none_on_schema_mismatch():
    """Valid JSON but missing required keys -> (None, raw)."""
    fake_body = {"choices": [{"message": {"content": '{"only_one_field":"oops"}'}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t is None
    assert '"only_one_field"' in c


def test_lmstudio_structured_strips_markdown_fences():
    """Common 4B-model failure mode: wraps JSON in ```json fences."""
    fenced = "```json\n{\"type\":\"figure\",\"content\":\"A plot.\"}\n```"
    fake_body = {"choices": [{"message": {"content": fenced}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t == "figure"
    assert c == "A plot."


def test_lmstudio_structured_sends_json_object_response_format():
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"choices": [{"message": {"content": '{"type":"figure","content":"x"}'}}]})
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vb.transcribe_lmstudio_structured(
            b"FAKE", host="http://localhost:1234", model="gemma-4-e4b-it", timeout=10, prompt="hi",
        )
    assert captured["body"].get("response_format") == {"type": "json_object"}


# --- transcribe_gemini_structured ---

def test_gemini_structured_returns_parsed_type_and_content():
    fake_body = {
        "candidates": [
            {"content": {"parts": [{"text": '{"type":"table","content":"<table>x</table>"}'}]}}
        ]
    }
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    assert t == "table"
    assert c == "<table>x</table>"


def test_gemini_structured_sends_response_schema():
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"candidates": [{"content": {"parts": [{"text": '{"type":"figure","content":"x"}'}]}}]})
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    gen_cfg = captured["body"]["generationConfig"]
    assert gen_cfg["response_mime_type"] == "application/json"
    schema = gen_cfg["response_schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"type", "content"}
    assert "type" in schema["required"] and "content" in schema["required"]


def test_gemini_structured_returns_none_on_parse_failure():
    fake_body = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    assert t is None
    assert c == "not json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_vision_backends.py -v -k "structured"`

Expected: all FAIL — helpers not defined yet.

- [ ] **Step 3: Add the structured-output helpers**

In `skills/pdf-doc-extraction/scripts/_vision_backends.py`, after the `transcribe_gemini` function and before `_gemini_with_round_robin`, add:

```python
import re as _re

_JSON_FENCE_RE = _re.compile(r"^```(?:json)?\s*(.*?)\s*```\s*$", _re.DOTALL | _re.IGNORECASE)


def _parse_structured_response(raw_text: str) -> tuple[str | None, str]:
    """Parse a model's text into (type, content) or (None, raw_text) on failure.

    Strips ```json ... ``` fences (common small-model failure mode), then
    json.loads. Validates {type, content} shape and that type is in
    {"figure", "table"}. On any failure returns (None, raw_text).
    """
    text = raw_text.strip()
    m = _JSON_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, raw_text
    if not isinstance(obj, dict):
        return None, raw_text
    t = obj.get("type")
    c = obj.get("content")
    if t not in ("figure", "table") or not isinstance(c, str):
        return None, raw_text
    return t, c


def transcribe_lmstudio_structured(
    image_png_bytes: bytes,
    *,
    host: str,
    model: str,
    timeout: int,
    prompt: str,
) -> tuple[str | None, str]:
    """Structured-output captioning via LMStudio (OpenAI-compat JSON mode).

    Returns (type, content) on a parseable {type, content} response, else
    (None, raw_text). LMStudio's OpenAI-compat layer supports
    response_format={"type":"json_object"} but not arbitrary JSON Schema
    enforcement, so the schema is also stated in the prompt (which is what
    `prompt` already contains via CAPTION_PROMPT_TEMPLATE).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url=f"{host.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    raw_text = body["choices"][0]["message"]["content"]
    return _parse_structured_response(raw_text)


def transcribe_gemini_structured(
    image_png_bytes: bytes,
    *,
    api_key: str,
    model: str,
    timeout: int,
    prompt: str,
) -> tuple[str | None, str]:
    """Structured-output captioning via Gemini (response_schema enforced).

    Returns (type, content) on parse success, else (None, raw_text).
    Raises urllib HTTPError on non-2xx (caller handles 429 routing).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png", "data": b64}},
    ]
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4096,
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["figure", "table"]},
                    "content": {"type": "string"},
                },
                "required": ["type", "content"],
            },
        },
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
    out_parts = body["candidates"][0]["content"]["parts"]
    raw_text = "".join(p.get("text", "") for p in out_parts if "text" in p)
    return _parse_structured_response(raw_text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_vision_backends.py -v`

Expected: all PASS (the original 9 from Task 1 plus 8 new ones).

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/_vision_backends.py skills/pdf-doc-extraction/tests/test_vision_backends.py
git commit -m "feat(pdf-extraction): structured-output helpers in shared backends"
```

---

## Task 3: Add `multidisc_pdf` fixture

**Files:**
- Modify: `skills/pdf-doc-extraction/tests/conftest.py`

- [ ] **Step 1: Write the failing test**

Append to `skills/pdf-doc-extraction/tests/test_extract_text.py`:

```python
def test_multidisc_fixture_resolves_or_skips(multidisc_pdf):
    """Fixture either points at a real PDF or pytest.skips."""
    assert multidisc_pdf.exists()
    assert multidisc_pdf.suffix == ".pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_text.py::test_multidisc_fixture_resolves_or_skips -v`

Expected: FAIL — `fixture 'multidisc_pdf' not found`.

- [ ] **Step 3: Add the fixture**

Append to `skills/pdf-doc-extraction/tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def multidisc_pdf() -> Path:
    """Figure-rich corpus: 259-page FDA clinical review with PK/KM plots."""
    p = APALUTAMIDE_FDA / "210951Orig1s000MultidisciplineR.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p
```

- [ ] **Step 4: Run test to verify it passes (or skips cleanly)**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_text.py::test_multidisc_fixture_resolves_or_skips -v`

Expected: PASS or SKIP (skip is correct if local fixture is absent — either is acceptable).

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/tests/conftest.py skills/pdf-doc-extraction/tests/test_extract_text.py
git commit -m "test(pdf-extraction): add multidisc_pdf fixture for Phase 3 tests"
```

---

## Task 4: `extract_figures.py` scaffold + substance resolution

**Files:**
- Create: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Create: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariants implemented: `<substance>/metadata.json` preferred, path inference fallback, `(substance, source)` tuple where source ∈ `{"metadata_json", "path_inference", "none"}`.

- [ ] **Step 1: Write the failing tests**

Create `skills/pdf-doc-extraction/tests/test_extract_figures.py`:

```python
"""Tests for extract_figures.py. PDF I/O uses real fixtures where available."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_path = SCRIPTS / "extract_figures.py"
_spec = importlib.util.spec_from_file_location("extract_figures", _path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/extract_figures.py at {_path}. "
        "Task 4 must create it before these tests can pass."
    )
extract_figures = importlib.util.module_from_spec(_spec)
sys.modules["extract_figures"] = extract_figures
_spec.loader.exec_module(extract_figures)


def test_load_substance_metadata_reads_file(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    sub_dir.mkdir()
    (sub_dir / "metadata.json").write_text(
        json.dumps({"inn": "apalutamide", "atc": "L02BB05"}), encoding="utf-8"
    )
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.parent.mkdir()
    pdf.touch()
    md = extract_figures.load_substance_metadata(pdf)
    assert md == {"inn": "apalutamide", "atc": "L02BB05"}


def test_load_substance_metadata_returns_none_when_absent(tmp_path):
    pdf = tmp_path / "lonely.pdf"
    pdf.touch()
    assert extract_figures.load_substance_metadata(pdf) is None


def test_infer_substance_prefers_metadata_json(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    (sub_dir / "FDA").mkdir(parents=True)
    (sub_dir / "metadata.json").write_text(
        json.dumps({"inn": "apalutamide-from-metadata"}), encoding="utf-8"
    )
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name == "apalutamide-from-metadata"
    assert source == "metadata_json"


def test_infer_substance_falls_back_to_path(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    (sub_dir / "FDA").mkdir(parents=True)
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name == "apalutamide"
    assert source == "path_inference"


def test_infer_substance_returns_none_source_when_both_missing(tmp_path):
    pdf = tmp_path / "random" / "X.pdf"
    pdf.parent.mkdir()
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name is None
    assert source == "none"


def test_infer_substance_path_uses_recognized_agency_dirs():
    """Substance name is the directory immediately above any AGENCY dir."""
    p = Path("c:/tmp/roxadustat/EMA/X.pdf")
    # Use a synthesized path; load_substance_metadata won't find anything.
    name, source = extract_figures.infer_substance(p)
    assert name == "roxadustat"
    assert source == "path_inference"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v`

Expected: `ModuleNotFoundError` from the spec_from_file_location guard.

- [ ] **Step 3: Create the scaffold**

Create `skills/pdf-doc-extraction/scripts/extract_figures.py`:

```python
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


def main(argv: list[str] | None = None) -> int:
    """Stub - populated in Task 10."""
    raise NotImplementedError("main() implemented in Task 10")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v`

Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): scaffold extract_figures with substance resolution"
```

---

## Task 5: `is_header_decoration` filter

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
def test_is_header_decoration_top_band_short():
    """Bbox in top 5% with 5% height -> agency logo, drop."""
    bbox = (0.10, 0.02, 0.30, 0.07)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is True


def test_is_header_decoration_below_band():
    """Bbox in middle of page -> keep."""
    bbox = (0.10, 0.40, 0.50, 0.70)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False


def test_is_header_decoration_top_but_tall():
    """Bbox starts near top but is tall (real figure spanning header zone) -> keep."""
    bbox = (0.10, 0.05, 0.50, 0.40)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False


def test_is_header_decoration_below_top_band_but_short():
    """Below top band but short -> keep (not a logo, just a small figure)."""
    bbox = (0.10, 0.30, 0.30, 0.34)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k header_decoration`

Expected: 4 FAIL — `AttributeError: 'is_header_decoration'`.

- [ ] **Step 3: Implement `is_header_decoration`**

In `extract_figures.py`, after `infer_substance`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k header_decoration`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): add is_header_decoration filter"
```

---

## Task 6: `is_redaction` pixel-statistics detector

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariant: defaults ship from FDA `(b)(4)` literature norms (gray fill ~`#CCCCCC`, std-dev < 15, mean < 245, area > 400 px). Calibration corpus `KNOWN_REDACTIONS` is seeded post-implementation; the test below documents the chicken-and-egg path but does NOT block on hand-labelled data.

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
def _make_uniform_png(width: int, height: int, gray_level: int) -> bytes:
    """Synthesize a uniform-gray PNG via fitz.Pixmap (no PIL dep)."""
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, (gray_level, gray_level, gray_level))
    return pix.tobytes("png")


def _make_noisy_png(width: int, height: int) -> bytes:
    """Synthesize a high-variance PNG (chequerboard)."""
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    for y in range(height):
        for x in range(width):
            v = 255 if (x // 4 + y // 4) % 2 == 0 else 0
            pix.set_pixel(x, y, (v, v, v))
    return pix.tobytes("png")


def test_is_redaction_uniform_gray():
    png = _make_uniform_png(40, 40, gray_level=200)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is True


def test_is_redaction_real_figure_negative():
    png = _make_noisy_png(40, 40)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


def test_is_redaction_too_small_negative():
    """Below min_area_px: don't flag (could be a tiny icon)."""
    png = _make_uniform_png(10, 10, gray_level=200)  # 100 < 400
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


def test_is_redaction_white_too_bright_negative():
    """Pure white = page background, not a redaction."""
    png = _make_uniform_png(40, 40, gray_level=255)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


# Calibration corpus is seeded post-implementation per spec
# ("Chicken-and-egg note"). Until then this list is empty.
KNOWN_REDACTIONS: list[tuple[str, int]] = []


@pytest.mark.skipif(not KNOWN_REDACTIONS, reason="KNOWN_REDACTIONS seeded post-implementation")
def test_is_redaction_against_known_corpus_redactions():
    """Pin against known (b)(4) pages. Seeded by running extract_figures.py
    on the apalutamide corpus once and recording observed redactions."""
    # Future: load page, extract figure at known bbox, assert is_redaction True
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k redaction`

Expected: 4 FAIL (`AttributeError`), 1 SKIP (calibration placeholder).

- [ ] **Step 3: Implement `is_redaction`**

In `extract_figures.py`, after `is_header_decoration`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k redaction`

Expected: 4 PASS, 1 SKIP.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): add is_redaction pixel-stats detector (literature defaults)"
```

---

## Task 7: `page_text_verbatim` + `nearby_text_for_bbox`

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariants:
- `page_text_verbatim`: document-ordered, Tier-1-eligible, via `page.get_text()`.
- `nearby_text_for_bbox`: page-wide capture, ranked closest-first by distance to figure bbox, captioner-context only (NOT Tier-1).
- Both fields attached to every figure on the page.

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
def test_page_text_verbatim_returns_page_get_text():
    class _FakePage:
        def get_text(self, mode="text"):
            if mode == "text":
                return "Page one full text in document order.\nLine two.\n"
            return None
    assert (
        extract_figures.page_text_verbatim(_FakePage())
        == "Page one full text in document order.\nLine two.\n"
    )


def test_nearby_text_captures_caption_candidate():
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [
                    (50, 100, 550, 130, "Figure 2. Plasma concentration over 24h.", 0, 0),
                    (50, 200, 550, 600, "[image]", 1, 1),
                    (50, 650, 550, 700, "Source: Sponsor analysis.", 2, 0),
                ]
            return "Figure 2. Plasma concentration over 24h.\n[image]\nSource: Sponsor analysis.\n"

    bbox_pdf = (50, 200, 550, 600)
    nearby, candidate = extract_figures.nearby_text_for_bbox(
        _FakePage(), bbox_pdf, max_chars=600
    )
    assert "Figure 2" in candidate
    assert "Plasma concentration" in candidate
    assert ("Plasma" in nearby) or ("Source" in nearby)


def test_nearby_text_ranks_closest_first():
    """Closer block appears earlier in nearby_text."""
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [
                    # Far-above block
                    (50, 10, 550, 40, "FAR_ABOVE_TEXT", 0, 0),
                    # Just-above block (closest)
                    (50, 380, 550, 400, "JUST_ABOVE_TEXT", 1, 0),
                    # Figure region
                    (50, 410, 550, 600, "[image]", 2, 1),
                    # Just-below block (close)
                    (50, 610, 550, 640, "JUST_BELOW_TEXT", 3, 0),
                ]
            return "irrelevant for this test"

    bbox_pdf = (50, 410, 550, 600)
    nearby, _ = extract_figures.nearby_text_for_bbox(
        _FakePage(), bbox_pdf, max_chars=10000
    )
    just_above_idx = nearby.find("JUST_ABOVE_TEXT")
    far_above_idx = nearby.find("FAR_ABOVE_TEXT")
    assert just_above_idx != -1 and far_above_idx != -1
    assert just_above_idx < far_above_idx, (
        f"closest-first violated: {nearby!r}"
    )


def test_nearby_text_truncates_to_max_chars():
    long = "X" * 5000
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [(50, 100, 550, 130, long, 0, 0)]
            return long

    nearby, _ = extract_figures.nearby_text_for_bbox(
        _FakePage(), (50, 200, 550, 600), max_chars=600
    )
    assert len(nearby) <= 600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "page_text_verbatim or nearby_text"`

Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the helpers**

In `extract_figures.py`, after `is_redaction`, add:

```python
import re

CAPTION_PREFIX_RE = re.compile(r"^\s*(figure|fig\.|table)\s*\d+", re.IGNORECASE)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "page_text_verbatim or nearby_text"`

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): page_text_verbatim (Tier-1) + nearby_text (captioner ctx)"
```

---

## Task 8: `extract_figures_from_page` per-page workhorse

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariants: returns `(figures, dropped_header_decorations)`. Each figure dict carries `page_text_verbatim` (shared across all figures on a page, computed once) + `nearby_text` (per-figure, distance-ranked) + `raw_caption_candidate` + redaction flag + image bytes.

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
import fitz  # noqa: E402 -- after sys.modules registration above


def test_extract_figures_from_page_returns_pair(multidisc_pdf):
    """Returns (figures, dropped_header_decorations) tuple."""
    with fitz.open(multidisc_pdf) as doc:
        out = extract_figures.extract_figures_from_page(
            doc, 0,
            header_fraction=0.15,
            header_min_height=0.08,
            redaction_thresholds=(15.0, 245.0),
            min_area_px=400,
            nearby_text_max_chars=2500,
        )
    assert isinstance(out, tuple) and len(out) == 2
    figures, dropped = out
    assert isinstance(figures, list)
    assert isinstance(dropped, list)


def test_extract_figures_from_page_attaches_page_text_verbatim_to_every_figure(multidisc_pdf):
    """If a page has multiple figures, page_text_verbatim is identical across them."""
    with fitz.open(multidisc_pdf) as doc:
        page_count = doc.page_count
        for i in range(min(220, page_count)):
            figures, _ = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if len(figures) >= 2:
                texts = {f["page_text_verbatim"] for f in figures}
                assert len(texts) == 1, "page_text_verbatim must be shared per page"
                return
    pytest.skip("no page with 2+ figures in first 220 pages")


def test_extract_figures_from_page_returns_required_keys(multidisc_pdf):
    """Each figure dict has every key the downstream JSON schema needs."""
    required = {
        "page_number", "page_index_within", "bbox_normalized", "image_bytes",
        "raw_caption_candidate", "nearby_text", "page_text_verbatim",
        "redacted", "width_px", "height_px", "size_bytes", "extraction_method",
    }
    with fitz.open(multidisc_pdf) as doc:
        for i in range(min(220, doc.page_count)):
            figures, _ = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if figures:
                missing = required - set(figures[0].keys())
                assert not missing, f"missing keys: {missing}"
                return
    pytest.skip("no figures found in first 220 pages of MultidisciplineR")


def test_extract_figures_from_page_dropped_decoration_shape(multidisc_pdf):
    """When the filter drops a candidate, the entry has the documented shape."""
    with fitz.open(multidisc_pdf) as doc:
        for i in range(min(220, doc.page_count)):
            _, dropped = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if dropped:
                d = dropped[0]
                for k in ("page_number", "bbox_normalized", "size_bytes", "reason"):
                    assert k in d, f"missing dropped-key: {k}"
                assert d["reason"] == "header_band"
                return
    pytest.skip("no header decorations dropped in first 220 pages")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "extract_figures_from_page"`

Expected: FAIL — `extract_figures_from_page` not defined.

- [ ] **Step 3: Implement `extract_figures_from_page`**

In `extract_figures.py`, after `nearby_text_for_bbox`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "extract_figures_from_page"`

Expected: tests PASS (or SKIP if `multidisc_pdf` fixture missing).

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): extract_figures_from_page with dropped-decorations audit log"
```

---

## Task 9: `write_figure_assets` + `hash_thresholds` + `compute_pdf_sha256`

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariants:
- `write_figure_assets`: write PNGs for non-redacted figures, strip `image_bytes` from returned dicts, populate `asset_path`/`asset_sha256`/`captioner`/`description`/`content_type`/`description_tier`/`*_tier` markers/`figure_id`.
- `hash_thresholds`: SHA-256 of JSON-canonicalized dict.
- `compute_pdf_sha256`: prefer `<stem>.meta.json::sha256` from Phase 1 if present; else compute.

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
def test_write_figure_assets_writes_non_redacted_pngs(tmp_path):
    figs = [
        {
            "page_number": 47, "page_index_within": 1,
            "bbox_normalized": [0.1, 0.3, 0.8, 0.6],
            "image_bytes": b"\x89PNG\r\n\x1a\nFAKE_OK",
            "raw_caption_candidate": "Figure 2.",
            "nearby_text": "context",
            "page_text_verbatim": "Page 47 full text.",
            "redacted": False,
            "width_px": 100, "height_px": 80, "size_bytes": 13,
            "extraction_method": "native_extract_image",
        },
        {
            "page_number": 51, "page_index_within": 1,
            "bbox_normalized": [0.4, 0.2, 0.7, 0.4],
            "image_bytes": b"REDACTED-BYTES",
            "raw_caption_candidate": "(b)(4)",
            "nearby_text": "",
            "page_text_verbatim": "Page 51 full text including (b)(4).",
            "redacted": True,
            "width_px": 50, "height_px": 30, "size_bytes": 14,
            "extraction_method": "native_extract_image",
        },
    ]
    assets_dir = tmp_path / "stem.assets"
    out = extract_figures.write_figure_assets(figs, assets_dir)

    assert len(out) == 2
    # non-redacted: file written, asset_path set, asset_sha256 set, image_bytes stripped
    a = out[0]
    assert a["asset_path"] == "stem.assets/figure_p47_f1.png"
    assert (assets_dir / "figure_p47_f1.png").exists()
    assert isinstance(a["asset_sha256"], str) and len(a["asset_sha256"]) == 64
    assert "image_bytes" not in a
    assert a["figure_id"] == "p47_f1"
    assert a["captioner"] is None
    assert a["description"] is None
    assert a["content_type"] is None
    assert a["description_tier"] is None
    assert a["raw_caption_candidate_tier"] == 1
    assert a["page_text_verbatim_tier"] == 1
    assert a["nearby_text_tier"] is None
    assert a["prompt_hash"] is None
    assert a["error"] is None

    # redacted: no file, asset_path None, pre-filled redaction values
    r = out[1]
    assert r["asset_path"] is None
    assert not (assets_dir / "figure_p51_f1.png").exists()
    assert "image_bytes" not in r
    assert r["redacted"] is True
    assert r["captioner"] == "skipped:redacted"
    assert r["description"] == "[REDACTED: (b)(4)]"
    assert r["content_type"] == "redaction"
    assert r["description_tier"] is None
    assert r["raw_caption_candidate_tier"] == 1
    assert r["page_text_verbatim_tier"] == 1
    assert r["nearby_text_tier"] is None


def test_hash_thresholds_is_deterministic():
    h1 = extract_figures.hash_thresholds({"a": 1, "b": 2})
    h2 = extract_figures.hash_thresholds({"b": 2, "a": 1})  # key order irrelevant
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 64  # sha256 hex


def test_hash_thresholds_changes_with_value():
    h1 = extract_figures.hash_thresholds({"x": 0.15})
    h2 = extract_figures.hash_thresholds({"x": 0.16})
    assert h1 != h2


def test_compute_pdf_sha256_prefers_meta_json(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"DUMMY PDF")
    meta = tmp_path / "doc.meta.json"
    meta.write_text(json.dumps({"sha256": "deadbeef" * 8}), encoding="utf-8")
    assert extract_figures.compute_pdf_sha256(pdf) == "deadbeef" * 8


def test_compute_pdf_sha256_computes_when_meta_absent(tmp_path):
    import hashlib
    pdf = tmp_path / "doc.pdf"
    body = b"REAL CONTENT"
    pdf.write_bytes(body)
    assert extract_figures.compute_pdf_sha256(pdf) == hashlib.sha256(body).hexdigest()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "write_figure_assets or hash_thresholds or compute_pdf_sha256"`

Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the three helpers**

In `extract_figures.py`, after `extract_figures_from_page`, add:

```python
import hashlib
from datetime import datetime, timezone


def hash_thresholds(thresholds: dict) -> str:
    """SHA-256 hex of a JSON-canonical thresholds dict (key-order invariant)."""
    canon = json.dumps(thresholds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


def compute_pdf_sha256(pdf_path: Path) -> str:
    """Prefer <stem>.meta.json::sha256 if present (cheap); else hash the PDF."""
    meta = pdf_path.with_suffix(pdf_path.suffix + ".meta.json")
    # Phase 1 actually writes <stem>.meta.json (stripping .pdf). Try both.
    candidates = [
        meta,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k "write_figure_assets or hash_thresholds or compute_pdf_sha256"`

Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): write_figure_assets + hash_thresholds + compute_pdf_sha256"
```

---

## Task 10: `extract_figures.py` main CLI

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/extract_figures.py`
- Modify: `skills/pdf-doc-extraction/tests/test_extract_figures.py`

Spec invariants:
- atomic write via `_vision_backends.atomic_write_json`
- sidecar carries `schema_version: "1.0"`, `source_pdf_sha256`, `extractor_version`, `extractor_thresholds`, `extractor_thresholds_hash`, `substance`, `substance_source`, `page_count`, `figure_count`, `redacted_count`, `dropped_header_decorations[]`, `figures[]`
- `--force` rewrites; otherwise skip-if-exists
- `_vision_backends` symbols loaded via the same re-export pattern as `ocr_page.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_extract_figures.py`:

```python
def test_cli_writes_full_sidecar_shape(multidisc_pdf, tmp_path):
    rc = extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    # Required top-level fields
    for k in (
        "schema_version", "source_file", "source_pdf_sha256",
        "extraction_date", "extractor_version", "extractor_thresholds",
        "extractor_thresholds_hash", "substance", "substance_source",
        "page_count", "figure_count", "redacted_count",
        "dropped_header_decorations", "figures",
    ):
        assert k in payload, f"missing top-level key: {k}"
    assert payload["schema_version"] == "1.0"
    assert payload["page_count"] >= 100
    assert len(payload["source_pdf_sha256"]) == 64
    assert len(payload["extractor_thresholds_hash"]) == 64


def test_cli_writes_assets_dir(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assets_dir = tmp_path / f"{multidisc_pdf.stem}.assets"
    if assets_dir.exists():
        pngs = list(assets_dir.glob("figure_p*_f*.png"))
        # Lower bound from spec Coverage table; actual seeded later.
        assert len(pngs) >= 1


def test_cli_skips_existing_without_force(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    first_mtime = json_path.stat().st_mtime

    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert json_path.stat().st_mtime == first_mtime


def test_cli_force_rewrites(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    first_mtime = json_path.stat().st_mtime

    # Force needs visible mtime change; sleep impractical, just touch and re-run
    import os, time
    os.utime(json_path, (first_mtime - 10, first_mtime - 10))
    pre_force_mtime = json_path.stat().st_mtime

    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--force",
        "--quiet",
    ])
    assert json_path.stat().st_mtime > pre_force_mtime


def test_cli_different_thresholds_produce_different_hash(multidisc_pdf, tmp_path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(out_a),
        "--header-fraction", "0.15",
        "--quiet",
    ])
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(out_b),
        "--header-fraction", "0.25",
        "--quiet",
    ])
    pa = json.loads((out_a / f"{multidisc_pdf.stem}.figures.json").read_text())
    pb = json.loads((out_b / f"{multidisc_pdf.stem}.figures.json").read_text())
    assert pa["extractor_thresholds_hash"] != pb["extractor_thresholds_hash"]


def test_cli_writes_atomically(multidisc_pdf, tmp_path, monkeypatch):
    """If atomic_write_json's os.replace fails, canonical file is unchanged."""
    # First run writes a valid sidecar
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    original = json_path.read_text(encoding="utf-8")

    # Re-run with --force but patch os.replace to fail mid-write
    import os as _os
    def boom(src, dst):
        raise OSError("simulated disk error")
    monkeypatch.setattr(_os, "replace", boom)

    with pytest.raises(OSError):
        extract_figures.main([
            "--pdf", str(multidisc_pdf),
            "--out", str(tmp_path),
            "--force",
            "--quiet",
        ])
    assert json_path.read_text(encoding="utf-8") == original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v -k cli`

Expected: FAIL — `main()` is `NotImplementedError`.

- [ ] **Step 3: Wire the re-export + implement `main`**

At the top of `extract_figures.py`, replace the existing `import fitz` block (and below the docstring) with this re-export pattern, then add the constants and `main`:

In `extract_figures.py`, REPLACE the section between the docstring and `AGENCY_DIRS = {...}` with:

```python
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
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
```

Then REPLACE the existing `main()` stub at the bottom with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_extract_figures.py -v`

Expected: all PASS (or SKIP if `multidisc_pdf` missing).

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_figures.py skills/pdf-doc-extraction/tests/test_extract_figures.py
git commit -m "feat(pdf-extraction): wire extract_figures CLI with hashes + atomic write"
```

---

## Task 11: `caption_figure.py` scaffold + helpers

**Files:**
- Create: `skills/pdf-doc-extraction/scripts/caption_figure.py`
- Create: `skills/pdf-doc-extraction/tests/test_caption_figure.py`

Spec invariants:
- `render_prompt(*, substance, nearby_text, raw_caption_candidate) -> str` substitutes into `CAPTION_PROMPT_TEMPLATE`, dropping blank context bullets cleanly.
- `compute_prompt_hash(rendered_prompt) -> str` is `sha256[:16]`.
- `validate_captioning_model(engine, model) -> str | None` enforces `CAPTION_DENYLIST` for engine=lmstudio.

- [ ] **Step 1: Write the failing tests**

Create `skills/pdf-doc-extraction/tests/test_caption_figure.py`:

```python
"""Tests for caption_figure.py. HTTP mocked; no live model calls."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_path = SCRIPTS / "caption_figure.py"
_spec = importlib.util.spec_from_file_location("caption_figure", _path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/caption_figure.py at {_path}. "
        "Task 11 must create it before these tests can pass."
    )
caption_figure = importlib.util.module_from_spec(_spec)
sys.modules["caption_figure"] = caption_figure
_spec.loader.exec_module(caption_figure)


# --- render_prompt ---

def test_render_prompt_full_substitution():
    out = caption_figure.render_prompt(
        substance="apalutamide",
        nearby_text="Plasma concentration",
        raw_caption_candidate="Figure 2. PK profile.",
    )
    assert "apalutamide" in out
    assert "Plasma concentration" in out
    assert "Figure 2. PK profile." in out
    assert "{substance}" not in out
    assert "{nearby_text}" not in out
    assert "{raw_caption_candidate}" not in out


def test_render_prompt_drops_substance_when_none():
    out = caption_figure.render_prompt(
        substance=None,
        nearby_text="some context",
        raw_caption_candidate="Figure 1.",
    )
    assert "Substance:" not in out
    assert "some context" in out


def test_render_prompt_drops_empty_nearby_and_candidate():
    out = caption_figure.render_prompt(
        substance="apalutamide",
        nearby_text="",
        raw_caption_candidate="",
    )
    assert "Nearby text" not in out
    assert "Caption candidate" not in out
    assert "apalutamide" in out


# --- compute_prompt_hash ---

def test_compute_prompt_hash_is_deterministic():
    a = caption_figure.compute_prompt_hash("hello world")
    b = caption_figure.compute_prompt_hash("hello world")
    assert a == b
    assert len(a) == 16


def test_compute_prompt_hash_differs_for_different_input():
    a = caption_figure.compute_prompt_hash("hello world")
    b = caption_figure.compute_prompt_hash("hello world.")
    assert a != b


# --- validate_captioning_model ---

def test_validate_captioning_model_rejects_glm_ocr():
    err = caption_figure.validate_captioning_model("lmstudio", "glm-ocr")
    assert err is not None
    assert "general vision" in err.lower() or "denylist" in err.lower()


def test_validate_captioning_model_rejects_lightonocr():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "lightonocr-2-1b-ocr-soup"
    ) is not None


def test_validate_captioning_model_rejects_deepseek_ocr():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "deepseek-ocr"
    ) is not None


def test_validate_captioning_model_accepts_gemma_4b():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "gemma-4-e4b-it"
    ) is None


def test_validate_captioning_model_ignores_engine_gemini():
    """Denylist applies to LMStudio engine only (Gemini doesn't serve those models)."""
    assert caption_figure.validate_captioning_model(
        "gemini", "glm-ocr"  # nonsense for gemini but not our concern here
    ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v`

Expected: `ModuleNotFoundError` from the loader guard.

- [ ] **Step 3: Create the scaffold**

Create `skills/pdf-doc-extraction/scripts/caption_figure.py`:

```python
"""Caption extracted figures via a vision model (Phase 3b).

Reads <stem>.figures.json (produced by extract_figures.py), verifies
freshness via source_pdf_sha256 + extractor_thresholds_hash, sends each
non-redacted figure PNG to a vision backend in structured-output mode
({type, content}), and atomically writes descriptions + provenance back.

Usage:
  python caption_figure.py --figures-json <stem>.figures.json
"""
from __future__ import annotations

# Re-export from shared backends (same pattern as ocr_page.py).
import importlib.util as _ilu
from pathlib import Path as _Path
import sys as _sys

_vb_path = _Path(__file__).resolve().parent / "_vision_backends.py"
_vb_spec = _ilu.spec_from_file_location("_vision_backends", _vb_path)
_vision_backends = _ilu.module_from_spec(_vb_spec)
_sys.modules["_vision_backends"] = _vision_backends
_vb_spec.loader.exec_module(_vision_backends)

CAPTION_PROMPT_TEMPLATE = _vision_backends.CAPTION_PROMPT_TEMPLATE
CAPTION_DENYLIST = _vision_backends.CAPTION_DENYLIST
atomic_write_json = _vision_backends.atomic_write_json
transcribe_lmstudio_structured = _vision_backends.transcribe_lmstudio_structured
transcribe_gemini_structured = _vision_backends.transcribe_gemini_structured

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def render_prompt(
    *,
    substance: str | None,
    nearby_text: str,
    raw_caption_candidate: str,
) -> str:
    """Substitute into CAPTION_PROMPT_TEMPLATE; drop empty Context bullets.

    The template has three "Context:" bullets. Any bullet whose value is
    empty/None is removed entirely (line + newline) so the prompt does not
    show "Substance: None" or hanging colons.
    """
    out = CAPTION_PROMPT_TEMPLATE.format(
        substance=substance or "",
        nearby_text=nearby_text or "",
        raw_caption_candidate=raw_caption_candidate or "",
    )
    drop_patterns = [
        r"^- Substance:\s*$\n",
        r"^- Nearby text from the surrounding document:\s*$\n",
        r"^- Caption candidate \(if found\):\s*$\n",
    ]
    for pat in drop_patterns:
        out = re.sub(pat, "", out, flags=re.MULTILINE)
    return out


def compute_prompt_hash(rendered_prompt: str) -> str:
    """First 16 hex chars of sha256(rendered_prompt). Audit-trail identifier."""
    return hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()[:16]


def validate_captioning_model(engine: str, model: str) -> str | None:
    """Return error string if engine=lmstudio + model in CAPTION_DENYLIST; else None.

    Gemini side doesn't serve those models so the check is engine-conditional.
    """
    if engine == "lmstudio" and model in CAPTION_DENYLIST:
        return (
            f"refusing to use OCR-specialized model {model!r} for captioning "
            f"(in CAPTION_DENYLIST). Use a general vision model like "
            f"'gemma-4-e2b-it' or 'gemma-4-e4b-it' for LMStudio, or "
            f"'gemma-4-31b-it' for the default Gemini path."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    """Implemented in Task 14."""
    raise NotImplementedError("main() implemented in Task 14")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v`

Expected: all 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/caption_figure.py skills/pdf-doc-extraction/tests/test_caption_figure.py
git commit -m "feat(pdf-extraction): caption_figure scaffold + prompt/hash/denylist helpers"
```

---

## Task 12: `check_sidecar_freshness`

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/caption_figure.py`
- Modify: `skills/pdf-doc-extraction/tests/test_caption_figure.py`

Spec invariant: `check_sidecar_freshness(sidecar_payload, pdf_path, current_thresholds_hash) -> str | None`. Returns None if fresh; else a diagnostic string. Computes the current PDF sha256 itself (via `extract_figures.compute_pdf_sha256` reused — but `caption_figure` shouldn't depend on `extract_figures`; reimplement inline).

- [ ] **Step 1: Write the failing tests**

Append to `test_caption_figure.py`:

```python
def test_check_sidecar_freshness_passes_when_hashes_match(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"PDF BODY")
    sidecar = {
        "source_pdf_sha256": caption_figure._sha256_file(pdf),
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    assert caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8
    ) is None


def test_check_sidecar_freshness_fails_when_pdf_changed(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"NEW PDF BODY")
    sidecar = {
        "source_pdf_sha256": "0" * 64,  # stale
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8
    )
    assert diag is not None
    assert "sha256" in diag.lower() or "pdf" in diag.lower()


def test_check_sidecar_freshness_fails_when_thresholds_differ(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"PDF BODY")
    sidecar = {
        "source_pdf_sha256": caption_figure._sha256_file(pdf),
        "extractor_thresholds_hash": "old" + "0" * 61,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="new" + "0" * 61,
    )
    assert diag is not None
    assert "threshold" in diag.lower()


def test_check_sidecar_freshness_handles_missing_pdf(tmp_path):
    """If the source PDF is gone, treat as stale with a clear diagnostic."""
    pdf = tmp_path / "doc.pdf"  # not created
    sidecar = {
        "source_pdf_sha256": "0" * 64,
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8,
    )
    assert diag is not None
    assert "missing" in diag.lower() or "not found" in diag.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v -k freshness`

Expected: FAIL.

- [ ] **Step 3: Implement `check_sidecar_freshness` + `_sha256_file`**

In `caption_figure.py`, after `validate_captioning_model`:

```python
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_pdf_path(sidecar: dict, figures_json_path: Path) -> Path:
    """Resolve the source PDF path from sidecar metadata, assuming it sits
    alongside the figures.json."""
    source_file = sidecar.get("source_file") or ""
    return figures_json_path.parent / source_file


def check_sidecar_freshness(
    sidecar: dict,
    *,
    pdf_path: Path,
    current_thresholds_hash: str,
) -> str | None:
    """Return None if sidecar is fresh; else a human-readable diagnostic.

    Checks:
      - The source PDF exists at pdf_path
      - PDF sha256 matches sidecar.source_pdf_sha256
      - current_thresholds_hash matches sidecar.extractor_thresholds_hash

    A diagnostic is returned (not raised) so the caller can decide whether
    to refuse, warn, or proceed (--force / --accept-stale).
    """
    if not pdf_path.is_file():
        return f"source PDF missing at {pdf_path} (sidecar expects this file)"

    sidecar_sha = sidecar.get("source_pdf_sha256")
    if not isinstance(sidecar_sha, str) or len(sidecar_sha) != 64:
        return "sidecar missing valid source_pdf_sha256"
    current_sha = _sha256_file(pdf_path)
    if current_sha != sidecar_sha:
        return (
            f"PDF sha256 mismatch: sidecar={sidecar_sha[:12]}... "
            f"current={current_sha[:12]}... (re-run extract_figures.py)"
        )

    sidecar_thresh = sidecar.get("extractor_thresholds_hash")
    if sidecar_thresh != current_thresholds_hash:
        return (
            f"thresholds hash mismatch: sidecar={sidecar_thresh!r:.16}... "
            f"current={current_thresholds_hash[:12]}... (re-run extract_figures.py "
            f"with the new thresholds, or pass --accept-stale)"
        )
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v -k freshness`

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/caption_figure.py skills/pdf-doc-extraction/tests/test_caption_figure.py
git commit -m "feat(pdf-extraction): check_sidecar_freshness with sha256 + thresholds-hash gates"
```

---

## Task 13: `caption_one_figure` + `process_figures` + Gemini round-robin

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/caption_figure.py`
- Modify: `skills/pdf-doc-extraction/tests/test_caption_figure.py`

Spec invariants:
- structured-output backends return `(type, content)` or `(None, raw)` — caller sets `content_type="error"` + `error="parse failed: <raw_preview>"` on `(None, raw)`.
- `captioner` is `"engine:model@YYYY-MM-DD"` on success, `"engine:error"` on exception, `"engine:parse_error"` on `(None, raw)`, `"skipped:redacted"` pre-filled.
- `prompt_hash` set on every captioned figure.
- `description_tier` set to `2` on success; `null` on error/redaction.
- Gemini round-robin advances pairs on HTTP 429; raises `RuntimeError` when all pairs exhausted.
- `process_figures` honours skip-if-done (unless `--force`) and `rate_budget_calls`.

- [ ] **Step 1: Write the failing tests**

Append to `test_caption_figure.py`:

```python
def _seed_assets(tmp_path: Path) -> Path:
    """Create a minimal assets dir with one PNG."""
    assets = tmp_path / "stem.assets"
    assets.mkdir(parents=True)
    (assets / "figure_p1_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return tmp_path


def _make_figure(asset_rel: str | None, *, redacted: bool = False,
                 captioner: str | None = None,
                 description: str | None = None) -> dict:
    return {
        "figure_id": "p1_f1",
        "page_number": 1,
        "page_index_within": 1,
        "asset_path": asset_rel,
        "asset_sha256": "x" * 64 if asset_rel else None,
        "bbox_normalized": [0.1, 0.2, 0.8, 0.6],
        "extraction_method": "native_extract_image",
        "size_bytes": 16,
        "width_px": 100,
        "height_px": 80,
        "raw_caption_candidate": "Figure 1." if not redacted else "(b)(4)",
        "raw_caption_candidate_tier": 1,
        "page_text_verbatim": "Page 1 full text.",
        "page_text_verbatim_tier": 1,
        "nearby_text": "context" if not redacted else "",
        "nearby_text_tier": None,
        "redacted": redacted,
        "captioner": captioner,
        "prompt_hash": None,
        "description": description,
        "description_tier": 2 if description and not redacted else None,
        "content_type": ("redaction" if redacted else
                         ("figure" if description else None)),
        "error": None,
    }


def test_caption_one_figure_skips_redacted(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure(None, redacted=True,
                       captioner="skipped:redacted",
                       description="[REDACTED: (b)(4)]")
    fig["content_type"] = "redaction"
    with patch("urllib.request.urlopen") as urlopen:
        out = caption_figure.caption_one_figure(
            fig,
            assets_root=root,
            substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("k", "m")], "timeout": 10},
        )
        assert urlopen.call_count == 0
    assert out["description"] == "[REDACTED: (b)(4)]"
    assert out["content_type"] == "redaction"


def test_caption_one_figure_lmstudio_structured_success(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_lmstudio_structured",
                      return_value=("figure", "A PK plot.")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="lmstudio",
            backend_kwargs={"host": "http://localhost:1234", "model": "gemma-4-e4b-it", "timeout": 60},
        )
    assert out["description"] == "A PK plot."
    assert out["content_type"] == "figure"
    assert out["description_tier"] == 2
    assert out["captioner"].startswith("lmstudio:gemma-4-e4b-it@")
    assert isinstance(out["prompt_hash"], str) and len(out["prompt_hash"]) == 16


def test_caption_one_figure_gemini_table_success(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("table", "<table><tr><td>x</td></tr></table>")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "table"
    assert out["description"].startswith("<table")
    assert out["description_tier"] == 2
    assert out["captioner"].startswith("gemini:gemma-4-31b-it@")


def test_caption_one_figure_records_parse_error(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=(None, "not json sorry")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "error"
    assert "parse" in out["error"].lower()
    assert out["description"] == ""
    assert out["description_tier"] is None


def test_caption_one_figure_records_http_error(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    def boom(*a, **kw):
        raise RuntimeError("HTTPError 500")
    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=boom):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "error"
    assert "HTTPError" in out["error"]


def test_caption_one_figure_gemini_round_robin_advances_on_429(tmp_path):
    """First pair 429s; second pair succeeds. caption_one_figure must not error."""
    import urllib.error
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    calls: list[tuple[str, str]] = []
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        calls.append((api_key, model))
        if api_key == "K1":
            raise urllib.error.HTTPError(
                url="http://x", code=429, msg="rate", hdrs=None, fp=None,
            )
        return ("figure", "A plot.")
    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={
                "pairs": [("K1", "m1"), ("K2", "m2")],
                "timeout": 60,
            },
        )
    assert calls == [("K1", "m1"), ("K2", "m2")]
    assert out["content_type"] == "figure"


def test_process_figures_skips_already_captioned(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure("stem.assets/figure_p1_f1.png",
                         captioner="gemini:gemma-4-31b-it@2026-05-15",
                         description="Existing caption.")]
    with patch.object(caption_figure, "transcribe_gemini_structured") as gem:
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=None,
        )
        assert gem.call_count == 0
    assert out[0]["description"] == "Existing caption."
    assert stats["captioned"] == 0
    assert stats["skipped_done"] == 1


def test_process_figures_force_recaptions(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure("stem.assets/figure_p1_f1.png",
                         captioner="gemini:gemma-4-31b-it@2026-05-15",
                         description="Stale.")]
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "Fresh.")):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "gemma-4-31b-it")], "timeout": 10},
            force=True, rate_budget_calls=None,
        )
    assert out[0]["description"] == "Fresh."
    assert stats["captioned"] == 1


def test_process_figures_rate_budget_stops_after_n(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure(f"stem.assets/figure_p{i}_f1.png") for i in range(1, 6)]
    # Seed extra PNGs
    for i in range(2, 6):
        (root / "stem.assets" / f"figure_p{i}_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nF")
        figs[i - 1]["figure_id"] = f"p{i}_f1"
        figs[i - 1]["page_number"] = i

    call_count = {"n": 0}
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        call_count["n"] += 1
        return ("figure", f"caption {call_count['n']}")

    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=3,
        )
    assert call_count["n"] == 3
    assert stats["budget_exhausted"] is True
    # First three are captioned; last two left untouched
    assert sum(1 for f in out if f.get("description")) == 3


def test_process_figures_resume_after_budget(tmp_path):
    """Re-run with same figures (3 already done) plus remaining budget completes the rest."""
    root = _seed_assets(tmp_path)
    figs = [_make_figure(f"stem.assets/figure_p{i}_f1.png") for i in range(1, 6)]
    for i in range(2, 6):
        (root / "stem.assets" / f"figure_p{i}_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nF")
        figs[i - 1]["figure_id"] = f"p{i}_f1"
        figs[i - 1]["page_number"] = i
    # Pre-mark figures 1-3 as already captioned
    for f in figs[:3]:
        f["captioner"] = "gemini:gemma-4-31b-it@2026-05-15"
        f["description"] = "done earlier"
        f["content_type"] = "figure"
        f["description_tier"] = 2

    call_count = {"n": 0}
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        call_count["n"] += 1
        return ("figure", f"resumed {call_count['n']}")

    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=None,
        )
    assert call_count["n"] == 2  # only the two unfinished figures
    assert stats["captioned"] == 2
    assert stats["skipped_done"] == 3
    assert all(f["description"] for f in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v -k "caption_one_figure or process_figures"`

Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the captioning loop**

In `caption_figure.py`, after `check_sidecar_freshness`, add:

```python
def _gemini_with_round_robin_structured(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> tuple[str | None, str, str]:
    """Round-robin gemini pairs in structured-output mode.

    Returns (type, content, used_model). Advances pairs on HTTP 429; on
    every-pair-exhausted raises RuntimeError. Local copy (not re-export)
    so patch.object(caption_figure, 'transcribe_gemini_structured')
    intercepts cleanly in tests.
    """
    last_429: Exception | None = None
    for api_key, model in pairs:
        try:
            t, c = transcribe_gemini_structured(
                image_png_bytes,
                api_key=api_key,
                model=model,
                timeout=timeout,
                prompt=prompt,
            )
            return t, c, model
        except urllib.error.HTTPError as e:
            if e.code == 429:
                last_429 = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs returned 429 ({len(pairs)} tried)"
    ) from last_429


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def caption_one_figure(
    figure_entry: dict,
    *,
    assets_root: Path,
    substance: str | None,
    engine: str,
    backend_kwargs: dict,
) -> dict:
    """Caption one figure. Returns a NEW dict (does not mutate input).

    For redacted figures: returns the entry unchanged (already pre-filled
    by write_figure_assets). No HTTP call.

    For real figures: reads the PNG, renders the prompt, calls the
    structured-output backend, populates description/content_type/
    captioner/prompt_hash/description_tier/error.

    Per-figure error containment (no exception escapes).
    """
    out = dict(figure_entry)
    if out.get("redacted"):
        return out

    asset_rel = out.get("asset_path")
    if not asset_rel:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = "missing asset_path on non-redacted figure"
        out["captioner"] = f"{engine}:skipped:no_asset"
        return out

    image_path = assets_root / asset_rel
    try:
        image_bytes = image_path.read_bytes()
    except OSError as e:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = f"could not read {image_path}: {e}"
        out["captioner"] = f"{engine}:skipped:read_error"
        return out

    prompt = render_prompt(
        substance=substance,
        nearby_text=out.get("nearby_text", "") or "",
        raw_caption_candidate=out.get("raw_caption_candidate", "") or "",
    )
    p_hash = compute_prompt_hash(prompt)
    out["prompt_hash"] = p_hash
    today = _utc_today()

    try:
        if engine == "lmstudio":
            model = backend_kwargs["model"]
            t, c = transcribe_lmstudio_structured(
                image_bytes,
                host=backend_kwargs["host"],
                model=model,
                timeout=backend_kwargs["timeout"],
                prompt=prompt,
            )
            used_model = model
        elif engine == "gemini":
            pairs = backend_kwargs["pairs"]
            t, c, used_model = _gemini_with_round_robin_structured(
                image_bytes,
                pairs=pairs,
                timeout=backend_kwargs["timeout"],
                prompt=prompt,
            )
        else:
            raise ValueError(f"unknown engine {engine!r}")
    except Exception as e:  # noqa: BLE001 - per-figure containment
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = f"{type(e).__name__}: {e}"
        out["captioner"] = f"{engine}:error"
        return out

    if t is None:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        # Truncate raw text for the error string to keep JSON manageable
        preview = (c or "")[:200].replace("\n", " ")
        out["error"] = f"structured-output parse failed: {preview!r}"
        out["captioner"] = f"{engine}:parse_error"
        return out

    out["description"] = c
    out["content_type"] = t  # 'figure' or 'table'
    out["description_tier"] = 2
    out["captioner"] = f"{engine}:{used_model}@{today}"
    return out


def process_figures(
    figures: list[dict],
    *,
    assets_root: Path,
    substance: str | None,
    engine: str,
    backend_kwargs: dict,
    force: bool,
    rate_budget_calls: int | None,
) -> tuple[list[dict], dict]:
    """Caption every figure. Skip already-done unless force; honour budget cap.

    Stats:
      captioned        - successful new captions written this run
      skipped_done     - figures already had a description (and force=False)
      errored          - figures whose content_type became 'error' this run
      skipped_redacted - figures pre-filled with redaction marker (no call)
      budget_exhausted - True iff rate_budget_calls was hit
    """
    out: list[dict] = []
    stats = {
        "captioned": 0,
        "skipped_done": 0,
        "errored": 0,
        "skipped_redacted": 0,
        "budget_exhausted": False,
    }
    calls_made = 0
    for f in figures:
        if f.get("redacted"):
            out.append(dict(f))
            stats["skipped_redacted"] += 1
            continue
        already_done = (
            f.get("captioner") not in (None, "")
            and f.get("description") not in (None, "")
            and f.get("content_type") not in (None, "", "error")
        )
        if already_done and not force:
            out.append(dict(f))
            stats["skipped_done"] += 1
            continue
        if rate_budget_calls is not None and calls_made >= rate_budget_calls:
            # Budget hit. Pass through remaining figures unchanged.
            out.append(dict(f))
            stats["budget_exhausted"] = True
            continue
        new_entry = caption_one_figure(
            f,
            assets_root=assets_root,
            substance=substance,
            engine=engine,
            backend_kwargs=backend_kwargs,
        )
        calls_made += 1
        out.append(new_entry)
        if new_entry.get("content_type") == "error":
            stats["errored"] += 1
        else:
            stats["captioned"] += 1
    return out, stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v -k "caption_one_figure or process_figures"`

Expected: all PASS (9 tests in this slice).

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/caption_figure.py skills/pdf-doc-extraction/tests/test_caption_figure.py
git commit -m "feat(pdf-extraction): caption_one_figure + process_figures with structured output + rate budget"
```

---

## Task 14: `caption_figure.py` main CLI

**Files:**
- Modify: `skills/pdf-doc-extraction/scripts/caption_figure.py`
- Modify: `skills/pdf-doc-extraction/tests/test_caption_figure.py`

Spec invariants:
- Flags: `--substance`, `--engine`, `--model`, `--host`, `--timeout`, `--api-key` (repeatable), `--gemini-models`, `--force`, `--accept-stale`, `--check-stale`, `--rate-budget-calls`, `--quiet`.
- Default `--engine gemini`, `--gemini-models gemma-4-31b-it,gemma-4-26b-a4b-it`, LMStudio default model `gemma-4-e4b-it`.
- Gemini API key precedence: `--api-key` (repeatable) > `GEMINI_API_KEY` > `GOOGLE_API_KEY`.
- Refuses denylisted LMStudio models with exit 2.
- Refuses stale sidecars unless `--force` or `--accept-stale`; exit non-zero with diagnostic.
- `--check-stale` prints diagnostic and exits 0 with no HTTP.
- Writes captioning metadata back: `captioning_date`, `captioning_engine`, `captioning_seconds`, plus `budget_exhausted` boolean.

- [ ] **Step 1: Write the failing tests**

Append to `test_caption_figure.py`:

```python
def _seed_figures_json(tmp_path: Path, *, fresh: bool = True,
                      with_caption: bool = False) -> tuple[Path, Path]:
    """Seed a tmp_path with stem.pdf, stem.figures.json, and stem.assets/.

    Returns (figures_json_path, pdf_path). If fresh=False, sidecar hashes
    don't match (used to test stale-sidecar refusal).
    """
    pdf = tmp_path / "stem.pdf"
    pdf.write_bytes(b"FAKE PDF BODY")
    assets = tmp_path / "stem.assets"
    assets.mkdir()
    (assets / "figure_p1_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    real_sha = caption_figure._sha256_file(pdf)
    fake_sha = "0" * 64
    thresholds = {
        "header_fraction": 0.15,
        "header_min_height": 0.08,
        "redaction_stddev": 15.0,
        "redaction_mean_max": 245.0,
        "min_area_px": 400,
        "nearby_text_max_chars": 2500,
    }
    import hashlib as _h
    canon = json.dumps(thresholds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    real_t_hash = _h.sha256(canon).hexdigest()
    fake_t_hash = "f" * 64
    payload = {
        "schema_version": "1.0",
        "source_file": "stem.pdf",
        "source_pdf_sha256": real_sha if fresh else fake_sha,
        "extraction_date": "2026-05-15T00:00:00Z",
        "extractor_version": "extract_figures.py@2026-05-15",
        "extractor_thresholds": thresholds,
        "extractor_thresholds_hash": real_t_hash if fresh else fake_t_hash,
        "substance": "apalutamide",
        "substance_source": "metadata_json",
        "page_count": 1,
        "figure_count": 1,
        "redacted_count": 0,
        "dropped_header_decorations": [],
        "captioning_date": None,
        "captioning_engine": None,
        "captioning_seconds": None,
        "figures": [_make_figure(
            "stem.assets/figure_p1_f1.png",
            captioner=("gemini:gemma-4-31b-it@2026-05-14" if with_caption else None),
            description=("Existing." if with_caption else None),
        )],
    }
    fj = tmp_path / "stem.figures.json"
    fj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fj, pdf


def test_cli_refuses_ocr_specialized_lmstudio_model(tmp_path, capsys):
    fj, _pdf = _seed_figures_json(tmp_path)
    rc = caption_figure.main([
        "--figures-json", str(fj),
        "--engine", "lmstudio",
        "--model", "glm-ocr",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "denylist" in err.lower() or "general vision" in err.lower()


def test_cli_refuses_stale_sidecar_without_force(tmp_path, capsys):
    fj, _pdf = _seed_figures_json(tmp_path, fresh=False)
    rc = caption_figure.main([
        "--figures-json", str(fj),
        "--engine", "gemini",
        "--api-key", "K",
        "--gemini-models", "gemma-4-31b-it",
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "stale" in err.lower() or "mismatch" in err.lower() or "sha256" in err.lower()


def test_cli_accept_stale_overrides_freshness(tmp_path):
    fj, _pdf = _seed_figures_json(tmp_path, fresh=False)
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "A plot.")):
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
            "--accept-stale",
        ])
    assert rc == 0
    payload = json.loads(fj.read_text(encoding="utf-8"))
    assert payload["figures"][0]["description"] == "A plot."


def test_cli_check_stale_no_calls(tmp_path, capsys):
    fj, _pdf = _seed_figures_json(tmp_path, fresh=False)
    with patch("urllib.request.urlopen") as urlopen:
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
            "--check-stale",
        ])
        assert urlopen.call_count == 0
    assert rc == 0
    captured = capsys.readouterr()
    assert "stale" in (captured.out + captured.err).lower() or "mismatch" in (captured.out + captured.err).lower()


def test_cli_writes_descriptions_back(tmp_path):
    fj, _pdf = _seed_figures_json(tmp_path)
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "A bar chart of AEs.")):
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
        ])
    assert rc == 0
    payload = json.loads(fj.read_text(encoding="utf-8"))
    fig = payload["figures"][0]
    assert fig["description"] == "A bar chart of AEs."
    assert fig["content_type"] == "figure"
    assert fig["description_tier"] == 2
    assert fig["captioner"].startswith("gemini:gemma-4-31b-it@")
    assert isinstance(fig["prompt_hash"], str) and len(fig["prompt_hash"]) == 16
    # Top-level captioning metadata
    assert payload["captioning_engine"] == "gemini"
    assert isinstance(payload["captioning_seconds"], (int, float))
    assert payload["captioning_date"] is not None


def test_cli_force_re_captions_existing(tmp_path):
    fj, _pdf = _seed_figures_json(tmp_path, with_caption=True)
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "Fresh.")):
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
            "--force",
        ])
    assert rc == 0
    payload = json.loads(fj.read_text(encoding="utf-8"))
    assert payload["figures"][0]["description"] == "Fresh."


def test_cli_uses_substance_from_sidecar(tmp_path):
    fj, _pdf = _seed_figures_json(tmp_path)
    captured = {}
    def fake(image_bytes, *, api_key, model, timeout, prompt):
        captured["prompt"] = prompt
        return ("figure", "OK")
    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
        ])
    assert rc == 0
    assert "apalutamide" in captured["prompt"]


def test_cli_gemini_uses_env_var_fallback(tmp_path, monkeypatch):
    fj, _pdf = _seed_figures_json(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "FROM_ENV")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "OK")) as gem:
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--gemini-models", "gemma-4-31b-it",
        ])
    assert rc == 0
    assert gem.call_args.kwargs["api_key"] == "FROM_ENV"


def test_cli_rate_budget_writes_partial_and_flag(tmp_path):
    fj, _pdf = _seed_figures_json(tmp_path)
    # Seed two figures, budget = 1
    payload = json.loads(fj.read_text(encoding="utf-8"))
    second = _make_figure("stem.assets/figure_p2_f1.png")
    second["figure_id"] = "p2_f1"
    second["page_number"] = 2
    (tmp_path / "stem.assets" / "figure_p2_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nB")
    payload["figures"].append(second)
    payload["figure_count"] = 2
    fj.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "Captioned.")):
        rc = caption_figure.main([
            "--figures-json", str(fj),
            "--engine", "gemini",
            "--api-key", "K",
            "--gemini-models", "gemma-4-31b-it",
            "--rate-budget-calls", "1",
        ])
    assert rc == 0
    payload = json.loads(fj.read_text(encoding="utf-8"))
    descs = [f.get("description") for f in payload["figures"]]
    assert descs.count("Captioned.") == 1
    assert payload.get("budget_exhausted") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v -k cli`

Expected: FAIL — `main()` is `NotImplementedError`.

- [ ] **Step 3: Implement `main`**

In `caption_figure.py`, REPLACE the `main()` stub at the bottom with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Caption extracted figures via a vision model (Phase 3b).",
    )
    parser.add_argument("--figures-json", type=Path, required=True)
    parser.add_argument("--substance", default=None,
                        help="Override; otherwise uses sidecar substance field.")
    parser.add_argument("--engine", default="gemini", choices=["gemini", "lmstudio"])
    parser.add_argument("--model", default=None,
                        help="LMStudio model name (default: gemma-4-e4b-it). "
                             "Ignored with --engine gemini.")
    parser.add_argument("--host", default="http://localhost:1234")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--api-key", action="append", default=None,
                        help="Gemini API key. Repeatable. Falls back to "
                             "GEMINI_API_KEY/GOOGLE_API_KEY env var.")
    parser.add_argument("--gemini-models",
                        default="gemma-4-31b-it,gemma-4-26b-a4b-it",
                        help="Comma-separated Gemini models for round-robin")
    parser.add_argument("--force", action="store_true",
                        help="Re-caption already-done figures; bypass freshness check")
    parser.add_argument("--accept-stale", action="store_true",
                        help="Proceed against a stale sidecar (warns instead of refusing)")
    parser.add_argument("--check-stale", action="store_true",
                        help="Print freshness diagnostic and exit 0; no HTTP")
    parser.add_argument("--rate-budget-calls", type=int, default=None,
                        help="Hard stop after N successful backend calls")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # 1. Load sidecar
    payload = json.loads(args.figures_json.read_text(encoding="utf-8"))
    pdf_path = _resolve_pdf_path(payload, args.figures_json)
    current_thresholds_hash = payload.get("extractor_thresholds_hash", "")

    # 2. Freshness check (always run; --check-stale short-circuits, --force
    #    and --accept-stale only relax the refusal).
    freshness_diag = check_sidecar_freshness(
        payload,
        pdf_path=pdf_path,
        current_thresholds_hash=current_thresholds_hash,
    )

    if args.check_stale:
        if freshness_diag:
            print(json.dumps({
                "figures_json": str(args.figures_json),
                "status": "stale",
                "diagnostic": freshness_diag,
            }, indent=2))
        else:
            print(json.dumps({
                "figures_json": str(args.figures_json),
                "status": "fresh",
            }, indent=2))
        return 0

    if freshness_diag and not (args.force or args.accept_stale):
        print(f"error: sidecar is stale: {freshness_diag}", file=sys.stderr)
        print("       pass --accept-stale to proceed, or re-run extract_figures.py "
              "and try again.", file=sys.stderr)
        return 3

    if freshness_diag and (args.force or args.accept_stale) and not args.quiet:
        print(f"WARNING: sidecar is stale ({freshness_diag}); proceeding due to flag",
              file=sys.stderr)

    # 3. Resolve backend kwargs + denylist check
    if args.engine == "lmstudio":
        model = args.model or "gemma-4-e4b-it"
        err = validate_captioning_model("lmstudio", model)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        backend_kwargs = {"host": args.host, "model": model, "timeout": args.timeout}
    else:  # gemini
        keys = list(args.api_key or [])
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not keys and env_key:
            keys = [env_key]
        if not keys:
            print("error: --engine gemini requires --api-key or "
                  "GEMINI_API_KEY/GOOGLE_API_KEY env var", file=sys.stderr)
            return 2
        models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]
        if not models:
            print("error: --gemini-models is empty after parsing", file=sys.stderr)
            return 2
        pairs = [(k, m) for k in keys for m in models]
        backend_kwargs = {"pairs": pairs, "timeout": args.timeout}

    # 4. Process
    substance = args.substance or payload.get("substance")
    assets_root = args.figures_json.parent

    t0 = time.monotonic()
    new_figures, stats = process_figures(
        payload.get("figures", []),
        assets_root=assets_root,
        substance=substance,
        engine=args.engine,
        backend_kwargs=backend_kwargs,
        force=args.force,
        rate_budget_calls=args.rate_budget_calls,
    )
    duration = round(time.monotonic() - t0, 3)

    # 5. Atomic write
    payload["figures"] = new_figures
    payload["captioning_date"] = _utc_now_iso()
    payload["captioning_engine"] = args.engine
    payload["captioning_seconds"] = duration
    payload["budget_exhausted"] = stats["budget_exhausted"]
    atomic_write_json(args.figures_json, payload)

    if not args.quiet:
        print(json.dumps({
            "figures_json": str(args.figures_json),
            "engine": args.engine,
            **stats,
            "total_seconds": duration,
        }, indent=2))
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/pdf-doc-extraction/tests/test_caption_figure.py -v`

Expected: every test PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/caption_figure.py skills/pdf-doc-extraction/tests/test_caption_figure.py
git commit -m "feat(pdf-extraction): caption_figure CLI with freshness gate + rate budget"
```

---

## Task 15: Update SKILL.md + README.md

**Files:**
- Modify: `skills/pdf-doc-extraction/SKILL.md`
- Modify: `skills/pdf-doc-extraction/README.md`

- [ ] **Step 1: Run the full skill test suite — verify clean baseline**

Run: `pytest skills/pdf-doc-extraction/tests -v`

Expected: every test passes (skips are acceptable for fixtures that are gitignored locally).

- [ ] **Step 2: Update `SKILL.md` tools table**

Open `skills/pdf-doc-extraction/SKILL.md`. Find the tools table (rows for `extract_text.py`, `ocr_page.py`, `ensure_lmstudio.py`). Add two new rows after `ocr_page.py`:

```markdown
| `scripts/extract_figures.py` | Phase 3a | Walks each page, extracts embedded figure rasters as PNGs, drops agency-logo header decorations (logged to `dropped_header_decorations[]`), detects `(b)(4)` redactions by pixel statistics, captures `page_text_verbatim` (document-ordered, Tier-1-eligible) + `nearby_text` (closest-first, captioner-context only). Atomic-write `<stem>.figures.json` + `<stem>.assets/figure_pN_fM.png`. Sidecar carries `source_pdf_sha256` + `extractor_thresholds_hash` for idempotency. |
| `scripts/caption_figure.py` | Phase 3b | Reads `<stem>.figures.json`, verifies freshness against the sidecar's PDF + thresholds hashes (refuses stale unless `--force`/`--accept-stale`), sends each non-redacted figure PNG to a vision backend in **structured-output mode** (`{type: "figure"|"table", content: ...}`). Default backend Gemini cloud; LMStudio supported with `CAPTION_DENYLIST` enforcement (refuses `glm-ocr` / `lightonocr-2-1b-ocr-soup` / `deepseek-ocr`). Atomic write descriptions + `captioner: "engine:model@YYYY-MM-DD"` + `prompt_hash` back into the same JSON. |
```

- [ ] **Step 3: Update `SKILL.md` model-selection table**

In the model-selection table, replace the existing "Vision captions for figures" row (if any) with:

```markdown
| Vision captions for figures | **Gemini API free-tier `gemma-4-31b-it,gemma-4-26b-a4b-it` round-robin, structured-output (`{type, content}`)** | LMStudio `gemma-4-e4b-it` (~4B, fits 6 GB VRAM) for offline runs | Models in `CAPTION_DENYLIST` (`glm-ocr`, `lightonocr-2-1b-ocr-soup`, `deepseek-ocr`) — refused at CLI; Sonnet vision sparingly; Opus vision never |
```

- [ ] **Step 4: Add a Phase 3 section to `SKILL.md`**

After the "OCR pass (Phase 2)" section, insert:

```markdown
## Figure extraction + captioning (Phase 3)

Two stages, two CLIs:

```bash
# 3a - extract figure rasters + write sidecar JSON
python skills/pdf-doc-extraction/scripts/extract_figures.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/

# 3b - caption non-redacted figures (default: Gemini cloud, structured output)
python skills/pdf-doc-extraction/scripts/caption_figure.py \
  --figures-json <substance>/<AGENCY>/<stem>.figures.json
```

Stage 3a writes `<stem>.figures.json` (atomic) + `<stem>.assets/figure_pN_fM.png`. Stage 3b updates the same JSON in place with `description` + `content_type` per entry (`figure` | `table` | `redaction` | `error`).

**Tier 1 / Tier 2 contract:**
- `raw_caption_candidate` and `page_text_verbatim` are Tier-1-eligible (verbatim, page-anchored).
- `description` is Tier-2 only (model-generated; auditable via `captioner` + `prompt_hash` but never a Tier 1 anchor).
- `nearby_text` is captioner-context only — `nearby_text_tier` is `null`. Do not cite from it.
- `wiki-pharma-extraction` enforces this via Rule 2b: "Tier 1 may cite only `raw_caption_candidate` or `page_text_verbatim`."

**Freshness contract:** the sidecar's `source_pdf_sha256` + `extractor_thresholds_hash` must match the current PDF + extractor defaults; otherwise `caption_figure.py` refuses to run. Override with `--accept-stale` or `--force`. `--check-stale` prints the freshness diagnostic without running HTTP.

**Defaults:**
- 3a: `--header-fraction 0.15 --header-min-height 0.08` (drop top-band logos)
- 3a: `--redaction-stddev 15 --redaction-mean-max 245 --min-area-px 400` (FOI `(b)(4)`)
- 3a: `--nearby-text-max-chars 2500`
- 3b: `--engine gemini --gemini-models gemma-4-31b-it,gemma-4-26b-a4b-it`
- 3b: substance auto-inferred from `<substance>/metadata.json::inn`, then path; sidecar records `substance_source`

**LMStudio captioning** is supported but not the default — 6 GB VRAM caps comfortable model size at ~4B, and 26-31B Gemma gives better captions on complex plots. The CLI **refuses OCR-specialized models** for captioning via explicit `CAPTION_DENYLIST` (`glm-ocr` / `lightonocr-2-1b-ocr-soup` / `deepseek-ocr`).
```

- [ ] **Step 5: Update `README.md` with a Phase 3 quick-start**

Open `skills/pdf-doc-extraction/README.md`. Add a "Phase 3 — figures + captions" section after the existing Phase 2 quick-start:

```markdown
### Phase 3 — figures + captions

```bash
# 3a: extract figures (atomic-write sidecar with content + thresholds hashes)
python scripts/extract_figures.py \
  --pdf ../../apalutamide/FDA/210951Orig1s000MultidisciplineR.pdf \
  --out ../../apalutamide/FDA/

# 3b: caption (structured output; uses GOOGLE_API_KEY/GEMINI_API_KEY from env)
python scripts/caption_figure.py \
  --figures-json ../../apalutamide/FDA/210951Orig1s000MultidisciplineR.figures.json

# Optional: see if the sidecar is fresh without making API calls
python scripts/caption_figure.py \
  --figures-json ../../apalutamide/FDA/210951Orig1s000MultidisciplineR.figures.json \
  --check-stale
```

Outputs: `<stem>.figures.json` + `<stem>.assets/figure_p*_f*.png`. The captioner refuses OCR-specialized models — pass a general vision model (`gemma-4-31b-it` for Gemini, `gemma-4-e4b-it` for LMStudio).
```

- [ ] **Step 6: Sanity-check the test suite**

Run: `pytest skills/pdf-doc-extraction/tests -v`

Expected: clean run (passes + acceptable fixture skips).

- [ ] **Step 7: Commit**

```bash
git add skills/pdf-doc-extraction/SKILL.md skills/pdf-doc-extraction/README.md
git commit -m "docs(pdf-extraction): document Phase 3 figures + captions tools"
```

---

## Self-review notes

**Spec coverage check:**
- 3a CLI + helpers: Tasks 4-10
- 3b CLI + helpers: Tasks 11-14
- `CAPTION_PROMPT_TEMPLATE`, `CAPTION_DENYLIST`, `atomic_write_json`: Task 1
- Structured-output helpers (`transcribe_lmstudio_structured`, `transcribe_gemini_structured`): Task 2
- Header-decoration filter + `dropped_header_decorations[]` audit: Tasks 5, 8, 10
- Redaction detection + literature defaults + chicken-and-egg seeding: Task 6
- `page_text_verbatim` (Tier-1, document-ordered) + `nearby_text` (captioner-only): Tasks 7, 8
- Substance inference (metadata.json preferred + path fallback + `substance_source`): Task 4
- Hash idempotency (`source_pdf_sha256`, `extractor_thresholds_hash`): Tasks 9, 10
- Atomic writes via `_vision_backends.atomic_write_json`: Tasks 1, 10, 14
- `*_tier` sentinel convention (`1`/`2`/`null`): Task 9 (write_figure_assets) + Task 13 (description_tier on success/error)
- Structured-output routing (no prefix sniffing): Tasks 2, 13
- `CAPTION_DENYLIST` enforcement: Tasks 1 + 11 + 14
- Captioner provenance (`engine:model@YYYY-MM-DD`, `prompt_hash`): Task 13
- Freshness gate (`--force`, `--accept-stale`, `--check-stale`): Tasks 12, 14
- Rate budget (`--rate-budget-calls`, partial save, resume): Task 13 + 14
- Per-figure error containment + `content_type: "error"`: Tasks 13, 14
- Round-robin advance on 429: Task 13
- SKILL.md + README.md updates: Task 15

**Type consistency check (function signatures across tasks):**
- `caption_one_figure(figure_entry, *, assets_root, substance, engine, backend_kwargs)` — same in Task 13 spec + tests, called by `process_figures` in Task 13 and `main` in Task 14.
- `process_figures(figures, *, assets_root, substance, engine, backend_kwargs, force, rate_budget_calls)` — consistent across Task 13 + Task 14.
- `render_prompt(*, substance, nearby_text, raw_caption_candidate)` — keyword-only; matches all callers.
- `extract_figures_from_page(doc, page_index_zero, *, header_fraction, header_min_height, redaction_thresholds, min_area_px, nearby_text_max_chars)` — `redaction_thresholds` is the 2-tuple `(stddev_max, mean_max)`, consistently passed in Task 8 + Task 10.
- `is_redaction(image_png_bytes, *, stddev_max, mean_max, min_area_px)` — consistent across Tasks 6, 8.
- `check_sidecar_freshness(sidecar, *, pdf_path, current_thresholds_hash) -> str | None` — consistent Tasks 12, 14.
- `_sha256_file(path)` — used in Task 12 + Task 14 tests (`_seed_figures_json`).
- `_make_figure(...)` test helper — defined in Task 13 tests, reused in Task 14 tests (test file is the same).
- `atomic_write_json(path, payload)` — defined Task 1, reused Task 10, Task 14.
- Captioner format `f"{engine}:{used_model}@{today}"` — set in Task 13 `caption_one_figure`, verified in Task 13 + Task 14 tests.

**Notes for SDD execution:**
- Tasks 1, 2 must come before any task that imports `_vision_backends.atomic_write_json` or the structured-output helpers (Tasks 10, 13, 14).
- Task 3 (fixture) must come before any test that uses `multidisc_pdf` (Tasks 8, 10).
- Within `extract_figures.py`: Tasks 4 → 5 → 6 → 7 → 8 → 9 → 10 is the dependency order.
- Within `caption_figure.py`: Tasks 11 → 12 → 13 → 14 is the dependency order.
- Task 15 (docs) is last and depends on nothing else functioning.
- 15 tasks total. Estimated 4-6 hours of subagent-driven execution depending on test debug loops.

**Deferred to implementation tickets (not in this plan, per second-pass review):**
- `KNOWN_REDACTIONS` corpus seeding (run extractor on apalutamide once, eyeball, record). Spec calls for ship-then-seed; the placeholder test is in Task 6.
- `COVERAGE_EXPECTATIONS` corpus seeding (pin per-source figure yields within ±20%). Spec's bands are wide; pin after first benchmark run.
- LMStudio JSON-mode reliability: single-retry on parse failure if measurements show high error rate. Phase 3.x.
- `extractor_thresholds_hash` doesn't cover code drift in `is_redaction()`. Phase 3.1 concern; `extractor_version` is currently a date string.
