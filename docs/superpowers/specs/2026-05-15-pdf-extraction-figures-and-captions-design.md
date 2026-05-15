# Phase 3 — Figure extraction + vision captions

**Skill:** `pdf-doc-extraction`
**Date:** 2026-05-15
**Status:** approved (design)
**Predecessors:** Phase 2 (LMStudio OCR — shipped), Phase 2b (Gemini cloud fallback — shipped)
**Successor:** Phase 4 (`assemble_md.py`) — deferred until 3a + 3b ship and we see real outputs

## Goal

Add two new CLI tools to the `pdf-doc-extraction` skill that, together, extract figure images from regulatory PDFs and produce LLM-friendly captions for them — while detecting and properly handling the common case where a "figure" is actually a scanned table.

- **3a — `scripts/extract_figures.py`**: walk each page, find embedded figure regions, write each one as a PNG to `<stem>.assets/figure_pN_fM.png`, capture nearby-text context for the captioner, detect FOI/CBI redactions, write a `<stem>.figures.json` sidecar describing the lot.
- **3b — `scripts/caption_figure.py`**: read `<stem>.figures.json`, send each non-redacted figure image + nearby-text context to a vision model (Gemini default; LMStudio Gemma alternative), get back either a 3-5 sentence caption OR an HTML `<table>` transcription if the figure is actually a scanned table. Write descriptions back into the same JSON.

## Non-goals (deferred)

- **Vector figure detection** — pages with no embedded raster but vector-drawn figures. Phase 3 v1 handles only `page.get_images()` results. If a page has no extractable figures we record nothing for it; users can run `--pages N` to force-render a page region as a fallback. Vector heuristic is Phase 3.1.
- **`assemble_md.py`** — splicing figure references into the final per-page markdown is mechanical once we know the actual JSON shape. Defer to Phase 4.
- **Table re-extraction on OCR'd pages** — tables that PyMuPDF mangled but OCR captured belong to Phase 2 (the OCR text already includes them). Figures-as-tables in Phase 3 are a different beast: the table is a literal raster image, not extractable from the PDF's text layer.
- **Garbage-text filter near figures** — defer until we see real downstream noise.
- **Two-tier image extraction with orientation correction** — Phase 3 v1 trusts PyMuPDF's `extract_image()` byte order; rotation correction can come later.
- **Caption batching / round-robin parallelism for cloud captioning** — `_gemini_with_round_robin` already exists; we'll reuse it but won't add a worker pool yet (sequential per page is fine for v1).

## Hard constraints

