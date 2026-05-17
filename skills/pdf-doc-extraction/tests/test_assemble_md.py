"""Tests for assemble_md.py - Phase 4 hybrid markdown assembly."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

# Load the module from an explicit path to avoid sys.path collisions.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_path = SCRIPTS / "assemble_md.py"
_spec = importlib.util.spec_from_file_location("assemble_md", _path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(f"Cannot find {_path}")
assemble_md = importlib.util.module_from_spec(_spec)
sys.modules["assemble_md"] = assemble_md
_spec.loader.exec_module(assemble_md)


# ---------------------------------------------------------------------------
# parse_phase1_md
# ---------------------------------------------------------------------------

def _make_phase1_md(pages: dict[int, str], with_problem_pages: set[int] | None = None) -> str:
    """Build a fake Phase 1 .md given {page_no: body, ...}."""
    problem = with_problem_pages or set()
    lines = [
        "---",
        'source_file: "x.pdf"',
        f"page_count: {len(pages)}",
        'engine: "pymupdf"',
        'engine_version: "1.26.3"',
        f"problem_page_count: {len(problem)}",
        "extraction_seconds: 0.1",
        "---",
    ]
    for pn in sorted(pages):
        lines.append(f"<!-- page: {pn} -->")
        if pn in problem:
            lines.append(f"<!-- problem-page: low text density ({len(pages[pn])} chars), needs OCR -->")
        lines.append("")
        lines.append(pages[pn])
        lines.append("")
    return "\n".join(lines)


def test_parse_phase1_md_returns_per_page_bodies():
    md = _make_phase1_md({1: "page one body", 2: "page two body", 3: "page three"})
    parsed = assemble_md.parse_phase1_md(md)
    assert parsed == {1: "page one body", 2: "page two body", 3: "page three"}


def test_parse_phase1_md_strips_problem_page_comment():
    md = _make_phase1_md({1: "real text", 2: "scanned garbage"}, with_problem_pages={2})
    parsed = assemble_md.parse_phase1_md(md)
    # The inline problem-page comment is dropped from the body
    assert "<!-- problem-page" not in parsed[2]
    assert parsed[2] == "scanned garbage"


def test_parse_phase1_md_handles_empty_page():
    md = _make_phase1_md({1: "body", 2: "", 3: "body3"})
    parsed = assemble_md.parse_phase1_md(md)
    assert parsed[2] == ""


def test_parse_phase1_md_without_frontmatter():
    # Edge case: file without YAML frontmatter still parses
    md = "<!-- page: 1 -->\n\nhello\n\n<!-- page: 2 -->\n\nworld\n"
    parsed = assemble_md.parse_phase1_md(md)
    assert parsed == {1: "hello", 2: "world"}


def test_parse_phase1_md_strips_trailing_whitespace():
    md = "<!-- page: 1 -->\n\n  body with trailing spaces   \n\n<!-- page: 2 -->\n\n\n\n"
    parsed = assemble_md.parse_phase1_md(md)
    assert parsed[1] == "body with trailing spaces"
    assert parsed[2] == ""


# ---------------------------------------------------------------------------
# select_page_body
# ---------------------------------------------------------------------------

def test_select_page_body_pymupdf_clean():
    body, source = assemble_md.select_page_body(
        page_number=5,
        pymupdf_text="clean text",
        is_problem=False,
        ocr_entry=None,
    )
    assert body == "clean text"
    assert source == "pymupdf_clean"


def test_select_page_body_ocr_ok_replaces_pymupdf():
    body, source = assemble_md.select_page_body(
        page_number=47,
        pymupdf_text="garbage",
        is_problem=True,
        ocr_entry={"page_number": 47, "text": "OCR result text", "status": "ok"},
    )
    assert body == "OCR result text"
    assert source == "ocr_ok"


def test_select_page_body_ocr_failed_marks_then_falls_back():
    body, source = assemble_md.select_page_body(
        page_number=47,
        pymupdf_text="garbage",
        is_problem=True,
        ocr_entry={
            "page_number": 47,
            "text": "",
            "status": "error",
            "error": "ConnectionError: timeout",
        },
    )
    assert "ConnectionError: timeout" in body
    assert "ocr-failed" in body
    assert "garbage" in body
    assert source == "ocr_failed"


def test_select_page_body_ocr_not_run_marks_then_uses_pymupdf():
    body, source = assemble_md.select_page_body(
        page_number=47,
        pymupdf_text="garbage",
        is_problem=True,
        ocr_entry=None,
    )
    assert "problem-page" in body
    assert "OCR not run" in body
    assert "garbage" in body
    assert source == "ocr_not_run"


# ---------------------------------------------------------------------------
# render_figure_block
# ---------------------------------------------------------------------------

def _figure_entry(**overrides) -> dict:
    base = {
        "figure_id": "p11_f1",
        "page_number": 11,
        "page_index_within": 1,
        "asset_path": "stem.assets/figure_p11_f1.png",
        "raw_caption_candidate": "",
        "description": None,
        "content_type": None,
        "captioner": None,
        "redacted": False,
        "error": None,
    }
    base.update(overrides)
    return base


def test_render_figure_uncaptioned_no_raw_caption():
    block = assemble_md.render_figure_block(_figure_entry())
    assert "### Figure p11_f1" in block
    assert "—" not in block.split("\n")[0]  # no inline caption suffix
    assert "![Figure p11_f1](stem.assets/figure_p11_f1.png)" in block
    assert "*Caption*" not in block


def test_render_figure_with_raw_caption_only():
    entry = _figure_entry(raw_caption_candidate="Figure 3. Dissolution profile of apalutamide")
    block = assemble_md.render_figure_block(entry)
    assert "### Figure p11_f1 — Figure 3. Dissolution profile of apalutamide" in block
    assert "![Figure p11_f1](stem.assets/figure_p11_f1.png)" in block
    assert "*Caption*" not in block


def test_render_figure_captioned():
    entry = _figure_entry(
        raw_caption_candidate="Figure 3. PK profile",
        description="Line plot showing apalutamide plasma concentration over time.",
        content_type="figure",
        captioner="gemini:gemma-4-26b-a4b-it@2026-05-17",
    )
    block = assemble_md.render_figure_block(entry)
    assert "### Figure p11_f1 — Figure 3. PK profile" in block
    assert "![Figure p11_f1](stem.assets/figure_p11_f1.png)" in block
    assert "> *Caption*: Line plot showing apalutamide plasma concentration over time." in block


def test_render_figure_table_content_type():
    entry = _figure_entry(
        description="<table><tr><td>A</td><td>B</td></tr></table>",
        content_type="table",
    )
    block = assemble_md.render_figure_block(entry)
    assert "### Table p11_f1" in block
    assert "![Table p11_f1](stem.assets/figure_p11_f1.png)" in block
    assert "<table><tr><td>A</td><td>B</td></tr></table>" in block
    assert "*Caption*" not in block


def test_render_figure_redaction():
    entry = _figure_entry(
        asset_path=None,
        description="[REDACTED: (b)(4)]",
        content_type="redaction",
        captioner="skipped:redacted",
        redacted=True,
    )
    block = assemble_md.render_figure_block(entry)
    assert "### Figure p11_f1" in block
    assert "[REDACTED: (b)(4)]" in block
    assert "![" not in block  # no image link for redactions


def test_render_figure_error():
    entry = _figure_entry(
        description=None,
        content_type="error",
        error="TimeoutError: caption call timed out",
    )
    block = assemble_md.render_figure_block(entry)
    assert "### Figure p11_f1" in block
    assert "![Figure p11_f1](stem.assets/figure_p11_f1.png)" in block
    assert "*Caption error*" in block
    assert "TimeoutError" in block


# ---------------------------------------------------------------------------
# discover_sidecars
# ---------------------------------------------------------------------------

def test_discover_sidecars_all_present(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text("---\n---\n", encoding="utf-8")
    (tmp_path / "doc.extract.json").write_text("{}", encoding="utf-8")
    (tmp_path / "doc.ocr.json").write_text("{}", encoding="utf-8")
    (tmp_path / "doc.figures.json").write_text("{}", encoding="utf-8")

    s = assemble_md.discover_sidecars(pdf=pdf, out_dir=tmp_path)
    assert s["md"] == tmp_path / "doc.md"
    assert s["extract_json"] == tmp_path / "doc.extract.json"
    assert s["ocr_json"] == tmp_path / "doc.ocr.json"
    assert s["figures_json"] == tmp_path / "doc.figures.json"


def test_discover_sidecars_optional_missing_ok(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text("---\n---\n", encoding="utf-8")
    (tmp_path / "doc.extract.json").write_text("{}", encoding="utf-8")

    s = assemble_md.discover_sidecars(pdf=pdf, out_dir=tmp_path)
    assert s["ocr_json"] is None
    assert s["figures_json"] is None


def test_discover_sidecars_required_missing_raises(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    # no .md, no .extract.json
    with pytest.raises(FileNotFoundError):
        assemble_md.discover_sidecars(pdf=pdf, out_dir=tmp_path)


def test_discover_sidecars_explicit_overrides(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    md = tmp_path / "elsewhere.md"
    md.write_text("---\n---\n", encoding="utf-8")
    ej = tmp_path / "elsewhere.extract.json"
    ej.write_text("{}", encoding="utf-8")

    s = assemble_md.discover_sidecars(
        pdf=pdf,
        out_dir=tmp_path,
        md_path=md,
        extract_json_path=ej,
    )
    assert s["md"] == md
    assert s["extract_json"] == ej


# ---------------------------------------------------------------------------
# assemble (end-to-end without disk I/O)
# ---------------------------------------------------------------------------

def test_assemble_includes_doc_meta_comment():
    extract_meta = {"page_count": 2, "problem_pages": []}
    phase1_md = _make_phase1_md({1: "page one", 2: "page two"})
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256="abc123",
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=None,
        figures_data=None,
    )
    assert result.hybrid_md.startswith("<!-- doc_meta:")
    assert "pages=2" in result.hybrid_md
    assert "ocr_pages=0" in result.hybrid_md
    assert "figure_count=0" in result.hybrid_md
    assert "source_pdf=doc.pdf" in result.hybrid_md


def test_assemble_emits_page_anchors_and_headings():
    extract_meta = {"page_count": 3, "problem_pages": []}
    phase1_md = _make_phase1_md({1: "alpha", 2: "beta", 3: "gamma"})
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256=None,
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=None,
        figures_data=None,
    )
    md = result.hybrid_md
    assert "<a id=\"p1\"></a>\n## Page 1" in md
    assert "<a id=\"p2\"></a>\n## Page 2" in md
    assert "<a id=\"p3\"></a>\n## Page 3" in md
    assert "alpha" in md and "beta" in md and "gamma" in md


def test_assemble_uses_ocr_text_for_problem_pages():
    extract_meta = {"page_count": 2, "problem_pages": [2]}
    phase1_md = _make_phase1_md({1: "clean", 2: "garbage"}, with_problem_pages={2})
    ocr_data = {
        "pages": [{"page_number": 2, "text": "OCR rescued text", "status": "ok"}],
    }
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256=None,
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=ocr_data,
        figures_data=None,
    )
    assert "OCR rescued text" in result.hybrid_md
    assert "garbage" not in result.hybrid_md
    assert result.page_sources["ocr_ok"] == 1
    assert result.page_sources["pymupdf_clean"] == 1


def test_assemble_inlines_figure_blocks_at_page_position():
    extract_meta = {"page_count": 2, "problem_pages": []}
    phase1_md = _make_phase1_md({1: "page one body", 2: "page two body"})
    figures_data = {
        "figures": [
            {
                "figure_id": "p1_f1",
                "page_number": 1,
                "page_index_within": 1,
                "asset_path": "doc.assets/figure_p1_f1.png",
                "raw_caption_candidate": "Figure 1. Test",
                "description": "A test figure",
                "content_type": "figure",
                "captioner": "gemini:test",
                "redacted": False,
                "error": None,
            }
        ]
    }
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256=None,
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=None,
        figures_data=figures_data,
    )
    md = result.hybrid_md
    # figure block appears after page 1 body but before page 2 anchor
    page1_idx = md.index("page one body")
    fig_idx = md.index("### Figure p1_f1")
    page2_idx = md.index("<a id=\"p2\"")
    assert page1_idx < fig_idx < page2_idx
    assert result.figure_counts["captioned"] == 1


def test_assemble_orders_multiple_figures_on_same_page():
    extract_meta = {"page_count": 1, "problem_pages": []}
    phase1_md = _make_phase1_md({1: "body"})
    figures_data = {
        "figures": [
            {
                "figure_id": "p1_f2", "page_number": 1, "page_index_within": 2,
                "asset_path": "doc.assets/figure_p1_f2.png",
                "raw_caption_candidate": "", "description": None,
                "content_type": None, "captioner": None,
                "redacted": False, "error": None,
            },
            {
                "figure_id": "p1_f1", "page_number": 1, "page_index_within": 1,
                "asset_path": "doc.assets/figure_p1_f1.png",
                "raw_caption_candidate": "", "description": None,
                "content_type": None, "captioner": None,
                "redacted": False, "error": None,
            },
        ]
    }
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256=None,
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=None,
        figures_data=figures_data,
    )
    md = result.hybrid_md
    assert md.index("### Figure p1_f1") < md.index("### Figure p1_f2")


def test_assemble_counts_redacted_and_errored_figures():
    extract_meta = {"page_count": 1, "problem_pages": []}
    phase1_md = _make_phase1_md({1: "body"})
    figures_data = {
        "figures": [
            {
                "figure_id": "p1_f1", "page_number": 1, "page_index_within": 1,
                "asset_path": None,
                "raw_caption_candidate": "", "description": "[REDACTED: (b)(4)]",
                "content_type": "redaction", "captioner": "skipped:redacted",
                "redacted": True, "error": None,
            },
            {
                "figure_id": "p1_f2", "page_number": 1, "page_index_within": 2,
                "asset_path": "doc.assets/figure_p1_f2.png",
                "raw_caption_candidate": "", "description": None,
                "content_type": "error", "captioner": "gemini:failed",
                "redacted": False, "error": "TimeoutError",
            },
        ]
    }
    result = assemble_md.assemble(
        stem="doc",
        source_pdf_name="doc.pdf",
        source_pdf_sha256=None,
        phase1_md_text=phase1_md,
        extract_metadata=extract_meta,
        ocr_data=None,
        figures_data=figures_data,
    )
    assert result.figure_counts["redacted"] == 1
    assert result.figure_counts["errored"] == 1
    assert result.figure_counts["captioned"] == 0
    assert result.figure_counts["uncaptioned"] == 0
    assert result.figure_counts["total"] == 2


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_writes_hybrid_md_and_assembly_json(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text(
        _make_phase1_md({1: "alpha", 2: "beta"}), encoding="utf-8"
    )
    (tmp_path / "doc.extract.json").write_text(
        json.dumps({"page_count": 2, "problem_pages": []}), encoding="utf-8"
    )
    rc = assemble_md.main(["--pdf", str(pdf), "--out", str(tmp_path), "--quiet"])
    assert rc == 0
    hybrid = tmp_path / "doc.hybrid.md"
    asm = tmp_path / "doc.assembly.json"
    assert hybrid.exists()
    assert asm.exists()
    md = hybrid.read_text(encoding="utf-8")
    assert "<a id=\"p1\"></a>" in md
    assert "<a id=\"p2\"></a>" in md
    asm_data = json.loads(asm.read_text(encoding="utf-8"))
    assert asm_data["page_count"] == 2
    assert asm_data["page_sources"]["pymupdf_clean"] == 2


def test_cli_refuses_overwrite_without_force(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text(
        _make_phase1_md({1: "alpha"}), encoding="utf-8"
    )
    (tmp_path / "doc.extract.json").write_text(
        json.dumps({"page_count": 1, "problem_pages": []}), encoding="utf-8"
    )
    (tmp_path / "doc.hybrid.md").write_text("preexisting", encoding="utf-8")

    rc = assemble_md.main(["--pdf", str(pdf), "--out", str(tmp_path), "--quiet"])
    assert rc == 0
    assert (tmp_path / "doc.hybrid.md").read_text(encoding="utf-8") == "preexisting"


def test_cli_force_overwrites(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text(
        _make_phase1_md({1: "alpha"}), encoding="utf-8"
    )
    (tmp_path / "doc.extract.json").write_text(
        json.dumps({"page_count": 1, "problem_pages": []}), encoding="utf-8"
    )
    (tmp_path / "doc.hybrid.md").write_text("preexisting", encoding="utf-8")

    rc = assemble_md.main(["--pdf", str(pdf), "--out", str(tmp_path), "--force", "--quiet"])
    assert rc == 0
    md = (tmp_path / "doc.hybrid.md").read_text(encoding="utf-8")
    assert "alpha" in md
    assert "preexisting" not in md


def test_cli_required_sidecar_missing_returns_2(tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    # no .md, no .extract.json
    rc = assemble_md.main(["--pdf", str(pdf), "--out", str(tmp_path), "--quiet"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Integration tests on real fixtures
# ---------------------------------------------------------------------------

def test_integration_chemr(chemr_pdf, tmp_path: Path):
    """ChemR has 51 pages and 5 OCR'd pages (47-51); assembly succeeds end-to-end."""
    import shutil
    out = tmp_path / "FDA"
    out.mkdir()
    stem = chemr_pdf.stem
    # Copy required + optional sidecars from the real on-disk location
    src_dir = chemr_pdf.parent
    for ext in (".md", ".extract.json", ".ocr.json", ".figures.json"):
        sc = src_dir / f"{stem}{ext}"
        if sc.exists():
            shutil.copy(sc, out / sc.name)

    rc = assemble_md.main(["--pdf", str(chemr_pdf), "--out", str(out), "--quiet"])
    assert rc == 0

    hybrid = out / f"{stem}.hybrid.md"
    md = hybrid.read_text(encoding="utf-8")
    # Has all 51 page anchors
    for pn in range(1, 52):
        assert f'<a id="p{pn}"></a>' in md
    # Pages 47-51 were OCR'd; their bodies should contain something OCR-only
    # (e.g. "FILING CONCLUSION" from page 47's OCR)
    assert "FILING CONCLUSION" in md

    asm = json.loads((out / f"{stem}.assembly.json").read_text(encoding="utf-8"))
    assert asm["page_count"] == 51
    assert asm["page_sources"]["ocr_ok"] == 5
    assert asm["page_sources"]["pymupdf_clean"] == 46


