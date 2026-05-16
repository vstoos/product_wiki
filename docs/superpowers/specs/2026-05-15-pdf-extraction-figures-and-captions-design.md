# Phase 3 — Figure extraction + vision captions

**Skill:** `pdf-doc-extraction`
**Date:** 2026-05-15 (revised 2026-05-16 — see "Revisions" at bottom)
**Status:** approved (design, post-review revision)
**Predecessors:** Phase 2 (LMStudio OCR — shipped), Phase 2b (Gemini cloud fallback — shipped)
**Successor:** Phase 4 (`assemble_md.py`) — deferred until 3a + 3b ship and we see real outputs

## Goal

Add two new CLI tools to the `pdf-doc-extraction` skill that, together, extract figure images from regulatory PDFs and produce LLM-friendly captions for them — while detecting and properly handling the common cases where a "figure" is actually a scanned table or an FOI redaction. Outputs make explicit which fields are Tier-1-eligible (verbatim) and which are Tier-2-only (model-generated).

- **3a — `scripts/extract_figures.py`**: walk each page, find embedded figure regions, write each one as a PNG to `<stem>.assets/figure_pN_fM.png`, capture nearby-text context for the captioner, detect FOI/CBI redactions, atomically write a `<stem>.figures.json` sidecar describing the lot, with content + threshold hashes for idempotency.
- **3b — `scripts/caption_figure.py`**: read `<stem>.figures.json`, verify freshness against hashes, send each non-redacted figure image + nearby-text context to a vision model (Gemini default; LMStudio Gemma alternative) using **structured output mode**, get back `{type, content}` that is either a 3-5 sentence caption OR an HTML `<table>` transcription. Atomically write descriptions + captioner provenance back to the JSON.

## Tier 1 / Tier 2 contract for figure-derived evidence

Per `CLAUDE.md`, Tier 1 facts MUST carry a 15-20-word verbatim snippet that literally appears in the source. Vision-model captions are model-generated and have no such anchor by construction. This phase resolves the contract upfront so `wiki-pharma-extraction` (and the future `assemble_md.py`) cannot accidentally promote model output to Tier 1.

| Field | Origin | Tier eligibility | Verbatim anchor |
|---|---|---|---|
| `raw_caption_candidate` | Literal text block adjacent to figure bbox (PyMuPDF text layer) | **Tier 1 OK** — verbatim text from the PDF on the figure's page | Yes — page_number + bbox |
| `page_text_verbatim` | Full page text in document order, captured once per page via PyMuPDF `page.get_text()` | **Tier 1 OK** for any 15-20-word substring that appears verbatim and contiguously on the cited page (preserved order makes this trivially checkable) | Yes — page_number |
| `nearby_text` | Text blocks on the page, ranked closest-first by distance to figure bbox; **captioner-context only** | **Not Tier-1-eligible** — closest-first ordering produces stitched strings that may not appear contiguously in the source; use `page_text_verbatim` for Tier 1 instead | n/a (prompt-context only) |
| `description` | Vision-model output (caption OR table transcription) | **Tier 2 only** — model-generated, not present in source | No |
| `asset_path` (PNG) | PyMuPDF `extract_image()` | Tier 1 evidence ID (page + figure_id) — link or embed, do not quote pixels as text | Yes — page_number |

Implications for downstream:

- A Tier 1 fact derived from a figure MUST cite a contiguous substring of `raw_caption_candidate` or `page_text_verbatim`, NOT of `description` or `nearby_text`.
- A figure whose page has neither a recognisable caption candidate nor any useful verbatim text on the page CANNOT be cited in Tier 1 — only described in Tier 2 with a `[[wikilink]]` back to the figure asset.
- `description` carries machine-attestation metadata (`captioner`, `prompt_hash`) so audits can identify which model+prompt produced which caption. That is sufficient for Tier 2 provenance; it is NOT a substitute for a Tier 1 verbatim anchor.
- `nearby_text` exists so the captioner sees document context with the most relevant blocks first; do not cite from it.
- Validator Rule 2 ("Tier 2 contains zero `[DOC_ID]` brackets") still holds. `wiki-pharma-extraction` will add a parallel Rule 2b: "no Tier 1 fact may cite a substring of `description` or `nearby_text`; only `raw_caption_candidate` or `page_text_verbatim` are citable." See "Downstream integration" below.

### Worked examples

**OK as Tier 1** (cites `raw_caption_candidate`):
```
Cmax of apalutamide increased dose-proportionally over 30-480 mg.
[210951Orig1s000MultidisciplineR.pdf | clinical_pharm | figure_p87_f2 | p.87]
Verbatim: "Figure 2. Mean (+/-SD) plasma concentration of apalutamide following single oral doses."
```

**NOT OK as Tier 1** (cites `description`):
```
The PK profile shows biphasic decline with rapid distribution followed by slower elimination.
[210951Orig1s000MultidisciplineR.pdf | clinical_pharm | figure_p87_f2 | p.87]
Verbatim: (description text - INVALID, model-generated)
```

**OK as Tier 2 synthesis** (description allowed, no verbatim required):
```
The PK profile shows biphasic decline with rapid distribution followed by slower elimination
([[apalutamide-clinical-pharm#figure_p87_f2]]).
```

## Non-goals (deferred)

- **Vector figure detection** — pages with no embedded raster but vector-drawn figures. Phase 3 v1 handles only `page.get_images()` results. See "Coverage expectations" for expected per-source loss; the EMA EPAR is the headline gap. Vector heuristic is Phase 3.1.
- **`assemble_md.py`** — splicing figure references into the final per-page markdown is mechanical once we know the actual JSON shape. Defer to Phase 4.
- **Table re-extraction on OCR'd pages** — tables that PyMuPDF mangled but OCR captured belong to Phase 2 (OCR text already includes them). Figures-as-tables in Phase 3 are different: the table is a literal raster image, not extractable from the PDF's text layer.
- **Garbage-text filter near figures** — defer until we see real downstream noise.
- **Two-tier image extraction with orientation correction** — Phase 3 v1 trusts PyMuPDF's `extract_image()` byte order; rotation correction can come later.
- **Caption batching / parallelism for cloud captioning** — `_gemini_with_round_robin` already exists; reuse but no worker pool yet (sequential per figure is fine for v1).
- **Per-figure-type prompt variants** — see Q3 below. One coherent prompt covers both discrete-value and continuous-curve modes.
- **Bordered / white-fill redaction detection** — Phase 3 v1 calibrates against `(b)(4)` gray rectangles only (the dominant FDA pattern). White-fill `(b)(6)` and bordered redactions are a Phase 3.2 follow-up; until then they slip through as "real figures" and the vision model will produce a caption like "uniform white rectangle, possibly a redaction" — visible to a reviewer.

