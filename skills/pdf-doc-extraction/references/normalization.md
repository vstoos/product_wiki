# Normalization

Post-Stage-4 assembly: how to compose Stages 1-4 outputs into the final `.hybrid.md`.

## Goal

After Stage 1 (PyMuPDF), Stage 2 (OCR), Stage 3 (tables), Stage 4 (figures + captions) have all run, normalization stitches their outputs into a single canonical `.hybrid.md`. This must be:

- **Reproducible** — same input + same engine choices → byte-identical output
- **Reading-order correct** — blocks appear in the natural left-to-right top-to-bottom flow
- **Idempotent** — running normalization twice on the same intermediate state produces the same output

## Per-page assembly

For each page (1-indexed):

```
1. Emit anchor + heading
   <a id="pN"></a>
   ## Page N
   <blank line>

2. Walk blocks in reading order (sorted by bbox y0, then x0 for same-row blocks).
   For each block:

   a. TEXT block:
      - If clean text (from Stage 1): emit as paragraph
      - If OCR text (from Stage 2): emit as paragraph (no marker — reader shouldn't tell)
      - Preserve blank lines between paragraphs

   b. TABLE candidate:
      - Look up the HTML rendering from Stage 3 (`<stem>.tables/page<N>_table<M>.html`)
      - If Azure DI was used → table is already in Stage 2 output, no separate lookup
      - Emit as `### Table M — <caption if any>` heading + HTML block
      - If SLANeXt failed: emit as a raster image fallback (`![Table M](...table_pN_tM.png)`)

   c. FIGURE candidate:
      - Look up the figure record from Stage 4 (asset_path, inline_caption, vision_caption)
      - Emit:
        ### Figure M — <inline_caption or empty>
        ![Figure M — <caption>](path/to/asset.png)
        <if vision_caption present>
        > *Caption*: <vision_caption>
        </if>
      - Add blank line after

3. End the page with blank lines (2x newlines, so next page heading is well-separated).
```

## Doc-meta header

At the very top of `.hybrid.md`, emit the meta comment:

```html
<!-- doc_meta: pages=259, scanned_pages=38, engines=pymupdf+gemma_multi+slanext, extracted_at=2026-05-13T11:42:18Z -->
```

Key=value pairs, comma-separated, in a single HTML comment. Parsers split on `, ` and `=` to extract:
- `pages` — total page count (int)
- `scanned_pages` — number of pages that went through OCR
- `engines` — `+`-separated list of engine identifiers in order used
- `extracted_at` — ISO 8601 timestamp

Add new keys as needed; downstream tools tolerate unknown keys.

## Reading-order edge cases

### Multi-column pages

For 2-column or 3-column pages, PyMuPDF's reading-order detection is usually correct (top of left column → bottom of left column → top of right column → etc.). If you observe garbled order, force column-aware sorting:

```python
def sort_blocks_by_column(blocks, n_cols=2):
    page_width = page.rect.width
    col_width = page_width / n_cols
    return sorted(blocks, key=lambda b: (
        int(b.bbox.x0 / col_width),  # column index
        b.bbox.y0,                    # then top-to-bottom within column
        b.bbox.x0                     # then left-to-right within row
    ))
```

### Footnotes / side notes

Footnotes typically render at the page bottom. Two options:
- **Inline:** keep them at the position the reading-order detector found them (bottom of page, after main body)
- **Numbered + footnoted:** more complex; rarely needed for regulatory docs

Default: inline at bottom. Downstream readers handle this fine.

### Spanning tables (multi-page)

If a table starts on page N and continues on page N+1:
- Emit two separate `<table>` blocks, one on each page
- The downstream wiki extractor handles cross-page table reconstruction (or chooses to ignore it; the per-page split is at least readable)

PaddleOCR-VL 1.5 supports automatic cross-page merge if available; if so, the merged table emits on the page where it started, and page N+1 has no table fragment.

## Encoding / character handling

UTF-8 throughout. Preserve:

| Symbol | Unicode | Context |
|---|---|---|
| ° | U+00B0 | temperature, angles |
| µ | U+00B5 | micrograms, milliseconds |
| ± | U+00B1 | confidence intervals, tolerances |
| ≤ ≥ | U+2264, U+2265 | comparisons |
| × | U+00D7 | multiplication, dimensions (e.g. 10 × 10⁻⁶) |
| – | U+2013 | en-dash (between ranges, e.g. "30–60 min") |
| — | U+2014 | em-dash (parenthetical) |
| → | U+2192 | arrows (e.g. "absorbed → metabolized") |
| ☒ ☐ | U+2612, U+2610 | EMA PSG checkboxes |
| α β γ δ | U+03B1+ | Greek letters in receptor names |

Normalise non-breaking spaces (U+00A0) to regular spaces. Normalise zero-width spaces (U+200B) to empty string. Otherwise preserve.

## Whitespace handling

- Collapse multiple consecutive spaces within a paragraph to single space
- Preserve newlines that separate paragraphs (blank lines)
- Strip trailing whitespace on each line
- Trim leading/trailing whitespace on each block before emitting

## Idempotency

Running normalization twice should produce byte-identical output. To ensure:

1. Sort dict keys when serializing JSON sidecars
2. Use deterministic block ordering (the sort by bbox.y0 then bbox.x0 is deterministic)
3. Don't include timestamps in markdown body (only in `meta` comment at top, and that's a single ISO-stamp that's stable as long as the file is unchanged)

## Sanity checks (run after normalization)

Before declaring the doc "done":

1. **Page count matches:** `.hybrid.md` contains exactly N `<a id="p..."></a>` anchors where N = `<stem>.meta.json["pages_processed"]`
2. **Figure embeds resolve:** every `![...](<stem>.assets/figure_p*_f*.png)` reference has a corresponding file on disk
3. **Table HTML is well-formed:** every `<table>` is closed by `</table>`, no nested tables
4. **No raw control characters:** no `\x00` through `\x08`, `\x0B`, `\x0C`, `\x0E` through `\x1F`
5. **Reasonable text density:** if more than 50% of pages have <20 chars of body text, something went wrong (likely a scanned PDF that didn't get OCR'd)

If any check fails, mark the doc as `extraction_quality: degraded` in `.meta.json` and continue. Don't silently fail — surface to the user in the summary report.
