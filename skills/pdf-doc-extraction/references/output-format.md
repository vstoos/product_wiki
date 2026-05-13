# Output Format

The `.hybrid.md` markdown conventions, asset directory layout, sidecar shapes.

## File layout per input PDF

```
<stem>.pdf                       # Input (unchanged)
<stem>.hybrid.md                 # PRIMARY OUTPUT — structured markdown with anchors, tables, figures
<stem>.hybrid.json               # Optional — JSON twin for programmatic consumers
<stem>.assets/                   # Figure rasters, optional table images
  ├── figure_p1_f01.png
  ├── figure_p2_f01.png
  ├── figure_p23_f01.png
  ├── figure_p23_f02.png
  ├── table_p5_t01.png           # only when SLANeXt failed and we kept the raster
  └── ir.json                    # optional structural IR (block types, bboxes, reading order)
<stem>.meta.json                 # extraction metadata (engines used, time, cost)
<stem>.native.txt                # raw PyMuPDF text dump (for debugging diff)
<stem>.pymupdf.md                # Stage 1 preliminary markdown
<stem>.pymupdf.json              # Stage 1 structured dump
<stem>.ocr/<engine>/             # Per-engine OCR cache (per-page JSON/MD)
<stem>.tables/                   # Per-table HTML
```

The `.hybrid.md` + `.assets/` directory are the SHIPPED outputs. Everything else is intermediate/cache.

## `.hybrid.md` structure

### Top of file

```markdown
<!-- doc_meta: pages=259, scanned_pages=38, engines=pymupdf+gemma_multi+slanext, extracted_at=2026-05-13T11:42:18Z -->

```

ONE HTML comment with key=value pairs. Downstream tools parse this for routing decisions. No additional title/headline — the content starts immediately at Page 1.

### Per-page block

```markdown
<a id="p1"></a>
## Page 1

CENTER FOR DRUG EVALUATION AND RESEARCH

APPLICATION NUMBER: 210951Orig1s000

MULTIDISCIPLINE REVIEW

```

REQUIRED:
- `<a id="pN"></a>` anchor immediately before the page heading
- `## Page N` (H2 heading; never H1, never H3+)
- Body content as paragraphs

The anchor + heading combination lets downstream tools navigate to a specific page via `<stem>.hybrid.md#pN`.

### Body content within a page

Paragraphs separated by blank lines. Preserve Unicode entities literally: `°`, `±`, `≤`, `≥`, `–`, `—`, `→`, `µ`, `★`, `☒`, `☐`.

```markdown
Apalutamide is practically insoluble in water (0.012 mg/mL at pH 7.4 at 37 °C).
The compound exhibits a pKa of 13.6 and a calculated log P of 4.3.
```

### Inline tables

Use HTML `<table>` syntax (NOT pipe-tables) for any table with nested headers, rowspans/colspans, or more than 4 columns.

```markdown
### Table 1 — Drug substance specifications

<table>
  <thead>
    <tr><th>Parameter</th><th>Method</th><th>Specification</th></tr>
  </thead>
  <tbody>
    <tr><td>Appearance</td><td>Visual</td><td>White to off-white powder</td></tr>
    <tr><td>Identification</td><td>IR</td><td>Conforms to reference</td></tr>
    <tr><td>Assay</td><td>HPLC</td><td>98.0–102.0%</td></tr>
  </tbody>
</table>
```

For simple 2-3 column tables, pipe-tables are acceptable:

```markdown
| Parameter | Value |
|---|---|
| Cmax | 6.0 μg/mL |
| AUC | 100 μg·h/mL |
```

But default to HTML — downstream parsers handle HTML reliably, while pipe-tables are fragile with embedded commas/pipes.

### Figures

```markdown
### Figure 1 — Apalutamide molecular structure

![Figure 1 — Apalutamide molecular structure](apalutamide_review.assets/figure_p2_f01.png)

> *Caption*: 2D chemical structure showing the diaryl-thiohydantoin core, bromine substituent, and the cyano-pyridinyl moiety characteristic of apalutamide. Vision-model annotation.
```