## Hard constraints

- **No PaddleOCR / no new Python deps.** Stdlib + `fitz` (already a dep) only. `_vision_backends.py` already provides the LMStudio + Gemini POST helpers; this phase adds structured-output variants.
- **Default captioning backend is Gemini cloud**, not local LMStudio. Per [[user-hardware]] the 6 GB VRAM caps comfortable local model size at ~4-5B; descriptive captioning on complex PK/KM/dissolution plots wants 26-31B-class models. LMStudio captioning is supported via `--engine lmstudio` for testing/offline, but defaults to Gemini.
- **Captioning model denylist (explicit set, not regex).** Hard CLI error if `--engine lmstudio --model X` where X is in `CAPTION_DENYLIST = {"glm-ocr", "lightonocr-2-1b-ocr-soup", "deepseek-ocr"}`. OCR-specialized models are fine-tuned for verbatim transcription and produce poor descriptive output. The Phase 2 `OCR_MODEL_PATTERN` regex is retained for prompt-selection heuristics (where false positives are harmless — image-only requests work on general models too, just suboptimally); captioning refusal uses the explicit set so a future general vision model named "vision-ocr-1" isn't blocked.
- **Each image is one HTTP POST in structured-output mode.** Per-image isolation (no conversation context). The POST requests a structured `{type, content}` response (Gemini `response_schema`; LMStudio `response_format: {"type": "json_object"}` + schema embedded in prompt). No string-prefix heuristics for table-vs-figure detection — routing is determined by the structured `type` field.
- **Substance context comes from `<substance>/metadata.json` if present; path-inference is the fallback.** A per-substance `metadata.json` (e.g. `apalutamide/metadata.json` with `{"inn": "apalutamide", "brand_names": ["Erleada"], "atc": "L02BB05"}`) is the durable, structured source. If absent, walk the path looking for the `<substance>/<AGENCY>/<file>.pdf` pattern. If both fail, omit the substance line from the prompt. The sidecar records `substance_source` so downstream knows which path was taken.
- **Don't modify Phase 1 / Phase 2 outputs.** New phase, new sidecars: `<stem>.figures.json` and the `<stem>.assets/` directory. The Phase 4 assembler will merge later.
- **Header-decoration filter is always-on with calibratable thresholds.** Defaults: top 15%, height < 8% → drop. The flags exist for ops calibration against new sources, not for "disable in production." Dropped candidates are logged in the sidecar (`dropped_header_decorations[]`) for audit; if a real figure is being dropped we can see it without re-running extraction.
- **Redaction detection.** After cropping a figure, check pixel statistics. Defaults: std-dev < 15, mean < 245, area > 400 px → tag as `(b)(4)` redaction, do NOT send to the vision model. `redacted: true`; `description` becomes `[REDACTED: (b)(4)]`. Default thresholds are calibrated against the apalutamide corpus during Task 5 (see "Calibration corpus" in the test plan).
- **Tables-as-figures handling.** Structured output forces the model to declare `type: "table" | "figure"`. For `type: "table"`, `content` is HTML `<table>...</table>`. For `type: "figure"`, `content` is a 3-5 sentence description. No prefix sniffing.
- **Atomic writes for `<stem>.figures.json`.** Write to `<stem>.figures.json.tmp` then `os.replace()`. Crash mid-write does not corrupt the canonical file. PNGs are written before the JSON to keep the JSON as the consistency anchor.
- **Content-hash idempotency.** `<stem>.figures.json` includes `source_pdf_sha256` (preferred from `<stem>.meta.json` if Phase 1 wrote one, else computed) and `extractor_thresholds_hash` (SHA-256 of the threshold tuple). The captioner refuses to run against a sidecar whose hashes don't match the current PDF + extractor defaults, unless `--force` or `--accept-stale` is passed.

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `skills/pdf-doc-extraction/scripts/extract_figures.py` | Create | The extractor CLI: walk pages → `page.get_images()` → header filter (with audit log) → extract via `doc.extract_image(xref)` → redaction check → capture nearby text → atomic-write PNG + JSON with hashes. |
| `skills/pdf-doc-extraction/scripts/caption_figure.py` | Create | The captioner CLI: read `<stem>.figures.json`, check freshness against hashes, request structured output from vision backend, atomic-write descriptions + provenance back to JSON. |
| `skills/pdf-doc-extraction/scripts/_vision_backends.py` | Modify | Add `CAPTION_PROMPT_TEMPLATE`, `CAPTION_DENYLIST`, plus structured-output helpers `transcribe_lmstudio_structured` and `transcribe_gemini_structured` returning `(type, content)`. |
| `skills/pdf-doc-extraction/tests/test_extract_figures.py` | Create | Unit tests + corpus-calibrated redaction test + header-filter audit-log tests + hash/atomic-write tests. |
| `skills/pdf-doc-extraction/tests/test_caption_figure.py` | Create | Unit tests + structured-output parse tests + freshness-check tests + denylist enforcement + rate-budget tests. |
| `skills/pdf-doc-extraction/SKILL.md` | Modify | Mark both tools shipped, document Tier-1/Tier-2 contract, model-selection row. |
| `skills/pdf-doc-extraction/README.md` | Modify | Quick-starts. |

## CLI contracts

### `extract_figures.py`

