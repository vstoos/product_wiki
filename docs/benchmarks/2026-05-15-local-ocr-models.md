# Local OCR model benchmark — 2026-05-15

**Goal:** Pick the default OCR model for `pdf-doc-extraction/scripts/ocr_page.py` from the three OCR-specialized models the user has on disk: `glm-ocr`, `lightonocr-2-1b-ocr-soup`, `deepseek-ocr`.

**Hardware:** Mobile RTX 3060, 6 GB VRAM. Models loaded sequentially via `lms unload -a` + `lms load <next>` to fit in budget.

**Method:** 15 pages from 4 PDFs, all rendered once at 200 DPI, then sent through each model's chat-completions endpoint via `_vision_backends.transcribe_lmstudio` with `prompt=""` (image-only — all three are OCR-specialized so no instruction prompt). `max_tokens=16384` (bumped from 4096 after the first benchmark showed truncation).

**Page mix:**

| Document | Pages | Content type |
|---|---|---|
| `210951Orig1s000ChemR.pdf` | 47-51 | Scanned regulatory filing forms (low-contrast checkbox tables) |
| `SUPPL_011_210951Orig1s011lbl.pdf` | 1, 5, 10, 20, 30 | Dense prescribing-information labels + drug-interaction tables |
| `210951Orig1s000MultidisciplineR.pdf` | 50, 100, 200 | Long clinical review with figures + study results |
| `DailyMed_label_*.pdf` | 1 | Alternative label format (NLM source) |
| `SUPPL_009_210951.pdf` | 1 | Small supplement letter |

## Aggregate

| Model | Reliability | s/page avg | chars/page avg | Total chars |
|---|---|---|---|---|
| `glm-ocr` | 15/15 | **9.6** ⚡ | 2,070 | 31,053 |
| `lightonocr-2-1b-ocr-soup` | 15/15 | 13.1 | **2,787** | 41,814 |
| `deepseek-ocr` | 15/15 | 11.4 | 2,257 | 33,855 |

## Structure capture

| Model | HTML `<table>` | `## md headers` | `# md headers` | Pipe-table lines |
|---|---|---|---|---|
| `glm-ocr` | 1 | 0 | 0 | 24 (incidental) |
| `lightonocr-2-1b-ocr-soup` | **15** | **19** | **7** | 0 |
| `deepseek-ocr` | 0 | 0 | 1 | 149 |

`SKILL.md`'s hard constraint says inline tables MUST be HTML `<table>` (regulatory tables routinely have rowspans / nested headers; pipe-tables can't represent them). Only `lightonocr-2-1b-ocr-soup` honours this consistently.

## Decision

**Default: `lightonocr-2-1b-ocr-soup`.** Trade-offs accepted:

- 36% slower than `glm-ocr` (3.5s/page extra) — acceptable for the structural quality gain
- `glm-ocr` documented as faster prose-only alternative for batches where structure doesn't matter
- `deepseek-ocr` documented as alternative for users who prefer pipe-tables (against spec, but their call)

Shipped in commit `728ff85` — flipped `--model` defaults in `ocr_page.py` and `ensure_lmstudio.py`, updated SKILL.md / README.md model-selection rows.

## Re-running this benchmark

```bash
# 1. Launch LM Studio desktop application (once)
# 2. Run:
python docs/benchmarks/2026-05-15-local-ocr-models.py
```

The script reads `.env` for any keys (currently only used to skip the LMStudio path during diagnostics — the script is local-only). It expects all three models present in your LM Studio library; modify `LOCAL_OCR_MODELS` in the script to swap.

Output: a JSON sidecar with per-page text + timing for every (model, page) combination, suitable for diffing future runs.

## Open follow-ups

- **Cloud benchmark** (Gemini Gemma 4 31B vs local) was attempted in an earlier round but Gemma 4 returned commentary-wrapped text that violated our prompt's "no commentary" rule, plus 5/10 HTTP 500 errors. Not pursued for OCR; Gemini is reserved for **figure captioning** in Phase 3 instead, where descriptive output is desirable.
- **Higher DPI test** — current 200 DPI is the SKILL.md default; bumping to 300 might help on the lowest-quality scanned forms (ChemR p51 returned only 96-114 chars across all three models). Defer to Phase 2.2 if scanned-form quality becomes a bottleneck during the backfill.