REQUIRED structure:
1. `### Figure N — <inline caption>` heading (H3). If no inline caption found, use `### Figure N`.
2. Markdown image with alt-text matching the heading
3. Optional `> *Caption*: ...` blockquote for vision-model annotation (omit if `caption_mode=none` or `flagged-only` didn't flag this figure)

### Lists, bullets, callouts

Preserve from the source. Use standard markdown:

```markdown
- Indication: Non-metastatic castration-resistant prostate cancer (NM-CRPC)
- Dose: 240 mg orally once daily
- Route: Oral, with or without food

### Black-box warnings
1. Fall and fracture risk
2. Seizure risk
```

### Page breaks

The next page's `<a id="pN+1"></a>` + `## Page N+1` heading is the page break. No explicit `---` or page-break marker between pages. Empty pages can still emit their heading + anchor (downstream tools tolerate empty pages).

### EMA PSG checkboxes — PRESERVE LITERALLY

```markdown
| Condition | Selected |
|---|---|
| Fasting | ☒ |
| Fed | ☐ |
```

`☒` (U+2612, BALLOT BOX WITH X) and `☐` (U+2610, BALLOT BOX). Never convert to "yes/no" or `true/false`. The downstream wiki extractor expects the literal glyphs.

## `.hybrid.json` shape (optional companion)

```json
{
  "meta": {
    "pages": 259,
    "scanned_pages": 38,
    "engines": ["pymupdf", "gemma_multi", "slanext"],
    "extracted_at": "2026-05-13T11:42:18Z",
    "extraction_tool": "pdf-doc-extraction skill v1"
  },
  "pages": [
    {
      "page": 1,
      "anchor": "p1",
      "text_blocks": [
        {"kind": "heading", "level": 2, "text": "Page 1"},
        {"kind": "paragraph", "text": "CENTER FOR DRUG EVALUATION AND RESEARCH"},
        ...
      ],
      "tables": [],
      "figures": []
    },
    {
      "page": 2,
      "anchor": "p2",
      "text_blocks": [...],
      "tables": [],
      "figures": [
        {
          "kind": "figure",
          "index": 0,
          "asset_path": "<stem>.assets/figure_p2_f01.png",
          "inline_caption": "Apalutamide molecular structure",
          "vision_caption": "2D chemical structure showing the diaryl-thiohydantoin core..."
        }
      ]
    }
  ]
}
```

Optional — generate when user wants programmatic access. The `.hybrid.md` is the canonical text representation.

## `.meta.json` extraction metadata

```json
{
  "input_pdf": "210951Orig1s000MultidisciplineR.pdf",
  "input_size_bytes": 10780000,
  "input_sha256": "a1b2c3...",

  "pages_processed": 259,
  "scanned_pages": 38,
  "clean_pages": 221,
  "figures_extracted": 14,
  "tables_extracted": 26,

  "engines_used": ["pymupdf", "gemma_multi", "slanext"],
  "extraction_time_seconds": 514,
  "cost_estimate_usd": 0.00,

  "extracted_at": "2026-05-13T11:42:18Z",
  "extraction_tool": "pdf-doc-extraction skill v1",
  "stages_failed": [],

  "caption_mode": "flagged-only",
  "captions_generated": 5,
  "captions_skipped": 9
}
```

## `.assets/ir.json` (optional structural IR)

When the user wants the structural IR (e.g. for downstream layout-aware tooling):

```json
{
  "doc_id": "210951Orig1s000MultidisciplineR",
  "pages": [
    {
      "page": 1,
      "size_px": [595, 842],
      "blocks": [
        {"type": "title", "bbox": [50, 80, 545, 120], "text": "MULTIDISCIPLINE REVIEW"},
        {"type": "paragraph", "bbox": [50, 140, 545, 220], "text": "..."},
        ...
      ]
    },
    ...
  ]
}
```

Block types: `title | heading_1 | heading_2 | paragraph | table | figure | list | caption | footer`.

Bboxes are in PDF coordinate space (origin at top-left, points; 1pt = 1/72 inch).

## Filename safety

The skill uses the original PDF stem unchanged for all output filenames:

```
<stem>.pdf              → input
<stem>.hybrid.md        → primary output
<stem>.assets/          → directory of figures
<stem>.meta.json        → metadata
```

The stem must be a valid filename across Linux/macOS/WSL/Windows. If the input PDF's stem contains characters problematic on Windows (`:`, `?`, `|`, `*`, `"`, `<`, `>`), sanitize before opening:

```python
def safe_stem(raw: str) -> str:
    return "".join(c if c.isalnum() or c in "-_.()" else "_" for c in raw).strip("_.").strip()
```

But typically the regulatory-doc-fetching skill already saved files with safe names; just preserve them.