```bash
python skills/pdf-doc-extraction/scripts/extract_figures.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/ \
  [--header-fraction 0.15]         # top-of-page exclusion zone (ops calibration)
  [--header-min-height 0.08]       # height threshold below which header items dropped
  [--redaction-stddev 15]          # pixel std-dev threshold for redaction
  [--redaction-mean-max 245]       # mean pixel threshold (gray fill)
  [--min-area-px 400]              # ignore tiny graphics
  [--nearby-text-max-chars 2500]   # nearby-text truncation for prompt context
  [--force]                        # rewrite existing figures.json + assets
  [--quiet]
```

Outputs:
- `<out>/<stem>.figures.json` (atomic write via `.tmp` + `os.replace`)
- `<out>/<stem>.assets/figure_pN_fM.png` (one PNG per non-redacted figure)

### `caption_figure.py`

```bash
python skills/pdf-doc-extraction/scripts/caption_figure.py \
  --figures-json <substance>/<AGENCY>/<file>.figures.json \
  [--substance <name>]             # override; otherwise metadata.json -> path -> none
  [--engine gemini|lmstudio]       # default: gemini
  [--model gemma-4-e4b-it]         # default per engine
  [--api-key ...]                  # repeatable; gemini only
  [--gemini-models gemma-4-31b-it,gemma-4-26b-a4b-it]
  [--host http://localhost:1234]   # lmstudio only
  [--timeout 180]
  [--force]                        # re-caption already-done; bypass freshness check
  [--accept-stale]                 # caption against a stale sidecar (logs warning)
  [--check-stale]                  # exit 0 with summary if sidecar is stale; no HTTP
  [--rate-budget-calls N]          # hard stop after N successful calls; partial save
  [--quiet]
```

Refusal / freshness behaviors:

- `--engine lmstudio --model X` where X is in `CAPTION_DENYLIST` → exit 2, error pointing at general vision models.
- Sidecar's `source_pdf_sha256` doesn't match the current PDF (looked up via co-located `<stem>.meta.json` or recomputed) → exit non-zero, suggest `--accept-stale` or re-running `extract_figures.py`. Bypass with `--accept-stale` or `--force`.
- Sidecar's `extractor_thresholds_hash` differs from current extractor defaults → same behavior.
- `--check-stale` → loads sidecar, runs freshness check, prints summary, exit 0 with no HTTP calls.
- All writes via tmp + `os.replace`.

## `<stem>.figures.json` schema

```json
{
  "schema_version": "1.0",
  "source_file": "210951Orig1s000MultidisciplineR.pdf",
  "source_pdf_sha256": "abc123...",
  "extraction_date": "2026-05-15T10:30:00Z",
  "extractor_version": "extract_figures.py@2026-05-15",
  "extractor_thresholds": {
    "header_fraction": 0.15,
    "header_min_height": 0.08,
    "redaction_stddev": 15,
    "redaction_mean_max": 245,
    "min_area_px": 400,
    "nearby_text_max_chars": 2500
  },
  "extractor_thresholds_hash": "def456...",
  "substance": "apalutamide",
  "substance_source": "metadata_json",
  "page_count": 259,
  "figure_count": 14,
  "redacted_count": 2,
  "dropped_header_decorations": [
    {"page_number": 1, "bbox_normalized": [0.05, 0.01, 0.95, 0.05], "size_bytes": 1234, "reason": "header_band"}
  ],
  "captioning_date": "2026-05-15T11:00:00Z",
  "captioning_engine": "gemini",
  "captioning_seconds": 312.5,
  "figures": [
    {
      "figure_id": "p47_f1",
      "page_number": 47,
      "page_index_within": 1,
      "asset_path": "210951Orig1s000MultidisciplineR.assets/figure_p47_f1.png",
      "asset_sha256": "...",
      "bbox_normalized": [0.12, 0.30, 0.85, 0.62],
      "extraction_method": "native_extract_image",
      "size_bytes": 48273,
      "width_px": 920,
      "height_px": 640,
      "raw_caption_candidate": "Figure 2. Plasma concentration over 24h...",
      "raw_caption_candidate_tier": 1,
      "page_text_verbatim": "Page 47 full text in document order, exactly as page.get_text() returns it...",
      "page_text_verbatim_tier": 1,
      "nearby_text": "Figure 2. Plasma concentration over 24h... Source: Sponsor analysis. Section header text further away...",
      "nearby_text_tier": null,
      "redacted": false,
      "captioner": "gemini:gemma-4-31b-it@2026-05-15",
      "prompt_hash": "sha256:abc...",
      "description": "Mean plasma concentration of apalutamide following 240 mg single oral dose...",
      "description_tier": 2,
      "content_type": "figure",
      "error": null
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
      "raw_caption_candidate_tier": 1,
      "page_text_verbatim": "Page 51 full text including the (b)(4) marker in document order...",
      "page_text_verbatim_tier": 1,
      "nearby_text": "",
      "nearby_text_tier": null,
      "redacted": true,
      "captioner": "skipped:redacted",
      "prompt_hash": null,
      "description": "[REDACTED: (b)(4)]",
      "description_tier": null,
      "content_type": "redaction",
      "error": null
    },
    {
      "figure_id": "p100_f1",
      "page_number": 100,
      "page_index_within": 1,
      "asset_path": "...assets/figure_p100_f1.png",
      "bbox_normalized": [0.10, 0.10, 0.90, 0.50],
      "extraction_method": "native_extract_image",
      "size_bytes": 18234,
      "width_px": 800,
      "height_px": 400,
      "raw_caption_candidate": "",
      "raw_caption_candidate_tier": 1,
      "page_text_verbatim": "Page 100 full text in document order...",
      "page_text_verbatim_tier": 1,
      "nearby_text": "...",
      "nearby_text_tier": null,
      "redacted": false,
      "captioner": "gemini:error",
      "prompt_hash": "sha256:...",
      "description": "",
      "description_tier": null,
      "content_type": "error",
      "error": "HTTPError: 500 Internal Server Error from gemma-4-31b-it"
    }
  ]
}
```

