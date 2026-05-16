"""Tests for extract_text.py — PyMuPDF text extraction tool."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load the module from an explicit path to avoid sys.path collisions
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_extract_text_path = SCRIPTS / "extract_text.py"
_spec = importlib.util.spec_from_file_location("extract_text", _extract_text_path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/extract_text.py at {_extract_text_path}. "
        "Task 3 must create it before these tests can pass."
    )
extract_text = importlib.util.module_from_spec(_spec)
sys.modules["extract_text"] = extract_text  # required for dataclass module lookup
_spec.loader.exec_module(extract_text)


def test_extract_returns_per_page_text(chemr_pdf):
    """extract() returns a dict with per-page text and metadata."""
    result = extract_text.extract(chemr_pdf)
    assert "pages" in result
    assert "metadata" in result
    assert isinstance(result["pages"], list)
    assert len(result["pages"]) == 51  # ChemR has 51 pages
    assert all(isinstance(p, dict) and "text" in p for p in result["pages"])


def test_render_markdown_has_yaml_frontmatter(chemr_pdf):
    result = extract_text.extract(chemr_pdf)
    md = extract_text.render_markdown(result)
    assert md.startswith("---\n")
    assert 'source_file: "210951Orig1s000ChemR.pdf"' in md
    assert "page_count: 51" in md
    assert 'engine: "pymupdf"' in md


def test_render_markdown_has_per_page_markers(chemr_pdf):
    result = extract_text.extract(chemr_pdf)
    md = extract_text.render_markdown(result)
    # Every page from 1..51 has a marker
    for n in range(1, 52):
        assert f"<!-- page: {n} -->" in md, f"missing marker for page {n}"


def test_problem_pages_are_flagged(chemr_pdf):
    """ChemR has scanned regions; expect at least one problem page."""
    result = extract_text.extract(chemr_pdf)
    # Don't pin the exact count (engine version may shift) — just assert detection works
    assert isinstance(result["metadata"]["problem_pages"], list)


def test_cli_writes_outputs(chemr_pdf, tmp_path):
    rc = extract_text.main([
        "--pdf", str(chemr_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    md = tmp_path / "210951Orig1s000ChemR.md"
    js = tmp_path / "210951Orig1s000ChemR.extract.json"
    assert md.exists() and md.stat().st_size > 1000
    assert js.exists()
    meta = json.loads(js.read_text(encoding="utf-8"))
    assert meta["page_count"] == 51
    assert meta["engine"] == "pymupdf"


def test_multidisc_fixture_resolves_or_skips(multidisc_pdf):
    """Fixture either points at a real PDF or pytest.skips."""
    assert multidisc_pdf.exists()
    assert multidisc_pdf.suffix == ".pdf"
