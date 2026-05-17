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
| `scripts/ocr_page.py` | LMStudio OCR for problem pages | shipped |
| `scripts/ensure_lmstudio.py` | Cross-shell pre-flight: starts server + loads model (idempotent) | shipped |
| `scripts/extract_figures.py` | Raster + vector figures into `<stem>.assets/` + sidecar JSON with text context | shipped |
| `scripts/caption_figure.py` | Vision-model caption per figure (structured output; default Gemini) | shipped |
| `scripts/assemble_md.py` | Stitch text + OCR + figures + captions | planned |

## Quick start

### Text extraction (Phase 1)

```bash
python scripts/extract_text.py --pdf path/to/file.pdf --out path/to/output_dir/
```

Writes `output_dir/<stem>.md` and `output_dir/<stem>.extract.json`. Reads the PDF only; never modifies it.

### OCR a PDF's problem pages (Phase 2)

**First, launch the LM Studio desktop application.** The `lms` CLI is a
thin client over the GUI's background daemon — `lms server start` will
fail with a clear error if the GUI app isn't running.

Then pre-flight (idempotent — works in any shell; starts the server if
down, loads `lightonocr-2-1b-ocr-soup` if not already loaded, with a
10-min auto-unload TTL):

```bash
python scripts/ensure_lmstudio.py
```

Then OCR:

```bash
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/
```

Default model is `lightonocr-2-1b-ocr-soup` (1B BF16, OCR-specialized,
captures HTML table structure + markdown headers — best for regulatory
forms). Alternatives: `--model glm-ocr` (faster, prose-only) or
`--model deepseek-ocr` (markdown pipe-tables). For OCR-specialized models
the request is image-only (no instruction prompt) — instructions can
confuse single-task OCR models. General vision models (e.g. `gemma-4-e2b-it`)
get the full `OCR_PROMPT`. Override with `--prompt "..."`.

### Cloud OCR via Gemini (Phase 2b)

When LMStudio isn't available:

```bash
export GEMINI_API_KEY=...
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/<file>.pdf \
  --extract-json apalutamide/FDA/<file>.extract.json \
  --out apalutamide/FDA/ \
  --engine gemini --gemini-models "gemma-4-31b-it,gemma-4-26b-a4b-it"
```

Pass `--api-key` multiple times to round-robin across multiple keys for
higher effective throughput on the free tier.

### Phase 3 - figures + captions

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

Outputs: `<stem>.figures.json` + `<stem>.assets/figure_p*_f*.png`. The captioner refuses OCR-specialized models - pass a general vision model (`gemma-4-31b-it` for Gemini, `gemma-4-e4b-it` for LMStudio).

See `SKILL.md` for the agent-facing contract.