- **No PaddleOCR / no new Python deps.** Stdlib + `fitz` (already a dep) only. `_vision_backends.py` already provides the LMStudio + Gemini POST helpers.
- **Default captioning backend is Gemini cloud**, not local LMStudio. Per [[user-hardware]] the 6 GB VRAM caps comfortable local model size at ~4-5B; descriptive captioning on complex PK/KM/dissolution plots wants 26-31B-class models. LMStudio captioning is supported via `--engine lmstudio` for testing/offline, but defaults to Gemini.
- **Refuse OCR-specialized models for captioning.** If `--engine lmstudio --model X` where X matches `OCR_MODEL_PATTERN` (i.e. `/ocr/i`), exit with a clear error: "use a general vision model like `gemma-4-e2b-it` or `gemma-4-e4b-it` for captioning, not an OCR-specialized model." OCR-specialized models like glm-ocr / lightonocr-2 are fine-tuned for verbatim transcription and produce poor descriptive output.
- **Each image is one HTTP POST, no conversation context.** Same constraint as Phase 2 OCR — captions are independent per figure.
- **Substance context inferred from path.** If `--substance` not given, walk the input PDF path looking for the `<substance>/` directory pattern (`apalutamide/FDA/<file>.pdf` → `substance="apalutamide"`); if no match, omit the substance line from the prompt rather than sending wrong info.
- **Don't modify Phase 1 / Phase 2 outputs.** New phase, new sidecars: `<stem>.figures.json` and the `<stem>.assets/` directory. The Phase 4 assembler will merge later.
- **Header-decoration filter is mandatory.** A "figure" whose bbox sits in the top 15% of the page AND whose height is < 8% of the page is almost certainly an agency logo/banner. Drop it. Without this, every page produces a junk figure (per the reference brief — "every regulatory PDF has an agency logo").
- **Redaction detection.** After cropping a figure, check pixel statistics (per-channel std-dev < 15, mean < 245, area > 400 px). If all hold, tag as `(b)(4)` redaction; do NOT send to the vision model (would hallucinate). Mark `redacted: true` in the JSON; description becomes `[REDACTED: (b)(4)]`.
- **Tables-as-figures handling.** Captioner prompt MUST include a rule: "If this image is a scanned table (rows and columns of cell data, with headers), transcribe it as an HTML `<table>` instead of describing it." The captioner output JSON gets a `content_type: "figure" | "table"` field so downstream knows which it is. The captioner detects content type from the model's output (starts with `<table>` → table; else figure).

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `skills/pdf-doc-extraction/scripts/extract_figures.py` | Create | The extractor CLI: walk pages → `page.get_images()` → header filter → extract via `doc.extract_image(xref)` → redaction check → capture nearby text → write PNG + JSON. |
| `skills/pdf-doc-extraction/scripts/caption_figure.py` | Create | The captioner CLI: read `<stem>.figures.json` → for each figure, render prompt template + send to vision backend → write description back to JSON. |
| `skills/pdf-doc-extraction/scripts/_vision_backends.py` | Modify (small) | Add `CAPTION_PROMPT_TEMPLATE` constant. The transcription helpers (`transcribe_lmstudio` / `transcribe_gemini` / `_gemini_with_round_robin`) are already there from Phase 2/2b — reuse as-is. |
| `skills/pdf-doc-extraction/tests/test_extract_figures.py` | Create | Unit tests for header filter, redaction detection, JSON shape, end-to-end against the apalutamide test corpus. |
| `skills/pdf-doc-extraction/tests/test_caption_figure.py` | Create | Unit tests for prompt rendering, content_type detection, mocked-HTTP captioner runs, redaction skip. |
| `skills/pdf-doc-extraction/SKILL.md` | Modify | Mark both tools shipped in the tools table. Add invocation section. Update model-selection to include captioning row. |
| `skills/pdf-doc-extraction/README.md` | Modify | Add quick-starts. |

## CLI contracts

### `extract_figures.py`

```bash
python skills/pdf-doc-extraction/scripts/extract_figures.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/ \
  [--header-fraction 0.15]      # top-of-page exclusion zone
  [--header-min-height 0.08]    # height threshold for header decoration
  [--redaction-stddev 15]       # pixel std-dev threshold for redaction
  [--redaction-mean-max 245]    # mean pixel threshold (gray fill)
  [--min-area-px 400]           # ignore tiny graphics (icons, bullets)
  [--force]                     # rewrite existing figures.json + assets
  [--quiet]
```

Outputs:
- `<out>/<stem>.figures.json` — see schema below
- `<out>/<stem>.assets/figure_pN_fM.png` — one PNG per non-redacted figure (`N` is 1-indexed page, `M` is 1-indexed within page)

### `caption_figure.py`

```bash
python skills/pdf-doc-extraction/scripts/caption_figure.py \
  --figures-json <substance>/<AGENCY>/<file>.figures.json \
  [--substance <name>]          # explicit override; auto-inferred from path otherwise
  [--engine gemini|lmstudio]    # default: gemini
  [--model gemma-4-e4b-it]      # default per --engine: e4b for lmstudio, gemma-4-31b for gemini
  [--api-key ...]               # repeatable; for gemini engine
  [--gemini-models gemma-4-31b-it,gemma-4-26b-a4b-it]  # default for --engine gemini
  [--host http://localhost:1234]  # for --engine lmstudio
  [--timeout 180]
  [--force]                     # re-caption pages already done
  [--quiet]
```

Outputs:
- The same `<stem>.figures.json` is updated in place: each figure entry gets a `description` and `content_type` field added (or overwritten if `--force`).

Validates: refuses `--engine lmstudio --model X` if X matches `OCR_MODEL_PATTERN`. Exits 2 with a clear error pointing at general vision models.

