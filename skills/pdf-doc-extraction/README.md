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
| `scripts/ocr_page.py` | llama.cpp OCR for problem pages | shipped |
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

**First, launch a llama.cpp server with a vision model loaded.** Only one
`llama-server.exe` can run at a time on this hardware (6 GB VRAM). Use the
wrapper at `C:\Data\llama.cpp\scripts\run-server.cmd`, or launch directly:

```powershell
& "C:\Data\llama.cpp\src\build\bin\llama-server.exe" `
    --model  "C:\Users\vstoo\.cache\lm-studio\models\noctrex\LightOnOCR-2-1B-ocr-soup-GGUF\LightOnOCR-2-1B-ocr-soup-BF16.gguf" `
    --mmproj "C:\Users\vstoo\.cache\lm-studio\models\noctrex\LightOnOCR-2-1B-ocr-soup-GGUF\mmproj-F32.gguf" `
    --ctx-size 8192 --n-gpu-layers 99 --flash-attn on `
    --cache-type-k q8_0 --cache-type-v q8_0 --threads 8 `
    --host 127.0.0.1 --port 8080
```

Confirm with `curl http://127.0.0.1:8080/v1/models` (the id you pass to
`--model` below must match what `/v1/models` returns).

Then OCR:

```bash
python scripts/ocr_page.py \
  --pdf apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf \
  --extract-json apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.extract.json \
  --out apalutamide/FDA/
```

Default model id is `LightOnOCR-2-1B-ocr-soup-BF16.gguf` (1B BF16,
OCR-specialized, captures HTML table structure + markdown headers — best
for regulatory forms). Alternatives: `--model GLM-OCR-Q8_0.gguf` (faster,
prose-only) or `--model DeepSeek-OCR-Q8_0.gguf` (markdown pipe-tables).
For OCR-specialized models the request is image-only (no instruction
prompt) — instructions can confuse single-task OCR models. General vision
models (e.g. `gemma-4-E2B-it-Q4_K_M.gguf`) get the full `OCR_PROMPT`.
Override with `--prompt "..."`.

### Cloud OCR via Gemini (Phase 2b)

When llama.cpp isn't running locally (or to benchmark cloud quality):

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

Outputs: `<stem>.figures.json` + `<stem>.assets/figure_p*_f*.png`. The captioner refuses OCR-specialized models (substring patterns `glm-ocr`/`lightonocr`/`deepseek-ocr`) — pass a general vision model. Default Gemini rotation is `gemma-4-26b-a4b-it,gemma-4-31b-it` (fast MoE primary + dense chemistry-precision secondary, 30 RPM combined under the 15-RPM-per-model cap). For local, prefer `Qwen3.5-4B-Q4_K_M.gguf` (fast) or `Qwen3.5-35B-A3B-Q4_K_M.gguf` MoE (quality).

See `SKILL.md` for the agent-facing contract.
