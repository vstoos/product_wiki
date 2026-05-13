# Figure Extraction + Captioning

When to extract a figure, when to caption it, and what the vision-model prompt should look like.

## Figure types (and what each needs)

| Figure type | Extract? | Caption? | Notes |
|---|---|---|---|
| Chemical structure (2D molecule) | Yes | **Yes** (when not captioned inline) | Vision model can name substituents/functional groups |
| PK/PD plot (time × concentration) | Yes | **Yes** | Caption: axes, what's plotted, key observation |
| Bar/box plot (group comparisons) | Yes | **Yes** | Caption: groups, metric, error bars, significance |
| Forest plot (subgroup analysis) | Yes | **Yes** | Caption: outcome, subgroups, effect direction |
| Kaplan-Meier curve | Yes | **Yes** | Caption: events, follow-up period, hazard ratio if shown |
| Schematic / flow diagram | Yes | Sometimes | If complex, caption. If trivial (e.g. study schema), inline caption usually sufficient |
| Image of dissolution apparatus | Yes | No | Mechanical photograph, inline caption sufficient |
| Histology / cell biology image | Yes | Yes | Caption: cell type, staining, magnification, finding |
| Photograph of drug substance | Yes | No | Photographic, inline caption sufficient |
| Logo / agency seal | **No** | No | Skip — decorative |
| Page header / footer image | **No** | No | Skip — boilerplate |
| Horizontal rule / separator | **No** | No | Skip — formatting |
| Watermark | **No** | No | Skip — boilerplate |
| Table-as-image (no underlying text) | Yes | No (use OCR / SLANeXt instead) | Routed to Stage 3 |

## §SkipHeuristics

How to decide whether to extract or skip a candidate figure (from Stage 1):

```python
def should_extract(candidate, page_context):
    # 1. Size check — tiny images are decorative
    if candidate.bbox_area < 5000:  # px²
        return False

    # 2. Aspect ratio — extreme aspect ratios are usually rules/separators
    ar = candidate.width / max(candidate.height, 1)
    if ar > 20 or ar < 0.05:
        return False

    # 3. Position check — page-margin images are headers/footers
    if candidate.bbox_top < 50 or candidate.bbox_bottom > page_context.height - 50:
        return False

    # 4. Repeated across many pages — likely watermark/logo
    if candidate.xref_repeat_count > 5:
        return False

    # 5. Caption proximity — figures with nearby "Figure N" markers are real
    if candidate.has_nearby_figure_caption:
        return True  # extract regardless of size

    return True  # default: extract
```

The repeated-xref check is important. PDFs often reuse the same image (logo) on every page — extracting 250 copies of the same logo wastes time and clutters `.assets/`.

## §CaptionDecision

Once a figure is extracted, decide whether to send to vision model for captioning:

```python
def should_caption(figure, inline_caption_text):
    # 1. If we have a substantive inline caption, no need for vision-model captioning
    if inline_caption_text and len(inline_caption_text) > 40:
        return False

    # 2. If figure was identified as a chart/plot by layout detector, caption regardless
    if figure.layout_class in ("chart", "plot", "graph", "molecular_structure"):
        return True

    # 3. If figure is large and central (likely informative), caption
    if figure.bbox_area > 50000 and figure.position == "centered":
        return True

    # 4. Otherwise skip — caption is just "Figure N." which adds no value
    return False
```

The user can override by setting:
- `caption_mode: all-figures` → caption every extracted figure
- `caption_mode: flagged-only` → only those flagged by `should_caption()`
- `caption_mode: none` → never caption (faster, no vision model dependency)

Default: `flagged-only`.

## Vision-model prompt template

When invoking vision model for a caption, use this prompt shape:

```
You are annotating a scientific figure from a regulatory drug review document.

Context (text immediately preceding and following the figure in the document):

<surrounding text — ~500 chars before + ~500 chars after>

The figure caption (if any was extracted) says:

<inline caption text or "(no inline caption available)">

Please write a 30-80 word description of what the figure shows. Focus on:
- WHAT is depicted (chart type, structures, biological setting)
- The key axes / variables / labels if visible
- The main finding the figure communicates (if inferable from the context and image content)

Do NOT speculate about findings not visible in the image. Do NOT reproduce the inline caption verbatim — add value beyond what's already there. Write factually and concisely.

Return ONLY the description text, no preamble or markdown formatting.
```