## `<stem>.figures.json` schema

```json
{
  "source_file": "210951Orig1s000MultidisciplineR.pdf",
  "extraction_date": "2026-05-15T...",
  "page_count": 259,
  "figure_count": 14,
  "redacted_count": 2,
  "figures": [
    {
      "figure_id": "p47_f1",
      "page_number": 47,
      "page_index_within": 1,
      "asset_path": "210951Orig1s000MultidisciplineR.assets/figure_p47_f1.png",
      "bbox_normalized": [0.12, 0.30, 0.85, 0.62],
      "extraction_method": "native_extract_image",
      "size_bytes": 48273,
      "width_px": 920,
      "height_px": 640,
      "raw_caption_candidate": "Figure 2. Plasma concentration over 24h...",
      "redacted": false,
      "captioner": null,
      "description": null,
      "content_type": null
    },
    {
      "figure_id": "p51_f1",
      "page_number": 51,
      "page_index_within": 1,
      "asset_path": null,
      "bbox_normalized": [0.45, 0.20, 0.78, 0.40],
      "extraction_method": "native_extract_image",
      "size_bytes": 0,
      "width_px": 200,
      "height_px": 100,
      "raw_caption_candidate": "(b)(4)",
      "redacted": true,
      "captioner": "skipped:redacted",
      "description": "[REDACTED: (b)(4)]",
      "content_type": "redaction"
    }
  ]
}
```

After `caption_figure.py` runs, every `figures[i]` has populated `captioner`, `description`, and `content_type`:

| `content_type` | Set when |
|---|---|
| `"figure"` | Description is prose narrative (default case for plots, photos, schematics) |
| `"table"` | Description starts with `<table` (model produced HTML table transcription) |
| `"redaction"` | `redacted: true` — description is the literal `[REDACTED: (b)(4)]` marker |
| `"error"` | Captioner failed (network, model error); description is empty; `error` field is set |

## Captioning prompt template

Defined as `CAPTION_PROMPT_TEMPLATE` in `_vision_backends.py` (alongside `OCR_PROMPT`):

```
Describe this figure in 3-5 sentences for a scientific reader.

Context:
- Substance: {substance}
- Nearby text from the surrounding document: {nearby_text}
- Caption candidate (if found): {raw_caption_candidate}

Rules:
- If this image is a scanned table (rows and columns of cell data, with
  headers), output an HTML <table> transcription instead of a description.
  Use rowspan/colspan if the table has merged cells.
- Otherwise: identify the figure type (PK plot, forest plot, dissolution
  profile, Kaplan-Meier curve, scatter plot, schematic, photograph, etc.).
  Describe trends and relationships, not specific numeric values.
- If axis labels are readable, state them with units.
- Be consistent with the caption candidate if one is provided.
- Never guess or extrapolate values you cannot clearly read.
- Do not invent. If the image is unreadable, say so.
```

Substitutions:
- `{substance}`: from `--substance` or path inference; if neither found, the prompt drops the "Substance: ..." bullet entirely (line removed via simple template logic, not left as `Substance: None`).
- `{nearby_text}`: `extract_figures.py` captures up to ~600 chars from text blocks within the same page, prioritizing the block immediately above and below the figure bbox; truncated to 600 chars to keep prompt size bounded.
- `{raw_caption_candidate}`: if a text block adjacent to the figure starts with `Figure \d+`, `Table \d+`, or `Fig\.`, capture it (truncated to ~200 chars).

If `nearby_text` and `raw_caption_candidate` are both empty, those bullets are dropped (same template logic as substance).

## Architecture details (per file)

### `extract_figures.py`

