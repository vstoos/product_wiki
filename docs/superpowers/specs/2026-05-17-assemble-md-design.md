# Phase 4 — assemble_md.py design

**Goal:** stitch Phase 1 PyMuPDF text + Phase 2 OCR + Phase 3 figures+captions into a single agent- and human-readable `<stem>.hybrid.md` per PDF, with `<a id="pN"></a>` page anchors so Tier 1 wiki facts can cite `p.N` against an unambiguous location.

**Why now:** Phases 1–3 each produce sidecars that any downstream consumer must re-stitch. Without Phase 4 the wiki extractor (`wiki-pharma-extraction`) cannot cite page anchors and OCR text remains unused.

**Scope:** one PDF in, one `.hybrid.md` + one `.assembly.json` out. No batch orchestration, no parallelism, no synthesis.

## Inputs

For a PDF at `D/<stem>.pdf`, Phase 4 reads (auto-discovered in `D/` unless overridden):

| File | Required | Source | What it gives |
|---|---|---|---|
| `D/<stem>.md` | **yes** | Phase 1 | per-page PyMuPDF text, delimited by `<!-- page: N -->` markers, preceded by a YAML frontmatter block |
| `D/<stem>.extract.json` | **yes** | Phase 1 | `page_count`, `problem_pages`, engine info |
| `D/<stem>.ocr.json` | optional | Phase 2 | per-page OCR text with `status: ok|error` |
| `D/<stem>.figures.json` | optional | Phase 3a/3b | per-figure entries (page_number, figure_id, asset_path, content_type, description, raw_caption_candidate, redacted, captioner) |
| `D/<stem>.assets/figure_pN_fM.png` | optional | Phase 3a | referenced by relative path from `.hybrid.md` |

Phase 1's `.md` is parsed (not re-extracted) — the marker format `<!-- page: N -->` is a stable contract within this skill. The PDF itself is not re-opened in Phase 4 (no PyMuPDF call).

## Outputs

```
D/<stem>.hybrid.md         primary output - LLM/human-readable assembled markdown
D/<stem>.assembly.json     ALCOA metadata: which sidecars were used, page-source breakdown, hashes, timing
```

`.hybrid.md` is written next to the PDF (same dir as Phase 1 outputs), per the repo's flat layout convention. The pre-existing Phase 1 `<stem>.md` remains in place — it stays useful as the raw text dump and as Phase 4's parse input.

## `.hybrid.md` shape

### Header (one HTML comment, exactly one blank line, then content)

```markdown
<!-- doc_meta: pages=51, ocr_pages=5, figure_count=0, source_pdf=210951Orig1s000ChemR.pdf, assembled_at=2026-05-17T12:34:56Z -->

<a id="p1"></a>
## Page 1

...page-1 body...
```