`content_type` semantics:

| `content_type` | Set when | `description` | `error` |
|---|---|---|---|
| `"figure"` | Structured output returned `type: "figure"` | 3-5 sentence prose | null |
| `"table"` | Structured output returned `type: "table"` | HTML `<table>...</table>` | null |
| `"redaction"` | `redacted: true` (no model call) | literal `[REDACTED: (b)(4)]` | null |
| `"error"` | Captioner exception (network, model error, structured-output parse error) | `""` | error string |

`description_tier` is null for `redaction` and `error` (no meaningful Tier-2 content); otherwise `2`.

**`*_tier` sentinel convention.** All `*_tier` fields are explicit: `1` (Tier-1-eligible, verbatim source-anchored), `2` (Tier-2-only, model-generated), or `null` (not applicable — no citable content for this entry, e.g. `description_tier` on a `redaction` or `error` row, or `nearby_text_tier` on every row since it is captioner-context only and never citable). A missing key is a schema violation; validators MUST reject sidecars where any expected `*_tier` field is absent. This rules out the ambiguity of "absent vs null" and gives `wiki-pharma-extraction`'s Rule 2b a clean predicate to check.

## Captioning prompt template

Defined as `CAPTION_PROMPT_TEMPLATE` in `_vision_backends.py`. The model receives this prompt AND a structured-output schema declaring the response shape `{type, content}`. The prompt's job is to clarify what goes in `content` for each `type`; routing is determined by the structured field, not by string prefixes.

```
You will receive a figure image from a regulatory document. Output a JSON
object with exactly two fields:
  - "type": one of "figure" or "table"
  - "content": see rules below

Context:
- Substance: {substance}
- Nearby text from the surrounding document: {nearby_text}
- Caption candidate (if found): {raw_caption_candidate}

Rules for type="table":
- Use this type if the image is a scanned table (rows and columns of cell
  data with headers, and no plotting elements).
- "content" is an HTML <table> transcription using rowspan/colspan for
  merged cells. Preserve cell text verbatim. No surrounding prose.

Rules for type="figure":
- Use this type for plots, charts, schematics, photographs, micrographs.
- "content" is a 3-5 sentence description.
- State the figure type (PK plot, dissolution profile, Kaplan-Meier curve,
  forest plot, scatter plot, schematic, photograph, etc.) in sentence 1.
- State axis labels and units if visible.
- Values policy (this resolves the apparent tension between "describe
  trends" and "state readable values"):
   * Discrete labeled data points - dissolution % at named timepoints,
     mean +/- SD bars with annotated values, table-like overlays:
     transcribe the values literally. These are part of the figure's data.
   * Continuous curves - Kaplan-Meier survival, scatter, dose-response,
     concentration-time profiles without per-point labels: describe shape
     and inflection points; do NOT interpolate specific values from the
     curve.
- Always describe trends and relationships visible in the data.
- Be consistent with the caption candidate if one is provided.
- Never invent. If the image is unreadable, set content to "[UNREADABLE]".

Output: a single JSON object, no surrounding prose, no markdown fences.
```

Substitutions:
- `{substance}`: from `--substance`, then `<substance>/metadata.json::inn`, then path inference; if none, the prompt drops the "Substance:" line entirely.
- `{nearby_text}`: extractor captures all text blocks on the page, ranks by distance to figure bbox (closest first), concatenates up to `--nearby-text-max-chars` (default 2500).
- `{raw_caption_candidate}`: if any text block on the page starts with `Figure \d+`, `Table \d+`, or `Fig\.`, capture the first match (truncated to ~200 chars).

If `nearby_text` and `raw_caption_candidate` are both empty, those lines are dropped (template helper).

`prompt_hash` in the sidecar is `sha256(rendered_prompt)[:16]` — lets us identify which prompt revision produced a caption when the template changes.

## Structured output mechanics

**Gemini**: pass `response_mime_type: "application/json"` and `response_schema`:

```json
{
  "type": "object",
  "properties": {
    "type": {"type": "string", "enum": ["figure", "table"]},
    "content": {"type": "string"}
  },
  "required": ["type", "content"]
}
```