| Function | Responsibility |
|---|---|
| `infer_substance(pdf_path: Path) -> str \| None` | Walk parents looking for the `<substance>/<AGENCY>/<file>.pdf` pattern; return the substance name or None. |
| `is_header_decoration(bbox_norm, *, top_fraction, min_height) -> bool` | True if bbox top is in the top fraction AND height is below threshold. |
| `is_redaction(image_bytes) -> bool` | PIL-free check using only `fitz.Pixmap` raw bytes: compute std-dev + mean across the image; True if std-dev < threshold AND mean < threshold AND pixel count > min_area_px. |
| `nearby_text_for_bbox(page, bbox, *, max_chars=600) -> tuple[str, str]` | Returns `(nearby_text, raw_caption_candidate)`. Pulls text blocks within ±5% normalized distance of the figure bbox, prioritizing above/below. Detects "Figure N" / "Table N" prefixes for the caption candidate. |
| `extract_figures_from_page(doc, page_index_zero, *, header_fraction, header_min_height, redaction_thresholds, min_area_px) -> list[dict]` | Per-page workhorse. Yields figure dicts with bbox, raw bytes, nearby text, redaction flag — but does NOT write files (caller writes after dedup). |
| `write_figure_assets(figures, assets_dir) -> list[dict]` | Write PNGs, return figures with `asset_path` populated. |
| `main(argv) -> int` | CLI entry. |

The implementation is intentionally synchronous — figure extraction is a small fraction of the wall-clock vs captioning, so concurrency offers little.

### `caption_figure.py`

| Function | Responsibility |
|---|---|
| `render_prompt(template: str, *, substance: str \| None, nearby_text: str, raw_caption_candidate: str) -> str` | Substitute `{substance}` etc.; drop blank bullets. |
| `detect_content_type(text: str) -> str` | Heuristic: returns `"table"` if text starts with `<table` (case-insensitive, allowing whitespace/markdown); else `"figure"`. |
| `caption_one_figure(figure_entry, *, prompt, engine, backend_kwargs) -> dict` | Read the PNG from `asset_path`, send via `transcribe_lmstudio` or `_gemini_with_round_robin`, return updated entry with `description`, `content_type`, `captioner` set. Per-figure error containment (status: error). |
| `process_figures(figures, *, engine, backend_kwargs, force) -> list[dict]` | Loop helper; skip already-captioned ones unless `--force`. |
| `validate_lmstudio_model_not_ocr(model: str) -> str | None` | Return error string if model matches OCR pattern; else None. |
| `main(argv) -> int` | CLI entry, includes captioning-model-not-OCR validation. |

## Test plan (TDD)

### `test_extract_figures.py` (new file)

| Test | What it verifies |
|---|---|
| `test_infer_substance_from_path` | `apalutamide/FDA/X.pdf` → `"apalutamide"`; arbitrary path → `None`. |
| `test_is_header_decoration_basic` | Bbox at top 5%, 5% height → True; bbox at center → False. |
| `test_is_redaction_uniform_gray` | Synthesize a 100×100 gray image, std=0 → True. |
| `test_is_redaction_real_figure_negative` | Synthesize an image with real variance → False. |
| `test_nearby_text_captures_caption_candidate` | Build a fake page-text-block layout, assert "Figure 2. ..." is captured. |
| `test_extract_figures_runs_on_real_pdf` | Use `apalutamide/FDA/210951Orig1s000MultidisciplineR.pdf`; assert at least one figure extracted, each entry has the required keys. (`pytest.skip` if test corpus missing.) |
| `test_cli_writes_figures_json_and_assets` | End-to-end against a small test PDF; assert `<stem>.figures.json` exists, `<stem>.assets/figure_p*_f*.png` files exist for each non-redacted figure. |

### `test_caption_figure.py` (new file)

| Test | What it verifies |
|---|---|
| `test_render_prompt_drops_empty_bullets` | substance=None and empty nearby_text → those lines absent from rendered prompt. |
| `test_detect_content_type_table` | Text starting `<table>` or `\n<table` → "table". |
| `test_detect_content_type_figure` | Plain prose → "figure". |
| `test_validate_lmstudio_model_not_ocr_rejects_glm_ocr` | Returns non-None error string. |
| `test_validate_lmstudio_model_not_ocr_accepts_gemma` | Returns None for `gemma-4-e4b-it`. |
| `test_caption_one_figure_skips_redacted` | Redacted figure → no HTTP call; description = `[REDACTED: (b)(4)]`. |
| `test_caption_one_figure_lmstudio_path` | Mock `transcribe_lmstudio` to return prose; assert content_type=figure, description set. |
| `test_caption_one_figure_gemini_path` | Mock `_gemini_with_round_robin`; same flow. |
| `test_caption_one_figure_table_detection` | Mock returns `<table>...</table>`; content_type=table. |
| `test_cli_refuses_ocr_specialized_lmstudio_model` | `--engine lmstudio --model glm-ocr` → exit 2, error mentions general vision model. |
| `test_cli_writes_descriptions_back_to_figures_json` | End-to-end with mocked HTTP; verify input figures.json is updated in place with descriptions. |
| `test_cli_force_recaption_overrides_existing` | Pre-seed a figure with a description; without `--force` it's skipped, with `--force` it's re-captioned. |

