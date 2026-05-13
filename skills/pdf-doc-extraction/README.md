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
