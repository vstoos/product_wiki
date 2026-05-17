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
| OCR of scanned pages | **`LightOnOCR-2-1B-ocr-soup-BF16.gguf` via llama.cpp (1B BF16, OCR-specialized, captures HTML table structure + markdown headers, ~12s/page on Mobile RTX 3060)** | `GLM-OCR-Q8_0.gguf` (smaller/faster ~9s/page when table structure isn't needed); `DeepSeek-OCR-Q8_0.gguf` (markdown pipe-tables); Gemini API free-tier Gemma models via `--engine gemini` when local is unavailable; `gemma-4-E2B-it-Q4_K_M.gguf`/`gemma-4-E4B-it-Q4_K_M.gguf` via llama.cpp for general vision | PaddleOCR (Windows hell); paid OCR (Azure DI) only on explicit user request |
| Vision captions for figures | **Gemini API free-tier `gemma-4-31b-it,gemma-4-26b-a4b-it` round-robin, structured-output (`{type, content}`)** | llama.cpp `gemma-4-E4B-it-Q4_K_M.gguf` (~4B, fits 6 GB VRAM) for offline runs | Models matching `CAPTION_DENYLIST` substring patterns (`glm-ocr`, `lightonocr`, `deepseek-ocr`) — refused at CLI; Sonnet vision sparingly; Opus vision never |
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
| `scripts/ocr_page.py` | shipped | llama.cpp OCR for problem pages. Reads Phase 1's `<stem>.extract.json`, transcribes flagged pages, writes `<stem>.ocr.json`. Gemini API round-robin is the cloud fallback (Phase 2b). |
| `scripts/extract_figures.py` | Phase 3a | Walks each page, extracts embedded figure rasters as PNGs, drops agency-logo header decorations (logged to `dropped_header_decorations[]`), detects `(b)(4)` redactions by pixel statistics, captures `page_text_verbatim` (document-ordered, Tier-1-eligible) + `nearby_text` (closest-first, captioner-context only). Atomic-write `<stem>.figures.json` + `<stem>.assets/figure_pN_fM.png`. Sidecar carries `source_pdf_sha256` + `extractor_thresholds_hash` for idempotency. |
| `scripts/caption_figure.py` | Phase 3b | Reads `<stem>.figures.json`, verifies freshness against the sidecar's PDF + thresholds hashes (refuses stale unless `--force`/`--accept-stale`), sends each non-redacted figure PNG to a vision backend in **structured-output mode** (`{type: "figure"|"table", content: ...}`). Default backend Gemini cloud; llama.cpp supported with `CAPTION_DENYLIST` substring enforcement (refuses any model id containing `glm-ocr` / `lightonocr` / `deepseek-ocr`). Atomic write descriptions + `captioner: "engine:model@YYYY-MM-DD"` + `prompt_hash` back into the same JSON. |
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

Requires a **llama.cpp server running with a vision model loaded** on
`http://127.0.0.1:8080` (default). Only one `llama-server.exe` can run at
a time — 6 GB VRAM is the bottleneck — so OCR and captioning are serial.
Launch via the user's wrapper at `C:\Data\llama.cpp\scripts\run-server.cmd`
or directly:

```powershell
& "C:\Data\llama.cpp\src\build\bin\llama-server.exe" `
    --model  "C:\Users\vstoo\.cache\lm-studio\models\noctrex\LightOnOCR-2-1B-ocr-soup-GGUF\LightOnOCR-2-1B-ocr-soup-BF16.gguf" `
    --mmproj "C:\Users\vstoo\.cache\lm-studio\models\noctrex\LightOnOCR-2-1B-ocr-soup-GGUF\mmproj-F32.gguf" `
    --ctx-size 8192 --n-gpu-layers 99 --flash-attn on `
    --cache-type-k q8_0 --cache-type-v q8_0 --threads 8 `
    --host 127.0.0.1 --port 8080
```

Default model is `LightOnOCR-2-1B-ocr-soup-BF16.gguf` (captures HTML table
structure + markdown headers, best for regulatory forms). Alternatives:
load `GLM-OCR-Q8_0.gguf` (faster, prose-only), `DeepSeek-OCR-Q8_0.gguf`
(markdown pipe-tables), or a general vision model like
`gemma-4-E4B-it-Q4_K_M.gguf`. Check what's loaded with
`curl http://127.0.0.1:8080/v1/models`.

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

**Gemini cloud fallback (Phase 2b)** — when llama.cpp isn't running locally
or you want a free-tier cloud benchmark:

```bash
export GEMINI_API_KEY=...   # or pass --api-key (repeatable)
python skills/pdf-doc-extraction/scripts/ocr_page.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --extract-json <substance>/<AGENCY>/<file>.extract.json \
  --out <substance>/<AGENCY>/ \
  --engine gemini \
  --gemini-models "gemma-4-31b-it,gemma-4-26b-a4b-it"
```

The (key, model) cross-product is rotated per page to spread load. On HTTP
429, the dispatcher advances to the next pair and retries; only when every
pair returns 429 does the page record `status: error`.

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
- `nearby_text` is captioner-context only - `nearby_text_tier` is `null`. Do not cite from it.
- `wiki-pharma-extraction` enforces this via Rule 2b: "Tier 1 may cite only `raw_caption_candidate` or `page_text_verbatim`."

**Freshness contract:** the sidecar's `source_pdf_sha256` + `extractor_thresholds_hash` must match the current PDF + extractor defaults; otherwise `caption_figure.py` refuses to run. Override with `--accept-stale` or `--force`. `--check-stale` prints the freshness diagnostic without running HTTP.

**Defaults:**
- 3a: `--header-fraction 0.15 --header-min-height 0.08` (drop top-band logos)
- 3a: `--redaction-stddev 15 --redaction-mean-max 245 --min-area-px 400` (FOI `(b)(4)`)
- 3a: `--nearby-text-max-chars 2500`
- 3b: `--engine gemini --gemini-models gemma-4-31b-it,gemma-4-26b-a4b-it`
- 3b: substance auto-inferred from `<substance>/metadata.json::inn`, then path; sidecar records `substance_source`

**llama.cpp captioning** is supported but not the default - 6 GB VRAM caps comfortable model size at ~4B, and 26-31B Gemma gives better captions on complex plots. The CLI **refuses OCR-specialized models** for captioning via `CAPTION_DENYLIST` substring matching (any model id containing `glm-ocr`, `lightonocr`, or `deepseek-ocr`).

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