All tests mock HTTP via the same `_MockResponse` + `patch("urllib.request.urlopen", ...)` pattern from Phase 2.

## Model-selection update for SKILL.md

Replace the existing "Vision captions for figures" row with:

| Decision | Default | Escalate to | Never |
|---|---|---|---|
| Vision captions for figures | **Gemini API free-tier `gemma-4-31b-it` round-robin** with `gemma-4-26b-a4b-it` as fallback | LMStudio `gemma-4-e4b-it` (~4B, fits in 6 GB VRAM) for offline runs; bigger Gemini Gemma variants on rate-limit issues | OCR-specialized models (glm-ocr / lightonocr-2 / deepseek-ocr) — refused at the CLI layer; Sonnet vision sparingly; Opus vision never |

## Open follow-ups (after 3a + 3b ship)

- **Phase 3.1: Vector figure detection** — for pages where `get_images()` returns nothing but `page.get_drawings()` shows non-trivial drawing operations, render the page region as a fallback figure.
- **Phase 4: `assemble_md.py`** — splice text + OCR + figures + captions into the final `<stem>.md`.
- **Backfill** — once Phase 4 ships, run the full pipeline (Phase 1 + 2 + 3 + 4) on the ~30 unextracted PDFs in `apalutamide/`.
- **Honest local-vs-cloud OCR comparison** with a strict no-preamble prompt for Gemma — see [[project-ocr-followups]].
- **Parallel local OCR** for large scanned docs — see [[project-ocr-followups]].

## Review questions resolved during design

| Question | Decision | Reasoning |
|---|---|---|
| 3a + 3b together, or split? | **Together (one phase).** | Captioner needs the extractor's output to be useful at all; ship as a coherent unit. |
| Backend sharing? | **Shared via `_vision_backends.py`** — already done in commit `aa25bce`. | Reuse the same HTTP helpers + round-robin logic from Phase 2/2b. |
| Default captioner backend? | **Gemini cloud.** | 6 GB VRAM caps comfortable local at ~4-5B; descriptive captions on complex plots want 26-31B. LMStudio Gemma 4B is supported via `--engine lmstudio` but not the default. |
| Default Gemini models for captioning? | **`gemma-4-31b-it,gemma-4-26b-a4b-it`** (cross-product with available API keys). | Per user direction — Gemma 4 only, Gemma 3 is "much worse". Available in user's `.env`. |
| Vector figure handling? | **Skip for v1.** | Heuristic risk. Document as Phase 3.1 follow-up. |
| Substance default? | **Infer from path** (`<substance>/<AGENCY>/<file>.pdf` pattern); if not found, omit from prompt. | Less brittle than requiring `--substance` everywhere. |
| Tables-as-figures? | **Captioner detects + transcribes as HTML.** | Per user observation that the previous pipeline misclassified tables as figures. The captioner output `content_type` field tells downstream which it is. |
| Refuse OCR-specialized models for captioning? | **Yes, hard CLI error.** | Different fine-tuning objective; would produce poor captions. Explicit error is more helpful than silent bad output. |
| Header-decoration filter? | **Mandatory** (top 15%, height < 8% → drop). | Per the reference brief: "every regulatory PDF has an agency logo at the top of every page". Without this, every page produces a junk figure. |
| Redaction detection? | **Mandatory** (std-dev + mean + min area thresholds → tag, skip vision call). | FDA `(b)(4)` redactions are gray rectangles; vision models hallucinate descriptions of them. |
