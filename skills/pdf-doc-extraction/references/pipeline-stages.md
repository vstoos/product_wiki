# HybridPipeline Stages

Detail for the 4-stage extraction pipeline. Each input PDF flows through Stages 1-4 sequentially; each stage may cache and skip its own work.

## Stage 1 — PyMuPDF text + structure pass

**Implementation:** `pdf_extraction/pdf_extractor_pymupdf.py`

**What it does:**
1. Open the PDF with PyMuPDF (`fitz.open(path)`).
2. For each page (1-indexed):
   - Extract text with `page.get_text("dict")` — returns blocks with text, font, bbox.
   - Capture reading order (sorted by block position).
   - List embedded raster images via `page.get_images()` and `page.get_image_info(xref)`.
   - Detect "problem indicators":
     - Total text length < 100 chars on a page that's clearly not a divider page (size > 50 KB equivalent)
     - Block-text-extraction returns "(cid:NNN)" patterns (font encoding broken)
     - Image-cover ratio > 0.7 (page is mostly image)
   - Detect table candidates: regions with grid-like block layout (multiple equally-sized columns + multiple rows).
3. Emit a per-page summary:

```python
PageSummary(
    page=N,
    text=str,
    blocks=[Block(bbox, text, font, ...)],
    images=[ImageInfo(xref, bbox, width, height)],
    is_problem=bool,
    table_candidates=[TableCandidate(bbox, n_rows_est, n_cols_est)],
    figure_candidates=[FigureCandidate(kind=raster|vector, bbox, xref)]
)
```