def test_integration_multidisc_has_figure_blocks(multidisc_pdf, tmp_path: Path):
    """Multidisc has 188 figures; verify a few figure blocks land at the right anchors.

    The on-disk Phase 1 output for this PDF predates the current sidecar format
    (Azure DI extraction, no .extract.json). Synthesize a minimal extract.json
    from the .md frontmatter so the test can run.
    """
    import shutil
    out = tmp_path / "FDA"
    out.mkdir()
    stem = multidisc_pdf.stem
    src_dir = multidisc_pdf.parent
    if not (src_dir / f"{stem}.figures.json").exists():
        pytest.skip(f"{stem}.figures.json missing; run extract_figures first")
    for ext in (".md", ".ocr.json", ".figures.json"):
        sc = src_dir / f"{stem}{ext}"
        if sc.exists():
            shutil.copy(sc, out / sc.name)
    if not (out / f"{stem}.md").exists():
        pytest.skip(f"{stem}.md missing")

    # Synthesize a minimal .extract.json by parsing page_count from the .md frontmatter
    md_text = (out / f"{stem}.md").read_text(encoding="utf-8")
    m = re.search(r"^page_count:\s*(\d+)", md_text, re.MULTILINE)
    if not m:
        pytest.skip("could not infer page_count from .md frontmatter")
    page_count = int(m.group(1))
    (out / f"{stem}.extract.json").write_text(
        json.dumps({"page_count": page_count, "problem_pages": []}), encoding="utf-8"
    )

    rc = assemble_md.main(["--pdf", str(multidisc_pdf), "--out", str(out), "--quiet"])
    assert rc == 0
    hybrid = out / f"{stem}.hybrid.md"
    md = hybrid.read_text(encoding="utf-8")
    # First figure on page 11 should be present
    figures_meta = json.loads((src_dir / f"{stem}.figures.json").read_text(encoding="utf-8"))
    assert figures_meta["figure_count"] > 0
    first = figures_meta["figures"][0]
    # Heading appears - works for any content_type (figure/table/redaction)
    # Both "### Figure pN_fM" and "### Table pN_fM" are valid
    fid = first["figure_id"]
    assert (f"### Figure {fid}" in md) or (f"### Table {fid}" in md)
    asm = json.loads((out / f"{stem}.assembly.json").read_text(encoding="utf-8"))
    assert asm["figure_counts"]["total"] == figures_meta["figure_count"]