The vision-model output gets appended after the figure embed:

```markdown
### Figure N — <inline caption if any>

![Figure N — <inline caption>](<stem>.assets/figure_pN_fM.png)

> *Caption*: <vision model response>
```

## Extraction implementation

### Embedded raster (most figures)

```python
import fitz
import io
from PIL import Image

page = doc[N - 1]
for xref, *_, name in page.get_images(full=True):
    img_info = doc.extract_image(xref)
    img_bytes = img_info["image"]
    img_ext = img_info["ext"]  # "png", "jpeg", etc.

    img = Image.open(io.BytesIO(img_bytes))
    img.save(stem_assets_dir / f"figure_p{N}_f{idx}.png")
```

### Vector region (chart/diagram, no raster)

```python
# Layout detector identifies a "figure" bbox on the page
# Rasterize the bbox region at 2x scale for quality
bbox = fitz.Rect(*figure_bbox)
zoom = 2.0
matrix = fitz.Matrix(zoom, zoom)
pixmap = page.get_pixmap(matrix=matrix, clip=bbox, alpha=False)
pixmap.save(stem_assets_dir / f"figure_p{N}_f{idx}.png")
```

### Inline caption discovery

```python
# Walk reading-order blocks near the figure's position
fig_y_center = (fig_bbox.y0 + fig_bbox.y1) / 2
for block in page_blocks:
    block_y_center = (block.bbox.y0 + block.bbox.y1) / 2
    # Look ±300 px in y-direction
    if abs(block_y_center - fig_y_center) < 300:
        text = block.text.strip()
        # Match "Figure N", "Fig. N", "Figure N.X" patterns
        match = re.match(r"^(Figure|Fig\.?)\s+(\d+(\.\d+)?)\b", text, re.IGNORECASE)
        if match:
            # Capture the rest of the caption text
            return text
return None
```

## §AssetNaming

Canonical asset filename pattern: `figure_p<page>_f<index>.png`

- `<page>` = 1-indexed page number where the figure appears
- `<index>` = 0-indexed figure number within the page (top to bottom reading order)

Examples:
- `figure_p2_f01.png` — first figure on page 2
- `figure_p23_f01.png` — first figure on page 23
- `figure_p23_f02.png` — second figure on page 23 (e.g. two side-by-side panels)

This pattern is referenced by `wiki-pharma-extraction` skill's source-card writer and by the downstream image-embed checker in the validator (Rule 5).

For tables-as-images (fallback when SLANeXt fails), use `table_p<page>_t<index>.png` with same logic.

## Cross-stage interaction

Stage 4 reads from Stage 1's `figure_candidates` list. It writes:
- PNG to `.assets/`
- markdown embed (and optional caption blockquote) to be injected by Stage 5 normalization

Stage 5 / normalization is responsible for:
- Placing the figure markdown at the figure's reading-order position
- Ensuring the inline caption (if any) appears in the heading line: `### Figure N — <caption>`
- Appending the vision-model caption as `> *Caption*: ...` after the image embed

No image data ever ends up in `.hybrid.md`. Only paths.

## Quality vs cost trade-offs

If user is cost-conscious:
- Set `caption_mode: none` — skip vision model entirely
- Use `caption_mode: flagged-only` (default) — only chart/plot/structure figures get captioned
- If using paid vision model (Gemini paid / OpenAI GPT-4V), `flagged-only` keeps costs proportional to extraction signal

A typical 250-page FDA review has ~10 captionable figures → 10 vision-model calls → ~$0 on free Gemma multi-provider, or ~$0.10 on paid GPT-4V.

For large batch runs (50+ documents), the captioning step CAN become expensive. Recommend `flagged-only` as the default, with a knob to disable entirely.