**Output:**
- `<stem>.native.txt` — concatenation of per-page text (for diff against final output)
- `<stem>.pymupdf.json` — full structured dump
- `<stem>.pymupdf.md` — preliminary markdown (used by Stage 2 to know what's already covered)

**Decisions for next stages:**
- Problem pages → Stage 2 OCR
- Table candidates → Stage 3 (after Stage 2 fills in any OCR'd text on those pages)
- Figure candidates → Stage 4

## Stage 2 — OCR pass for problem pages

**Implementation:** one of `pdf_extraction/pdf_ocr_{paddlevl,gemma,surya,azuredi,remote}.py` per engine choice.

**What it does:**
1. For each problem page from Stage 1, render the page as a PNG (PyMuPDF `page.get_pixmap(dpi=200)`).
2. Send the PNG to the chosen OCR engine.
3. Receive structured text back. Most engines return text-by-region (so reading order is preserved).
4. Integrate the OCR text with Stage 1's clean-text pages — for partial-OCR pages (some clean text + some scanned regions), use bbox-based merging.

**Engine choice:** see `engine-selection.md`. Default = Gemma multi-provider.

**Output augments Stage 1's per-page text:** problem-page entries now have OCR'd text. Final output of Stage 2 is `<stem>.ocr/` directory with per-page OCR JSON or markdown.

**Special: Azure DI** — its `prebuilt-layout` model does BOTH OCR and table structure in one call, returning markdown with HTML tables inline. If using Azure DI, you can skip Stage 3 for those pages (DI handles tables).

## Stage 3 — Table extraction

**Implementation:** `pdf_extraction/pdf_table_slanext.py` (SLANeXt model)

**What it does:**
1. For each table candidate from Stage 1 (or detected during OCR in Stage 2):
   - Render the table region as a PNG (`page.get_pixmap(clip=bbox, dpi=200)`).
   - Feed to SLANeXt: a table-structure-recognition transformer that returns cell-grid HTML.
   - Output is `<table><tr><td>...</td></tr>...</table>` markup, with proper colspan/rowspan handling.
2. Position the HTML table in the reading-order stream at the table's location.

**Cross-page tables:** SLANeXt operates per-region; it doesn't merge across pages. Emit each fragment in its own page heading. Cross-page table reconstruction is a downstream concern (PaddleOCR-VL 1.5 supports it natively; SLANeXt does not).

**Skip Stage 3 if:** Azure DI was used in Stage 2 (DI tables already inline).

**Output:** updated `<stem>.tables/` directory with per-table HTML, plus updated `<stem>.hybrid.md` (Stage 5 / normalization stitches it all together).

## Stage 4 — Figure extraction + captioning

**Implementation:** see `figure-extraction.md` for the full protocol. Brief here:

**What it does:**
1. For each figure candidate from Stage 1:
   - **Raster:** save the embedded image via `page.get_image_info(xref) → render` or PyMuPDF's image-writer.
   - **Vector:** rasterize the bbox region via `page.get_pixmap(clip=bbox)`.
2. Find the inline caption: walk ±200 chars of the figure's reading-order position, look for "Figure N", "Fig. N", "Figure N.X" patterns.
3. **Caption decision:**
   - If inline caption found AND text is descriptive (>20 chars) → use it as-is. Skip vision-model annotation.
   - If inline caption is short / missing AND figure appears to be a chart/plot/diagram (not a logo) → invoke vision model for annotation.
   - If figure is decorative (logo, header rule, separator) → skip entirely (don't extract).
4. Save the PNG to `<stem>.assets/figure_p<page>_f<index>.png`.
5. Emit markdown:

```markdown
### Figure N — <inline caption if available>

![Figure N — <caption>](<stem>.assets/figure_pN_fM.png)

> *Caption*: <vision-model annotation, if generated>
```

## Stage 5 — Normalization (assembly)

**Implementation:** `pdf_extraction/normalization/` package — composes Stage 1-4 outputs into final `.hybrid.md`.

**What it does:**
1. Walk pages in order.
2. For each page:
   a. Emit `<a id="pN"></a>` anchor immediately before the page heading.
   b. Emit `## Page N` (with H2).
   c. Walk blocks in reading order. Substitute:
      - Text blocks → plain paragraph text (preserving Unicode entities `°`, `±`, `≤`, etc.)
      - Table candidates → inline `<table>...</table>` HTML (from Stage 3 or 2)
      - Figure candidates → markdown image syntax + optional caption blockquote (from Stage 4)
   d. End the page (no explicit divider; the next page's `## Page N+1` heading provides the break).
3. Emit final metadata at the top: `<!-- doc_meta: pages=N, scanned_pages=O, engines=... -->`
4. Write to `<stem>.hybrid.md`.
5. Write companion `<stem>.hybrid.json` if the user wants programmatic access:
   - Same content, but structured per-page with sections, table HTMLs, figure refs as JSON.

## Caching across runs

Each stage writes intermediate artifacts:

```
<stem>.pymupdf.md / .json     ← Stage 1
<stem>.ocr/                    ← Stage 2 (per-engine subdirs: paddlevl/, gemma/, surya/, azuredi/)
<stem>.tables/                 ← Stage 3
<stem>.assets/                 ← Stage 4 (figures + optional table images)
<stem>.hybrid.md / .json       ← Stage 5
<stem>.meta.json               ← extraction metadata (engines used, page counts, cost)
```

**Cache hit rule:** if `<stem>.hybrid.md` exists with non-zero size AND its mtime > all input PDF's mtime AND user didn't force-refresh → skip the entire pipeline for this PDF.

For partial reprocessing (e.g. "redo OCR with a different engine"): user must delete the relevant intermediate subdir (`<stem>.ocr/`) before re-running, OR pass an explicit "redo from Stage 2" flag.

## Failure handling

Each stage can fail without aborting the whole pipeline:

- Stage 1 PyMuPDF fails → abort (no fallback for text extraction); report doc as failed
- Stage 2 OCR engine fails → try next engine in priority list; if all fail, mark scanned pages as `<!-- OCR failed -->` and continue
- Stage 3 SLANeXt fails → leave the table region as a `<!-- table at p3 -->` placeholder + raster image
- Stage 4 figure extraction fails per-figure → log + skip that figure

Per-doc errors get recorded in `<stem>.meta.json`:

```json
{
  "pages_processed": 259,
  "scanned_pages": 38,
  "engines_used": ["pymupdf", "gemma_multi", "slanext"],
  "stages_failed": [],
  "figures_extracted": 14,
  "tables_extracted": 26,
  "extraction_time_seconds": 514,
  "cost_estimate_usd": 0.00,
  "extracted_at": "2026-05-13T11:42:18Z",
  "extraction_tool": "pdf-doc-extraction skill v1"
}
```

## Note on cost

- Gemma multi-provider (free tier): $0 with normal usage
- PaddleOCR-VL local: $0 (GPU compute, your own hardware)
- Surya local: $0 (CPU compute)
- Azure DI: $10 / 1000 pages — track per-doc cost in `meta.json`
- Remote Docker (LightOnOCR, GLM-OCR, Surya): $0 ($GPU lease cost on host)
- Gemma vision captioning: $0 on free tier; ~$0.001 / image on paid

A typical FDA review (250 pages, 30 scanned, 10 figures, 20 tables) costs $0 on the free-default config or ~$2.50 if Azure DI is used.
