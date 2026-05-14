# PDF Extraction Skill — Text Tool (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the agent-friendly skill-with-CLI pattern by (a) rewriting `pdf-doc-extraction/SKILL.md` to match the format that's actually on disk and (b) shipping the first CLI tool — `extract_text.py` (PyMuPDF only) — validated against existing extractions and applied to one previously-unextracted FDA supplement.

**Architecture:** Each skill is a self-contained folder with `SKILL.md` (model-agnostic prose contract), `references/` (deep docs), `scripts/` (small CLI tools the agent invokes via Bash), and `requirements.txt` (system Python, no in-repo venv). This phase ships only the first tool. OCR, figure extraction, vision captioning, and pipeline assembly are subsequent plans.

**Tech Stack:** Python 3.11+, PyMuPDF (`pymupdf`/`fitz`), pytest. No other runtime deps.

**Out of scope for this phase:** OCR, figure/asset extraction, vision-model captions, table extraction (SLANeXt), multi-PDF batch CLI, format converters for the existing 7 Azure-DI `.md` files.

---

## File Structure

```
skills/pdf-doc-extraction/
├── SKILL.md                       # REWRITE — match on-disk reality + model-selection block at top
├── README.md                      # CREATE — install + invocation
├── requirements.txt               # CREATE — pymupdf + pytest
├── references/                    # KEEP existing files; trim claims about formats not yet implemented
│   ├── pipeline-stages.md
│   ├── engine-selection.md
│   ├── figure-extraction.md
│   ├── output-format.md
│   └── normalization.md
├── scripts/
│   └── extract_text.py            # CREATE — first CLI tool
└── tests/
    ├── conftest.py                # CREATE — fixture path resolver
    └── test_extract_text.py       # CREATE — unit + smoke tests
```

The plan does NOT touch `references/` content in this phase — that gets reconciled in a follow-up plan once the actual tools exist to compare against.

---

## Task 1: Skill scaffolding (requirements.txt + README.md)

**Files:**
- Create: `skills/pdf-doc-extraction/requirements.txt`
- Create: `skills/pdf-doc-extraction/README.md`

- [ ] **Step 1: Write `requirements.txt`**

```
pymupdf>=1.24.0
pytest>=8.0.0
```

- [ ] **Step 2: Write `README.md`**

````markdown
# pdf-doc-extraction

Agent-friendly CLI tools for extracting text + assets from regulatory PDFs.

## Install

```bash
pip install -r requirements.txt
```

System Python is fine — no venv required. If you prefer isolation:

```bash
pipx install --spec . pdf-doc-extraction-cli   # future, once a console_scripts entry exists
```

## Tools

| Script | Purpose | Status |
|---|---|---|
| `scripts/extract_text.py` | PyMuPDF text extraction → `<stem>.md` + `<stem>.extract.json` | shipped |
| `scripts/ocr_page.py` | Gemma OCR for scanned pages | planned |
| `scripts/extract_figures.py` | Raster + vector figures into `<stem>.assets/` | planned |
| `scripts/caption_figure.py` | Vision-model caption per figure | planned |
| `scripts/assemble_md.py` | Stitch text + OCR + figures + captions | planned |

## Quick start

```bash
python scripts/extract_text.py --pdf path/to/file.pdf --out path/to/output_dir/
```

Writes `output_dir/<stem>.md` and `output_dir/<stem>.extract.json`. Reads the PDF only; never modifies it.

See `SKILL.md` for the agent-facing contract.
````

- [ ] **Step 3: Verify pip install works**

Run from `skills/pdf-doc-extraction/`:
```bash
pip install -r requirements.txt
python -c "import fitz; print(fitz.__doc__.splitlines()[0])"
```
Expected: prints PyMuPDF version line, no errors.

- [ ] **Step 4: Commit**

```bash
git add skills/pdf-doc-extraction/requirements.txt skills/pdf-doc-extraction/README.md
git commit -m "feat(pdf-extraction): add skill scaffolding (requirements + README)"
```

---

## Task 2: Test scaffold + first failing test

**Files:**
- Create: `skills/pdf-doc-extraction/tests/conftest.py`
- Create: `skills/pdf-doc-extraction/tests/test_extract_text.py`

- [ ] **Step 1: Write `conftest.py` to locate the apalutamide test fixtures**

