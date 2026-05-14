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
| OCR of scanned pages | **`glm-ocr` via LMStudio (≈891M params Q8_0, OCR-specialized, >150 tps on a Mobile RTX 3060 6 GB)** | Gemini API free-tier Gemma models via `--engine gemini` when local is unavailable; or `gemma-4-e2b-it`/`gemma-4-e4b-it` via LMStudio for general vision. | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
| Vision captions for figures | **Gemini API round-robin on Gemma 4 models (free tier)** | Sonnet vision sparingly | Opus vision |
| Heavy synthesis (NOT this skill — wiki only) | n/a | n/a | n/a |

Local hardware budget today: Mobile RTX 3060 6 GB (~5.5 GB usable). Caps comfortable model size at ≈4-5B at moderate quantization. Future eGPU with RTX 3090 would lift the ceiling; the `--engine` flag and orchestration stay identical when the swap happens.

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

## Tools available

| Tool | Status | What it does |
|---|---|---|
| `scripts/extract_text.py` | shipped | PyMuPDF text extraction → `<stem>.md` + `<stem>.extract.json`. Flags problem pages (text < 100 chars) for a later OCR pass. |
| `scripts/ocr_page.py` | shipped | LMStudio OCR for problem pages. Reads Phase 1's `<stem>.extract.json`, transcribes flagged pages, writes `<stem>.ocr.json`. Gemini API round-robin is Phase 2b. |
| `scripts/ensure_lmstudio.py` | shipped | Cross-shell pre-flight that starts the LMStudio server and loads a model if not already loaded. Idempotent. Wraps `lms` CLI. |
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
(default: `glm-ocr`). One-liner pre-flight (any shell):

```bash
python skills/pdf-doc-extraction/scripts/ensure_lmstudio.py
```

This starts the server (if down) and loads `glm-ocr` (if not already loaded)
with a 10-min auto-unload TTL. Override with `--model gemma-4-e2b-it
--ttl 1800 --gpu 0.5`. The script is idempotent.

Then OCR:

```bash
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --extract-json <substance>/<AGENCY>/<file>.extract.json \
  --out <substance>/<AGENCY>/
```

Reads `problem_pages` from the extract sidecar, transcribes each, writes
`<stem>.ocr.json`. Override which pages to OCR with `--pages "3,5,7-9"`.
Rerun is cache-aware: ok-status pages are skipped unless `--force`.

**Prompt mode is auto-selected by model name:**
- Models matching `/ocr/i` (e.g. `glm-ocr`, `deepseek-ocr`, `lightonocr-*`) get
  an **image-only request** with no instruction text — they are trained for
  the single task and instructions can confuse them.
- General vision models (e.g. `gemma-4-e2b-it`) get the full `OCR_PROMPT`
  with rules for tables, special characters, and redactions.
- Override with `--prompt "..."`. The chosen mode is recorded in the output
  JSON as `prompt_mode: auto-empty | auto-default | user`.

Before processing, the script probes `/v1/models` and prints a warning if
the requested model is not loaded (suppress with `--skip-model-check`).

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
