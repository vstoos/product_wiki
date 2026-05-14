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

```bash
# Start LMStudio with glm-ocr loaded on port 1234, then:
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/
```

See `SKILL.md` for the agent-facing contract.
