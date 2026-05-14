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
| `scripts/ensure_lmstudio.ps1` | PowerShell pre-flight: starts server + loads model | shipped |
| `scripts/extract_figures.py` | Raster + vector figures into `<stem>.assets/` | planned |
| `scripts/caption_figure.py` | Vision-model caption per figure | planned |
| `scripts/assemble_md.py` | Stitch text + OCR + figures + captions | planned |

## Quick start

### Text extraction (Phase 1)

```bash
python scripts/extract_text.py --pdf path/to/file.pdf --out path/to/output_dir/
```

Writes `output_dir/<stem>.md` and `output_dir/<stem>.extract.json`. Reads the PDF only; never modifies it.

### OCR a PDF's problem pages (Phase 2)

PowerShell pre-flight (idempotent — starts the LMStudio server if down,
loads `glm-ocr` if not already loaded, with a 10-min auto-unload TTL):

```powershell
.\scripts\ensure_lmstudio.ps1
```

Then OCR:

```bash
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/
```

Default model is `glm-ocr` (≈891M, OCR-specialized). For OCR-specialized
models the request is image-only (no instruction prompt) — instructions can
confuse single-task OCR models. General vision models (e.g. `gemma-4-e2b-it`)
get the full `OCR_PROMPT`. Override with `--prompt "..."`.

See `SKILL.md` for the agent-facing contract.