**LMStudio (OpenAI-compatible)**: pass `response_format: {"type": "json_object"}`. Include the schema verbatim in the prompt (LMStudio's OpenAI-compat layer supports JSON mode but not arbitrary JSON Schema enforcement). Parse the model's JSON; validate against the schema. On parse failure or schema mismatch, return `(None, raw_text)` so the caller records `content_type: "error"`, `error: "structured-output parse failed: <detail>"`.

Both helpers (`transcribe_lmstudio_structured`, `transcribe_gemini_structured`) live in `_vision_backends.py` and return a `(type, content)` tuple on success, `(None, raw_text)` on parse failure. HTTP errors raise as before (caller catches per-figure).

## Coverage expectations (against apalutamide corpus)

Per-source expected figure yield from Phase 3a v1 (raster only). These bound the regression assertion in `test_extract_figures.py` (±20% tolerance):

| Source | Document | Expected raster figure yield | Vector loss expected |
|---|---|---|---|
| FDA NDA | `210951Orig1s000ChemR.pdf` (~70 pp, scanned) | 5-15 | None (scanned, all raster) |
| FDA NDA | `210951Orig1s000MultidisciplineR.pdf` (259 pp, clinical review) | 40-80 | Low (mostly raster) |
| FDA Label | `SUPPL_011_210951Orig1s011lbl.pdf` (~30 pp, label) | 0-5 (mostly text) | None |
| EMA | EPAR Assessment 2019+ (when ingested) | Lower than FDA for same page count | **High — vector-drawn plots common; Phase 3.1 target** |
| HC | Product Monograph | Low (tables dominate) | Medium |

The actual numeric expected values for the regression assertion are seeded during the first benchmark run on the apalutamide corpus, recorded in a `COVERAGE_EXPECTATIONS` constant in `test_extract_figures.py`, and pinned within ±20%. This makes silent under-coverage visible across re-fetches and PyMuPDF version changes.

**EMA vector-loss is the headline gap.** The EMA EPAR for apalutamide (2019) is expected to under-yield in v1. Phase 3.1 (`page.get_drawings()` + render fallback) closes this. The SKILL.md model-selection section will state this clearly so users know EMA captions will be sparse until 3.1 ships.

## Resumption + rate budget

Free-tier Gemini gives ~90k calls/day per model (per [[project-free-compute-strategy]]). The apalutamide corpus has ~30 PDFs × ~14 figures average = ~420 captioning calls — well within budget for a single backfill run.

Behaviors when something goes wrong:

| Condition | Behavior |
|---|---|
| Single (api_key, model) pair returns 429 for one figure | Round-robin advances; no error recorded |
| All round-robin pairs return 429 for one figure | Mark figure `content_type: "error"`, `error: "all gemini pairs exhausted (429)"`, continue with next figure |
| Network / 5xx error | Per-figure error; continue |
| Structured-output parse error | Per-figure error with raw text in the error string for debugging |
| `--rate-budget-calls N` reached | Stop AFTER finishing the in-flight figure; atomic-write the partial JSON; exit 0 with summary noting `budget_exhausted: true`. Resume by re-running (already-captioned figures skipped unless `--force`). |
| Many consecutive errors | Same — record per-figure error; do not abort. User reruns later; rerun skips successes and retries errors. |

Atomic-write invariant means crash recovery is "rerun the command" — already-done figures are skipped, errored figures are retried.

## Architecture details (per file)

### `extract_figures.py`

| Function | Responsibility |
|---|---|
| `load_substance_metadata(pdf_path: Path) -> dict | None` | Walk parents looking for `<substance>/metadata.json`; return parsed dict or None. |
| `infer_substance(pdf_path: Path) -> tuple[str | None, str]` | Returns `(substance, source)` where source ∈ `{"metadata_json", "path_inference", "none"}`. Prefers metadata. |
| `is_header_decoration(bbox_norm, *, top_fraction, min_height) -> bool` | True if bbox top is in the top fraction AND height is below threshold. |
| `is_redaction(image_bytes, *, stddev_max, mean_max, min_area_px) -> bool` | PIL-free check via `fitz.Pixmap`. Pure function for testing. |
| `page_text_verbatim(page) -> str` | Returns full page text in document order via `page.get_text()`. Page-ordered, contiguous — citable as Tier 1. Captured once per page, attached to every figure on that page. |
| `nearby_text_for_bbox(page, bbox, *, max_chars) -> tuple[str, str]` | Returns `(nearby_text, raw_caption_candidate)`. Captures ALL text blocks on the page, ranks by distance to figure bbox, concatenates closest-first up to max_chars. Detects `Figure N` / `Table N` for the caption candidate. Output is captioner-context only — **not** citable as Tier 1 (use `page_text_verbatim` instead). |
| `extract_figures_from_page(doc, page_index_zero, *, header_fraction, header_min_height, redaction_thresholds, min_area_px, nearby_text_max_chars) -> tuple[list[dict], list[dict]]` | Returns `(figures, dropped_header_decorations)` for one page. Every figure dict includes `page_text_verbatim` (computed once per page, shared across that page's figures) and `nearby_text` (per-figure, distance-ranked). |
| `write_figure_assets(figures, assets_dir) -> list[dict]` | Write PNGs (non-redacted), compute `asset_sha256`, return enriched entries with `image_bytes` stripped. |
| `hash_thresholds(thresholds: dict) -> str` | SHA-256 hex of JSON-canonicalized threshold dict. |
| `compute_pdf_sha256(pdf_path: Path) -> str` | Look up `<stem>.meta.json::sha256` if present; else compute. |
| `atomic_write_json(path: Path, payload: dict) -> None` | Write to `path.tmp`, fsync, `os.replace`. |
| `main(argv) -> int` | CLI entry. |

### `caption_figure.py`

| Function | Responsibility |
|---|---|
| `render_prompt(*, substance: str | None, nearby_text: str, raw_caption_candidate: str) -> str` | Substitute `{substance}` etc.; drop blank lines for empty values. |
| `compute_prompt_hash(rendered_prompt: str) -> str` | `sha256(rendered_prompt)[:16]`. |
| `check_sidecar_freshness(sidecar: dict, pdf_path: Path, current_thresholds_hash: str) -> str | None` | Returns None if fresh; else a diagnostic string. |
| `caption_one_figure(figure_entry, *, prompt, prompt_hash, captioner_label, engine, backend_kwargs) -> dict` | Read PNG, call structured-output backend, populate `description`/`content_type`/`captioner`/`prompt_hash`/`error`. Per-figure error containment. |
| `process_figures(figures, *, substance, engine, backend_kwargs, force, rate_budget_calls) -> tuple[list[dict], dict]` | Loop helper; honours skip-if-done, budget cap; returns (entries, run_stats). |
| `validate_captioning_model(engine: str, model: str) -> str | None` | engine=lmstudio + model in `CAPTION_DENYLIST` → error string; else None. |
| `atomic_write_json(path: Path, payload: dict) -> None` | Same helper as extractor. |
| `main(argv) -> int` | CLI entry. |

## Test plan (TDD)

### `test_extract_figures.py`

| Test | What it verifies |
|---|---|
| `test_infer_substance_via_metadata_json_wins` | Fake `<substance>/metadata.json` present → uses it; source = "metadata_json". |
| `test_infer_substance_falls_back_to_path` | No metadata → path heuristic; source = "path_inference". |
| `test_infer_substance_none_when_both_missing` | Returns (None, "none"). |
| `test_is_header_decoration_basic` | Bbox top 5% / 5% height → True; bbox center → False. |
| `test_is_header_decoration_top_but_tall` | Top of page but 35% tall → False. |
| `test_is_redaction_uniform_gray` | Synthesize 100x100 gray, std=0 → True. |
| `test_is_redaction_real_figure_negative` | High-variance image → False. |
| `test_is_redaction_too_small_negative` | Tiny image → False (below min_area). |
| `test_is_redaction_white_too_bright_negative` | Mean > 245 → False (page bg, not redaction). |
| `test_is_redaction_against_known_corpus_redactions` | **Calibration test:** load known `(b)(4)` pages from apalutamide corpus (`KNOWN_REDACTIONS` constant), assert detector flags them. SKIP if corpus missing. |
| `test_nearby_text_captures_caption_candidate` | Fake page-text-block layout → "Figure 2. ..." captured. |
| `test_nearby_text_ranks_by_distance` | Multiple blocks at varying distances → closer-first in nearby_text. |
| `test_nearby_text_truncates_to_max_chars` | Total > max_chars → truncated; no mid-word cut required (whitespace boundary OK). |
| `test_page_text_verbatim_preserves_document_order` | Fake page with three blocks in known order → `page_text_verbatim` matches `page.get_text()` output (document order, not distance-ranked). Distinct from `nearby_text` which reorders. |
| `test_page_text_verbatim_attached_to_every_figure_on_page` | Page with two figures → both entries carry identical `page_text_verbatim`; captured once per page, not per figure. |
| `test_extract_figures_from_page_returns_dropped_decorations` | Page with header logo + real figure → figures=[real], dropped=[logo]. |
| `test_extract_figures_runs_on_real_pdf` | Against MultidisciplineR → figure count within `COVERAGE_EXPECTATIONS` band. SKIP if fixture missing. |
| `test_cli_writes_figures_json_and_assets` | E2E: `<stem>.figures.json` + assets dir exist. |
| `test_cli_writes_atomic` | Patch `os.replace` to raise; assert canonical file unchanged (tmp may exist). |
| `test_cli_records_source_pdf_sha256_and_thresholds_hash` | New sidecar contains both fields, non-empty hex. |
| `test_cli_changing_thresholds_changes_hash` | Re-run with different `--header-fraction` → different `extractor_thresholds_hash`. |
| `test_cli_logs_dropped_header_decorations` | E2E: real PDF with a logo → `dropped_header_decorations` non-empty in JSON. |

### `test_caption_figure.py`

| Test | What it verifies |
|---|---|
| `test_render_prompt_drops_empty_bullets` | substance=None and empty nearby → those lines absent. |
| `test_render_prompt_handles_full_substitution` | All fields present → no `{...}` leftover. |
| `test_compute_prompt_hash_is_deterministic` | Same input → same 16-char hash. |
| `test_check_sidecar_freshness_passes_when_hashes_match` | Match → returns None. |
| `test_check_sidecar_freshness_fails_when_pdf_changed` | PDF hash differs → diagnostic string. |
| `test_check_sidecar_freshness_fails_when_thresholds_differ` | Thresholds hash differs → diagnostic. |
| `test_validate_captioning_model_rejects_denylist` | Each of `{glm-ocr, lightonocr-2-1b-ocr-soup, deepseek-ocr}` → non-None error. |
| `test_validate_captioning_model_accepts_general_vision` | `gemma-4-e4b-it`, `gemma-4-31b-it` → None. |
| `test_caption_one_figure_skips_redacted` | Redacted → no HTTP call; description = `[REDACTED: (b)(4)]`. |
| `test_caption_one_figure_lmstudio_structured` | Mock returns `{"type":"figure","content":"..."}` → parsed; content_type=figure. |
| `test_caption_one_figure_gemini_structured_table` | Mock returns `{"type":"table","content":"<table>..."}` → content_type=table. |
| `test_caption_one_figure_records_parse_error` | Mock returns garbage text → content_type=error, error mentions "parse". |
| `test_caption_one_figure_records_http_error` | Mock raises HTTPError → content_type=error, error has detail. |
| `test_cli_refuses_ocr_specialized_lmstudio_model` | exit 2; stderr mentions general vision model. |
| `test_cli_writes_descriptions_atomically` | Patch `os.replace` to raise; canonical sidecar unchanged. |
| `test_cli_writes_captioner_with_date_and_prompt_hash` | New entries have `captioner: "gemini:gemma-4-31b-it@YYYY-MM-DD"` format and 16-char `prompt_hash`. |
| `test_cli_refuses_stale_sidecar_without_force` | PDF hash mismatch → exit non-zero; no HTTP. |
| `test_cli_accept_stale_overrides_freshness_check` | `--accept-stale` → proceeds with warning. |
| `test_cli_check_stale_returns_summary_no_calls` | `--check-stale` → no HTTP, exit 0, prints diagnostic. |
| `test_cli_rate_budget_stops_after_N` | `--rate-budget-calls 3` → exactly 3 backend calls; partial JSON written; `budget_exhausted: true`. |
| `test_cli_resume_skips_done_continues_errors` | Pre-seed mixed entries → only error+null re-attempted. |

All HTTP mocked via the existing `_MockResponse` + `patch("urllib.request.urlopen", ...)` pattern.

**Calibration corpus** for redaction test: documented in `test_extract_figures.py` as a list `KNOWN_REDACTIONS = [(pdf_filename, page_number, expected_bbox_normalized), ...]`. Seeded by running `extract_figures.py` against the apalutamide corpus once, eyeballing the `dropped_header_decorations` + flagged figures, and recording known `(b)(4)` cases. Maintained as the corpus grows.

**Chicken-and-egg note:** to avoid blocking the ship on a calibration loop, ship the defaults from FDA `(b)(4)` literature norms first (gray fill ≈ `#CCCCCC`, std-dev < 15, mean < 245, area > 400 px). After Tasks 3-7 land, run `extract_figures.py` on the apalutamide corpus once, eyeball flagged figures and known unflagged `(b)(4)` pages, and seed `KNOWN_REDACTIONS` from that observed list. The calibration test then pins the corpus going forward. Do NOT block Phase 3a shipping on a hand-labelled corpus that doesn't exist yet.

## Model-selection update for SKILL.md

Replace the existing "Vision captions for figures" row with:

| Decision | Default | Escalate to | Never |
|---|---|---|---|
| Vision captions for figures | **Gemini API free-tier `gemma-4-31b-it,gemma-4-26b-a4b-it` round-robin, structured-output mode (`{type, content}`)** | LMStudio `gemma-4-e4b-it` (~4B, fits 6 GB VRAM) for offline runs | Models in `CAPTION_DENYLIST` (`glm-ocr`, `lightonocr-2-1b-ocr-soup`, `deepseek-ocr`) — refused at CLI; Sonnet vision sparingly; Opus vision never |

## Downstream integration

This phase's outputs are consumed by two downstream skills. The contract is fixed at design time (not integration time) to prevent silent Tier 1 promotion of model-generated content.

### For `assemble_md.py` (Phase 4)

Reads three sidecars per PDF: `<stem>.md` (Phase 1 text), `<stem>.ocr.json` (Phase 2 OCR), `<stem>.figures.json` (Phase 3). Splices into a final `<stem>.hybrid.md`.

Required figure block at the figure's `page_number`:

- `asset_path` (relative) → embedded image
- `figure_id` → markdown anchor for wikilinks (`<a id="figure_p47_f1"></a>`)
- `raw_caption_candidate` → printed as the visible caption (this is the Tier-1-eligible verbatim)
- `description` → printed as italic annotation labelled `(machine caption — Tier 2)` so downstream readers and `wiki-pharma-extraction` see the tier separation in the assembled markdown
- `content_type: "table"` → render `description` (the HTML table) directly inline, no italic wrapper
- `redacted` → render a literal `[FIGURE REDACTED: (b)(4) — see p.N]` placeholder, no asset link
- `content_type: "error"` → render `[FIGURE EXTRACTION FAILED: see <stem>.figures.json::figure_id=<id>]`, no asset link, so the user can investigate

### For `wiki-pharma-extraction`

- Tier 1 facts derived from figures MUST cite a contiguous substring of `raw_caption_candidate` or `page_text_verbatim`. The validator already enforces Rule 2 ("no `[DOC_ID]` brackets in Tier 2"); a new Rule 2b should be added in `wiki-pharma-extraction`: "no Tier 1 fact may cite a substring of `description` or `nearby_text`; only `raw_caption_candidate` or `page_text_verbatim` of the cited figure are valid Tier 1 anchors." This is enforceable because the validator can load `<stem>.figures.json`. The contiguity check is trivial for `page_text_verbatim` because it preserves document order (unlike `nearby_text`, which reorders by distance and could yield substrings that don't appear contiguously on the source page).
- Tier 2 narratives can reference `description` freely with a `[[wikilink]]` to the figure anchor. No verbatim required.
- The captioner metadata (`captioner: "gemini:gemma-4-31b-it@2026-05-15"`, `prompt_hash`) is sufficient Tier 2 provenance; record it in Tier 2 footers if helpful, but it is NOT a Tier 1 promotion path.

When Phase 3 lands, `wiki-pharma-extraction/SKILL.md` gets a section referencing this contract, plus a follow-up to add Rule 2b to its validator.

## Open follow-ups (after 3a + 3b ship)

- **Phase 3.1: Vector figure detection** for the EMA EPAR coverage gap (`page.get_drawings()` + render fallback). Raises EPAR yield to FDA-comparable levels.
- **Phase 3.2: Non-`(b)(4)` redactions** — white-fill `(b)(6)`, bordered redactions. Extend `is_redaction` calibration with corpus-seeded variants.
- **Phase 4: `assemble_md.py`** — splice text + OCR + figures into the final `<stem>.hybrid.md`.
- **Backfill** on the ~30 unextracted PDFs in `apalutamide/`.
- **Validator update in `wiki-pharma-extraction`** for Rule 2b ("Tier 1 may cite only `raw_caption_candidate` or `page_text_verbatim`; never `description` or `nearby_text`").
- **`<substance>/metadata.json` schema spec** — define keys (`inn`, `brand_names`, `atc`, `ich_class`, `mechanism`, `aliases`) once we have two substances to compare. Until then, the captioner reads any `metadata.json` opportunistically with safe defaults if keys are missing.
- **Honest local-vs-cloud OCR comparison** with strict no-preamble prompt — see [[project-ocr-followups]].
- **Parallel local OCR** for large scanned docs — see [[project-ocr-followups]].

## Review questions resolved during design

| Question | Decision | Reasoning |
|---|---|---|
| 3a + 3b together, or split? | Together (one phase). | Captioner needs extractor output to be useful at all. |
| Backend sharing? | Shared via `_vision_backends.py`. | Reuse Phase 2/2b HTTP helpers; add structured-output variants. |
| Default captioner backend? | Gemini cloud. | 6 GB VRAM caps local at ~4-5B; 26-31B better for complex plots. |
| Default Gemini models? | `gemma-4-31b-it,gemma-4-26b-a4b-it`. | Gemma 4 only per user direction; both available in user's `.env`. |
| Vector figure handling? | Skip for v1; Phase 3.1. | Heuristic risk; gap documented explicitly in Coverage expectations. |
| Substance default? | `metadata.json` preferred; path inference fallback; `substance_source` recorded. | Metadata gives ATC/INN context for prompt enrichment and decouples from filesystem layout. (Q8) |
| Tables-as-figures detection? | **Structured output (`{type, content}`), not prefix sniffing.** | Prefix detection breaks on preambles or formatting variations; structured output is deterministic. Both Gemini (`response_schema`) and LMStudio (JSON mode + in-prompt schema) support it. (Q4) |
| Refuse OCR-specialized models for captioning? | Yes — explicit `CAPTION_DENYLIST` set, not regex. | Regex would reject future general models with "ocr" in name. Explicit list is honest about what we actually know to be unsuitable. The Phase 2 `OCR_MODEL_PATTERN` regex stays for prompt-selection heuristics where false positives are harmless. (Q9) |
| Header-decoration filter — mandatory but with flags? | Always-on with calibratable thresholds; dropped items logged to `dropped_header_decorations[]` for audit. | Flags exist for ops calibration against new sources, not "disable in production." Audit log answers "did we drop a real figure?" without needing to re-run. (Q6) |
| Redaction detection — verified? | Defaults calibrated against apalutamide corpus in Task 5 via `KNOWN_REDACTIONS` constant + test. v1 covers `(b)(4)` gray rectangles only; non-gray and bordered redactions deferred to Phase 3.2 and explicitly listed as Non-goal. | Better to ship a calibrated narrow detector than an over-promised broad one. Non-`(b)(4)` redactions slip through as "real figures" — visible to a reviewer because the caption will describe them as uniform rectangles. (Q5) |
| Verbatim grounding contract for captions? | **`raw_caption_candidate` and `page_text_verbatim` are Tier-1-eligible; `description` and `nearby_text` are NOT.** Schema fields include `*_tier` per item; downstream validator (`wiki-pharma-extraction`) enforces "Tier 1 cannot cite `description` or `nearby_text`" as Rule 2b. | Tier 1 invariant requires verbatim source-anchored text; model-generated captions do not qualify by construction. `nearby_text` was initially marked Tier-1-eligible in v1 of this spec, but its closest-first ordering means a 15-word substring might stitch across non-adjacent blocks and not appear contiguously on the source page. Adding `page_text_verbatim` (document-ordered, captured once per page via `page.get_text()`) gives downstream a contiguous, trivially-checkable Tier 1 anchor without dropping `nearby_text` from the captioner's prompt (where closest-first is still the right ranking). (Q1, second-pass review) |
| Sidecar shape — per-figure JSONs vs one mutated file? | **One sidecar; atomic-write via tmp + os.replace.** Per-figure sidecars rejected. | Single JSON is simpler to scan, hash, and validate; atomic write covers the crash-corruption concern. Per-figure sidecars add filesystem chatter, require a separate index, and offer no offsetting win at our scale (~14 figs/PDF). (Q2 part) |
| Content-hash idempotency? | `source_pdf_sha256` + `extractor_thresholds_hash` in sidecar header; captioner refuses stale sidecars unless `--force` or `--accept-stale`. | Detects "PDF re-fetched" and "thresholds changed since last extraction" — both invalidate cached captions silently otherwise. (Q2 part) |
| Captioner versioning? | `captioner` field uses `engine:model@YYYY-MM-DD`; `prompt_hash` per figure. | Audit trail for which model+prompt produced which caption. Future prompt revisions or model swaps are identifiable from the sidecar alone. (Q2 part) |
| Prompt internal consistency (values policy)? | **Single coherent rule: discrete labeled values → transcribe literally; continuous curves → describe trends only. Always state axis labels and units.** Per-figure-type prompt variants rejected. | Per-type variants add maintenance overhead and require classifying the figure twice (once to pick prompt, once to write content). One rule with explicit "discrete vs continuous" guidance covers both modes; model decides at inference time. (Q3) |
| Nearby-text capture? | Page-wide capture ranked by distance to figure bbox, truncated to 2500 chars (was ±5% radius / 600 chars in v1 draft). | A 31B model has plenty of context for 2500 chars; tight radius lost real captions when figure floats far from its prose. (Minor) |
| Stale-sidecar UX? | `--check-stale` (read-only diagnostic), `--accept-stale` (proceed with warning), default = refuse. | Loud-by-default with explicit overrides matches the ALCOA mindset. (Missing item) |
| Rate budget? | `--rate-budget-calls N` (hard stop after N successful calls); partial JSON written via atomic replace; resume by rerunning. | Free-tier quotas are generous for apalutamide-sized backfills, but the flag exists for ops control and is cheap to add. (Missing item) |
| Coverage expectations published? | Per-source figure-yield table tied to apalutamide corpus, ±20% regression tolerance via `COVERAGE_EXPECTATIONS` constant. | Makes silent under-coverage visible. Especially important for EMA where vector loss is large. (Missing item / Q7) |
| Schema example shows "error" state? | Yes — third example entry in the schema; `description: ""`, `error: "..."`. | The original schema example omitted it; the table mentioned it. (Minor) |
| Downstream integration story documented? | Yes — new "Downstream integration" section spelling out the contracts for `assemble_md.py` and `wiki-pharma-extraction`. | Forces Q1 to be resolved at design time, not integration time. (Missing item) |
| Cost / rate model documented? | Yes — "Resumption + rate budget" section spells out per-condition behaviors and the rerun-to-resume model. | Free-tier headroom makes this comfortable for v1, but ops behaviors should be explicit. (Missing item) |

## Revisions

- **2026-05-16**: Major revision in response to design review. Added Tier 1/Tier 2 contract section with worked examples; added downstream integration section; added coverage expectations table; added resumption + rate budget section; added structured-output mechanics. Updated schema with `source_pdf_sha256`, `extractor_thresholds_hash`, `*_tier` fields, `prompt_hash`, `error` field, `dropped_header_decorations` audit log, `substance_source`. Replaced prefix-sniffing table detection with structured output (Q4). Replaced regex denylist with explicit `CAPTION_DENYLIST` set (Q9). Promoted atomic writes to documented invariant. Widened nearby-text capture (page-wide ranked by distance, 2500 chars). Reworded prompt for coherent values policy (Q3). Added `--check-stale`, `--accept-stale`, `--rate-budget-calls` flags. Added calibration-corpus test for redaction defaults. Listed non-`(b)(4)` redactions as explicit Phase 3.2 non-goal.
- **2026-05-16 (second pass)**: Tightened Tier-1 eligibility. Added `page_text_verbatim` (document-ordered, captured once per page via `page.get_text()`) as the Tier-1-eligible page-text field; demoted `nearby_text` to captioner-context only with `nearby_text_tier: null`. Updated Tier table, schema example, worked examples, downstream-integration Rule 2b text, architecture function list, and added two tests (`test_page_text_verbatim_preserves_document_order`, `test_page_text_verbatim_attached_to_every_figure_on_page`). Added explicit `*_tier` sentinel-convention legend (`1` / `2` / `null`; missing key is a schema violation). Added chicken-and-egg seeding note to the Calibration corpus paragraph so implementation does not block on hand-labelling.