The header carries only the keys downstream tools actually parse. No YAML frontmatter (that lives on Phase 1's `.md`). No H1 title.

### Per-page block

```markdown
<a id="pN"></a>
## Page N

<body text>

<figure blocks, if any, in page_index_within order>
```

Required:
- `<a id="pN"></a>` immediately before the heading
- `## Page N` (H2; never H1, never H3+)
- One blank line between the heading and the body

The body is one of:
1. **OCR-replaced** — page is in `problem_pages` AND `.ocr.json` has it with `status=ok` → use `ocr.text`; do NOT include the PyMuPDF text.
2. **OCR-failed** — page is in `problem_pages` AND `.ocr.json` has it with `status=error` → emit `<!-- ocr-failed: <error> -->` then the PyMuPDF body (which is probably garbage, but it's all we have).
3. **OCR-not-run** — page is in `problem_pages` AND `.ocr.json` is missing OR doesn't list the page → emit `<!-- problem-page: low text density, OCR not run -->` then the PyMuPDF body.
4. **PyMuPDF clean** — page is NOT in `problem_pages` → use PyMuPDF body as-is.

The Phase 1 `.md` per-page sections can contain a stale `<!-- problem-page: ... (chars) -->` comment from extract_text.py; Phase 4 strips that comment and re-emits the appropriate one based on the current OCR state.

Page bodies are emitted verbatim (no paraphrasing, no whitespace normalization beyond stripping leading/trailing blank lines). Unicode characters (`°`, `µ`, `±`, `≤`, `≥`, `–`, `—`, `→`, `☒`, `☐`) pass through untouched.

### Figure blocks

For each figure on page N, in `page_index_within` order, append after the page body (separated by one blank line):

**Figure (`content_type == "figure"` or null):**
```markdown
### Figure <figure_id> — <raw_caption_candidate or "(uncaptioned)">

![Figure <figure_id>](<stem>.assets/figure_pN_fM.png)

> *Caption*: <description>
```
- The `— <raw_caption_candidate>` part is omitted entirely if `raw_caption_candidate` is empty. Heading becomes just `### Figure <figure_id>`.
- The `> *Caption*: <description>` blockquote is omitted if `description` is null (uncaptioned).

**Table (`content_type == "table"`):**
```markdown
### Table <figure_id>

![Table <figure_id>](<stem>.assets/figure_pN_fM.png)

<description content, rendered as-is — typically <table>...</table> HTML>
```
The captioner is expected to return a well-formed table representation in `description` when `content_type=="table"`. No `> *Caption*:` blockquote wrapper.

**Redaction (`content_type == "redaction"`, `redacted == true`):**
```markdown
### Figure <figure_id>

> *[REDACTED: (b)(4)]*
```
No image link (asset_path is null).

**Error (`content_type == "error"`):**
```markdown
### Figure <figure_id>

![Figure <figure_id>](<stem>.assets/figure_pN_fM.png)

> *Caption error*: <error>
```

### Page break

The next page's `<a id="pN+1"></a>` is the only page break marker. No `---`. Two blank lines between pages.

## `.assembly.json` shape

```json
{
  "schema_version": "1.0",
  "source_file": "210951Orig1s000ChemR.pdf",
  "source_pdf_sha256": "87b2900663...",
  "assembly_date": "2026-05-17T12:34:56Z",
  "assembler_version": "assemble_md.py@2026-05-17",
  "page_count": 51,
  "page_sources": {
    "pymupdf_clean": 46,
    "ocr_ok": 5,
    "ocr_failed": 0,
    "ocr_not_run": 0
  },
  "figure_counts": {
    "total": 0,
    "captioned": 0,
    "uncaptioned": 0,
    "redacted": 0,
    "errored": 0
  },
  "inputs": {
    "md": "210951Orig1s000ChemR.md",
    "extract_json": "210951Orig1s000ChemR.extract.json",
    "ocr_json": "210951Orig1s000ChemR.ocr.json",
    "figures_json": "210951Orig1s000ChemR.figures.json"
  },
  "output": {
    "hybrid_md": "210951Orig1s000ChemR.hybrid.md",
    "size_bytes": 12345
  },
  "assembly_seconds": 0.42
}
```

`source_pdf_sha256` is read from `figures.json::source_pdf_sha256` if available; else from `<stem>.pdf.meta.json::sha256` or `<stem>.meta.json::sha256` if available (mirrors `extract_figures.compute_pdf_sha256()`); else null (we do not re-hash the PDF — that's Phase 1/3's job).

## CLI

```bash
python skills/pdf-doc-extraction/scripts/assemble_md.py \
  --pdf <substance>/<AGENCY>/<file>.pdf \
  --out <substance>/<AGENCY>/
```

Flags:
- `--pdf PATH` (required) — input PDF (only used for stem + sidecar lookup; never opened)
- `--out DIR` (required) — output dir; sidecars auto-discovered here unless overridden
- `--md PATH` — override Phase 1 .md location (default `<out>/<stem>.md`)
- `--extract-json PATH` — override (default `<out>/<stem>.extract.json`)
- `--ocr-json PATH` — override (default `<out>/<stem>.ocr.json`, skipped if missing)
- `--figures-json PATH` — override (default `<out>/<stem>.figures.json`, skipped if missing)
- `--force` — overwrite existing `.hybrid.md`
- `--quiet` — suppress stdout summary

Behavior:
- Refuses to overwrite an existing `.hybrid.md` without `--force` (mirrors `extract_figures.py`).
- Required sidecars missing → exit 2 with a clear error.
- Optional sidecars missing → continue, record the absence in `.assembly.json` and emit a `<!-- ocr-not-run -->` or omit-figures behavior accordingly.

stdout (unless `--quiet`):
```json
{
  "hybrid_md": "apalutamide/FDA/210951Orig1s000ChemR.hybrid.md",
  "pdf": "apalutamide/FDA/210951Orig1s000ChemR.pdf",
  "page_count": 51,
  "page_sources": {"pymupdf_clean": 46, "ocr_ok": 5, ...},
  "figure_counts": {"total": 0, ...},
  "assembly_seconds": 0.42
}
```

Exit codes: 0 success; 2 bad CLI / missing required sidecar; 1 unexpected failure.

## Non-goals (deferred)

- **`.hybrid.json` companion** — output-format.md mentions it as optional; defer until a downstream programmatic consumer needs it.
- **Cross-page table reconstruction** — table fragments stay per-page (matches Phase 3 contract).
- **Re-extracting text from the PDF** — Phase 4 parses Phase 1's `.md`; if Phase 1's marker format changes, both files ship together.
- **Caption freshness validation** — already enforced at Phase 3b. Phase 4 trusts the figures.json contents.
- **Per-figure vector graphic support** — covered by [[project-phase3-followups]]'s Phase 3.1, not Phase 4.
- **Batch directory walking** — single-PDF only; the agent loops.

## Test plan

Unit tests:
1. `parse_phase1_md()` — given a known markdown with frontmatter + 3 pages (one with the `problem-page` comment, one empty), returns `{1: "body1", 2: "", 3: "body3"}` and strips inline `problem-page` comments.
2. `select_page_body()` — table-driven test over the 4 cases (pymupdf_clean, ocr_ok, ocr_failed, ocr_not_run) given a fake extract/ocr state, returns expected body + page_source label.
3. `render_figure_block()` — table-driven test over the 5 content_type cases (figure-captioned, figure-uncaptioned, figure-with-raw-caption, table, redaction, error) returning expected markdown blocks.
4. `compute_page_sources_summary()` — given a mix of pages, returns the counts dict.
5. `discover_sidecars()` — required missing → raises; optional missing → returns None for that slot.
6. CLI smoke: writes `.hybrid.md` + `.assembly.json`, refuses to overwrite without `--force`.

Integration tests against fixtures:
7. `chemr_pdf` (51 pages, 5 OCR'd, 0 figures): assembly produces a `.hybrid.md` containing `<a id="p47"></a>` through `<a id="p51"></a>` with OCR'd bodies; `.assembly.json` reports `pymupdf_clean=46, ocr_ok=5`.
8. `multidisc_pdf` (figure-rich): assembly produces a `.hybrid.md` with figure blocks containing `![Figure p11_f1](...assets/figure_p11_f1.png)` for the first figure; counts match figures.json.

All tests use the existing `conftest.py` fixtures; no new fixtures needed.

## Implementation order (TDD)

1. `parse_phase1_md()` — test, implement, commit
2. `select_page_body()` + page-source labels — test, implement, commit
3. `render_figure_block()` — test (all 5 cases), implement, commit
4. `discover_sidecars()` + freshness/required-missing handling — test, implement, commit
5. `assemble()` end-to-end function — test, implement, commit
6. CLI + atomic write + stdout summary — test, implement, commit
7. Integration test on chemr_pdf and multidisc_pdf fixtures — test, run, commit
8. Update SKILL.md + README.md (Phase 4 row, invocation, defaults) — commit
9. Run full test suite, fix any regressions, commit

Estimated 9 commits, ~250-350 LOC implementation + ~200 LOC tests.

Related: [[project-phase3-followups]], [[project-free-compute-strategy]], output-format.md (existing reference).