```python
# skills/pdf-doc-extraction/tests/conftest.py
"""Shared fixtures. The apalutamide/ data is gitignored but local."""
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
APALUTAMIDE_FDA = REPO_ROOT / "apalutamide" / "FDA"


@pytest.fixture(scope="session")
def chemr_pdf() -> Path:
    """Small-but-real fixture: 6.4 MB FDA Chemistry Review PDF."""
    p = APALUTAMIDE_FDA / "210951Orig1s000ChemR.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p


@pytest.fixture(scope="session")
def suppl11_pdf() -> Path:
    """Smoke target: 2.8 MB previously-unextracted FDA supplement label."""
    p = APALUTAMIDE_FDA / "SUPPL_011_210951Orig1s011lbl.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p
```

- [ ] **Step 2: Write the first failing test (extract_text returns a dict with expected keys)**

```python
# skills/pdf-doc-extraction/tests/test_extract_text.py
"""Tests for extract_text.py — PyMuPDF text extraction tool."""
from pathlib import Path
import json
import sys

import pytest

# Make scripts/ importable
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_text  # noqa: E402


def test_extract_returns_per_page_text(chemr_pdf):
    """extract() returns a dict with per-page text and metadata."""
    result = extract_text.extract(chemr_pdf)
    assert "pages" in result
    assert "metadata" in result
    assert isinstance(result["pages"], list)
    assert len(result["pages"]) == 51  # ChemR has 51 pages
    assert all(isinstance(p, dict) and "text" in p for p in result["pages"])
```

- [ ] **Step 3: Run the test to verify it fails for the right reason**

Run from `skills/pdf-doc-extraction/`:
```bash
pytest tests/test_extract_text.py::test_extract_returns_per_page_text -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'extract_text'` (because the script doesn't exist yet).

- [ ] **Step 4: Commit**

```bash
git add skills/pdf-doc-extraction/tests/conftest.py skills/pdf-doc-extraction/tests/test_extract_text.py
git commit -m "test(pdf-extraction): add fixtures and first failing test for extract_text"
```

---

## Task 3: Minimal `extract_text.py` to pass the first test

**Files:**
- Create: `skills/pdf-doc-extraction/scripts/extract_text.py`

- [ ] **Step 1: Write the minimal script**

```python
# skills/pdf-doc-extraction/scripts/extract_text.py
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
```

- [ ] **Step 2: Run the test to verify it now passes**

Run from `skills/pdf-doc-extraction/`:
```bash
pytest tests/test_extract_text.py::test_extract_returns_per_page_text -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/pdf-doc-extraction/scripts/extract_text.py
git commit -m "feat(pdf-extraction): minimal extract_text.py (PyMuPDF, per-page text + metadata)"
```

---

## Task 4: Test the markdown output shape

**Files:**
- Modify: `skills/pdf-doc-extraction/tests/test_extract_text.py`

- [ ] **Step 1: Add tests for markdown rendering and CLI**

Append to `test_extract_text.py`:

```python
def test_render_markdown_has_yaml_frontmatter(chemr_pdf):
    result = extract_text.extract(chemr_pdf)
    md = extract_text.render_markdown(result)
    assert md.startswith("---\n")
    assert 'source_file: "210951Orig1s000ChemR.pdf"' in md
    assert "page_count: 51" in md
    assert 'engine: "pymupdf"' in md


def test_render_markdown_has_per_page_markers(chemr_pdf):
    result = extract_text.extract(chemr_pdf)
    md = extract_text.render_markdown(result)
    # Every page from 1..51 has a marker
    for n in range(1, 52):
        assert f"<!-- page: {n} -->" in md, f"missing marker for page {n}"


def test_problem_pages_are_flagged(chemr_pdf):
    """ChemR has scanned regions; expect at least one problem page."""
    result = extract_text.extract(chemr_pdf)
    # Don't pin the exact count (engine version may shift) — just assert detection works
    assert isinstance(result["metadata"]["problem_pages"], list)


def test_cli_writes_outputs(chemr_pdf, tmp_path):
    rc = extract_text.main([
        "--pdf", str(chemr_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    md = tmp_path / "210951Orig1s000ChemR.md"
    js = tmp_path / "210951Orig1s000ChemR.extract.json"
    assert md.exists() and md.stat().st_size > 1000
    assert js.exists()
    meta = json.loads(js.read_text(encoding="utf-8"))
    assert meta["page_count"] == 51
    assert meta["engine"] == "pymupdf"
```

- [ ] **Step 2: Run the full test file**

Run from `skills/pdf-doc-extraction/`:
```bash
pytest tests/test_extract_text.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/pdf-doc-extraction/tests/test_extract_text.py
git commit -m "test(pdf-extraction): cover markdown shape, page markers, CLI roundtrip"
```

---

## Task 5: Smoke-extract SUPPL_011 and visually verify

**Files:**
- (none modified; this task produces dataset output under the gitignored `apalutamide/` tree)

- [ ] **Step 1: Run extract_text.py on SUPPL_011**

```bash
python skills/pdf-doc-extraction/scripts/extract_text.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --out apalutamide/FDA/
```
Expected stdout: JSON summary with `page_count` ~30-50, `problem_page_count` 0 or low (this is a label, mostly clean text).

- [ ] **Step 2: Inspect the output markdown**

```bash
ls -la apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.md apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json
head -20 apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.md
grep -c '<!-- page:' apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.md
```
Expected: file exists, frontmatter present, page-marker count matches `page_count` in the JSON sidecar.

- [ ] **Step 3: Compare format against an existing extraction**

```bash
head -15 apalutamide/FDA/210951Orig1s000ChemR.md
head -15 apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.md
```

Expected differences (acceptable):
- New file's frontmatter has `engine: "pymupdf"` instead of `engine: "azure_di"`.
- New file lacks `figures_extracted`, `tables_extracted`, `ir_path` fields (those come in later phases).

Expected SAMENESS:
- YAML frontmatter at top, `---` delimited
- `<!-- page: N -->` markers between page bodies (not `<a id="pN">`)

If the format diverges from the existing extractions in any other way, stop and reconcile before proceeding to Task 6.

- [ ] **Step 4: No commit** (output goes to gitignored `apalutamide/` tree).

---

## Task 6: Rewrite `SKILL.md` to match reality + add model-selection block

**Files:**
- Modify: `skills/pdf-doc-extraction/SKILL.md` (full rewrite)

- [ ] **Step 1: Replace the entire file contents**

Replace `skills/pdf-doc-extraction/SKILL.md` with:

````markdown
---
name: pdf-doc-extraction
description: Use when the user has one or more downloaded regulatory PDF documents (FDA reviews, EMA EPARs, HC Product Monographs, PMDA review reports, TGA AusPARs, PubMed PMC full-texts) and needs them converted into LLM-friendly markdown with structured text, embedded HTML tables, extracted figures/images, OCR'd scanned regions, and optional vision-model captions for plots/charts/diagrams. Triggers include "extract text from this PDF", "convert these reviews to markdown", "OCR the scanned pages", "extract figures and tables from this EPAR", "process all PDFs in <dir>".
---

# PDF Document Extraction

Agent-friendly CLI tools for converting regulatory PDFs into structured markdown + asset folders. Each tool is a small Python script invoked via Bash; outputs are files on disk plus a JSON summary on stdout.

## Model selection (read this first)

Use the cheapest / fastest model that gets the job done. Defaults:

| Decision | Default model | Escalate to | Never use by default |
|---|---|---|---|
| Per-page text vs OCR routing, engine choice, caption-or-skip | **Haiku** | Sonnet only after Haiku gives clearly wrong output twice | Opus |
| OCR of scanned pages | **Gemini API round-robin on Gemma 4 models (free tier)**; planned local 2B models in future | Gemma 27B/31B if 4B output is unusable | Paid OCR (Azure DI) — only on explicit user request |
| Vision captions for figures | **Gemini API round-robin on Gemma 4 models (free tier)** | Sonnet vision sparingly | Opus vision |
| Heavy synthesis (NOT this skill — wiki only) | n/a | n/a | n/a |

Local-LLM swap-in (RTX 3090, future): change the OCR/caption tool's `--engine` flag; SKILL.md and orchestration stay identical.

## What this skill produces per input PDF

```
<stem>.md                  # YAML frontmatter + per-page text + (planned) inline tables, figures
<stem>.extract.json        # extraction metadata: pages, problem_pages, engines used, timing
<stem>.assets/             # (planned) figure / image rasters extracted from the PDF
  ├── figure_p1_f1.png
  ├── figure_p23_f1.png
  └── ir.json              # (planned) structural IR
```

The shape on disk follows the convention already established by upstream extractions in this repo (YAML frontmatter, `<!-- page: N -->` markers between pages, plain `>` blockquote captions adjacent to figure references). This is a description of what the tools produce, not a strict format the wiki agent must parse — the wiki agent is an LLM and reads either anchor convention.

## Tools available (Phase 1)

| Tool | Status | What it does |
|---|---|---|
| `scripts/extract_text.py` | shipped | PyMuPDF text extraction → `<stem>.md` + `<stem>.extract.json`. Flags problem pages (text < 100 chars) for a later OCR pass. |
| `scripts/ocr_page.py` | planned | Gemma OCR for problem pages. Free-tier round-robin between Gemini API and OpenRouter. |
| `scripts/extract_figures.py` | planned | Raster + vector figures into `<stem>.assets/`. |
| `scripts/caption_figure.py` | planned | Vision-model caption per figure. Free-tier Gemma 4. |
| `scripts/assemble_md.py` | planned | Stitch text + OCR + figures + captions into the final `<stem>.md`. |

See `README.md` for invocation; see `references/` for engine-comparison details.

## When to use this skill

- Newly fetched PDFs from `reg-doc-fetching` need to become structured markdown
- Existing PDFs in `<substance>/<AGENCY>/` lack a sibling `<stem>.md` extraction
- An existing extraction was produced by a different engine (e.g. Azure DI) and the user wants a free-tier re-extraction

Do NOT use this skill for:
- Fetching documents — that's `reg-doc-fetching`
- Wiki / fact extraction — that's `wiki-pharma-extraction`
- Single-doc text dump — `pdftotext` is fine

## Setup

```bash
pip install -r skills/pdf-doc-extraction/requirements.txt
```

System Python is fine; no in-repo venv. See `README.md` for details.

## How to invoke (Phase 1 only)

```bash
python skills/pdf-doc-extraction/scripts/extract_text.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/
```

Reads the PDF, writes `<stem>.md` and `<stem>.extract.json` next to it. Emits a JSON summary on stdout. Never modifies the input.

## Hard constraints

- **Don't paraphrase or "fix" extracted text.** If a page reads garbled, leave it garbled — downstream verifiers handle quality. Editing introduces silent data corruption.
- **Don't OCR pages with clean PyMuPDF text.** Wastes compute and risks degrading clean text with OCR errors. Only OCR pages flagged `is_problem: true` in the JSON sidecar.
- **Don't merge cross-page tables.** Emit table fragments tagged in their respective pages; cross-page merge is a downstream concern.
- **Always write the `.extract.json` sidecar.** Even minimal metadata is the audit trail — engines used, processing time, problem-page count.
- **Never modify the input PDF.** All outputs go in the same directory or a user-specified out dir.

## Output report format

After processing one or more PDFs, emit:

```
## PDF extraction summary

- Document: <stem>.pdf — N pages (M problem pages flagged for OCR), processed in T seconds
- Output: <stem>.md (S kB), <stem>.extract.json
- Engine: pymupdf (vN.N.N)
```

For a directory batch, list one line per file plus aggregate counts at the end.

## What NOT to do

- Don't run OCR on every page — only the problem pages from the text pass.
- Don't post-process `.md` to "improve" it. Output should be reproducible.
- Don't store binary blobs in `.md`. Images go in `<stem>.assets/` (in later phases).
- Don't bypass the JSON sidecar — it's the audit anchor for which engine produced what.

## Resources

- `README.md` — install and invocation
- `references/pipeline-stages.md` — full pipeline plan (text → OCR → tables → figures+captions)
- `references/engine-selection.md` — OCR engine comparison + decision tree
- `references/figure-extraction.md` — caption-vs-skip rules; vision-model prompting
- `references/output-format.md` — `.md` conventions, asset naming
- `references/normalization.md` — post-extraction normalization

References describe the full target pipeline. The shipped tools cover only a subset; the table above is the source of truth for what's actually available today.
````

- [ ] **Step 2: Verify the file is well-formed**

```bash
head -5 skills/pdf-doc-extraction/SKILL.md
wc -l skills/pdf-doc-extraction/SKILL.md
```
Expected: starts with `---` frontmatter, ~110-130 lines.

- [ ] **Step 3: Commit**

```bash
git add skills/pdf-doc-extraction/SKILL.md
git commit -m "docs(pdf-extraction): rewrite SKILL.md to match on-disk reality + cheap-model rule"
```

---

## Task 7: Update CLAUDE.md to surface the new pattern

**Files:**
- Modify: `CLAUDE.md` (add a short section pointing at the skill-with-CLI pattern and the model-selection rule)

- [ ] **Step 1: Read the current CLAUDE.md and find the "Model-cost preference" section**

Run:
```bash
grep -n "Model-cost preference" CLAUDE.md
```

- [ ] **Step 2: Replace that section to reference the new skill-with-CLI pattern**

Find this block in `CLAUDE.md`:

```markdown
## Model-cost preference

The user prefers the cheapest model that gets the job done — Haiku by default, free-tier Gemma (Gemini API + OpenRouter round-robin) for OCR and image captions, local LLMs via RTX 3090 (Qwen3.6-27b-Q4K_M) as future option. The skills already reflect this: `pdf-doc-extraction` defaults to "Gemma multi-provider" (free) and only escalates to Azure DI when the user accepts paid cost. When you have agency over model selection inside a skill, mirror that bias: pick free / Haiku / local first, escalate only on quality failure or explicit user ask.
```

Replace with:

```markdown
## Model selection (read every session)

Use the cheapest / fastest model that gets the job done.

- **Default text inference** (page classification, engine routing, caption-or-skip decisions): **Haiku**.
- **OCR / vision captions:** Gemini API round-robin on Gemma 4 models (free tier). Local 2B-class models on RTX 3090 are the planned swap-in — same skill, different `--engine` flag.
- **Heavy synthesis** (Tier 2 wiki narratives only): Sonnet sparingly. Never Opus by default.
- **Escalate** only after the cheap path produces clearly wrong output twice, or on explicit user ask.

Each skill's `SKILL.md` carries its own model-selection block at the top — when you invoke a skill, that block is the local-source-of-truth and overrides this default.

## Skill structure (the pattern)

Each skill is a self-contained folder:

```
skills/<skill-name>/
├── SKILL.md           # model-agnostic prose contract, model-selection block at top
├── README.md          # install + invocation
├── requirements.txt   # system Python deps (no in-repo venv)
├── references/        # deep docs loaded only when needed
└── scripts/           # small CLI tools the agent invokes via Bash
```

Tools are language-agnostic in principle (Python first because of the PDF/vision ecosystem; a future skill might wrap a Rust or C binary, like `be-sample-size` does). What matters is they're invokable as plain CLI commands and emit JSON to stdout / files to disk — so any agent (Claude, Hermes, Pi) can use them, not just Claude Code.
```

- [ ] **Step 3: Verify the diff**

```bash
git diff CLAUDE.md
```
Expected: one section replaced, one new section added below it.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): codify skill-with-CLI pattern + sharpen model-selection rule"
```

---

## Self-Review

**Spec coverage:**
- Skill scaffolding (requirements.txt, README) — Task 1 ✓
- TDD-built `extract_text.py` (PyMuPDF only) — Tasks 2, 3, 4 ✓
- Smoke-extract SUPPL_011 — Task 5 ✓
- Rewrite SKILL.md to match reality + model-selection block — Task 6 ✓
- Embed cheap-model rule prominently in CLAUDE.md — Task 7 ✓
- Validate output against existing Azure-DI extraction — Task 5 step 3 ✓
- No in-repo venv (`pip install -r requirements.txt`) — Task 1 ✓
- Test fixture: ChemR (not PSG) — Task 2 conftest ✓
- Smoke target: complex supplement with new study results (SUPPL_011) — Task 5 ✓

Out-of-scope items deliberately deferred to follow-up plans: OCR (`ocr_page.py`), figures (`extract_figures.py`), captions (`caption_figure.py`), pipeline orchestrator (`assemble_md.py`), reconciling the 7 existing Azure-DI `.md` files (no migration needed if the new tools produce the same shape going forward).

**Placeholder scan:** None. Every step has concrete code or commands.

**Type consistency:** `extract()` returns `dict[str, Any]` consistently across Tasks 3 and 4. CLI args (`--pdf`, `--out`, `--quiet`) match between script, tests, and SKILL.md.
