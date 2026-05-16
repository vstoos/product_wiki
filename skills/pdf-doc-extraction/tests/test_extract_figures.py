"""Tests for extract_figures.py. PDF I/O uses real fixtures where available."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_path = SCRIPTS / "extract_figures.py"
_spec = importlib.util.spec_from_file_location("extract_figures", _path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/extract_figures.py at {_path}. "
        "Task 4 must create it before these tests can pass."
    )
extract_figures = importlib.util.module_from_spec(_spec)
sys.modules["extract_figures"] = extract_figures
_spec.loader.exec_module(extract_figures)


def test_load_substance_metadata_reads_file(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    sub_dir.mkdir()
    (sub_dir / "metadata.json").write_text(
        json.dumps({"inn": "apalutamide", "atc": "L02BB05"}), encoding="utf-8"
    )
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.parent.mkdir()
    pdf.touch()
    md = extract_figures.load_substance_metadata(pdf)
    assert md == {"inn": "apalutamide", "atc": "L02BB05"}


def test_load_substance_metadata_returns_none_when_absent(tmp_path):
    pdf = tmp_path / "lonely.pdf"
    pdf.touch()
    assert extract_figures.load_substance_metadata(pdf) is None


def test_infer_substance_prefers_metadata_json(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    (sub_dir / "FDA").mkdir(parents=True)
    (sub_dir / "metadata.json").write_text(
        json.dumps({"inn": "apalutamide-from-metadata"}), encoding="utf-8"
    )
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name == "apalutamide-from-metadata"
    assert source == "metadata_json"


def test_infer_substance_falls_back_to_path(tmp_path):
    sub_dir = tmp_path / "apalutamide"
    (sub_dir / "FDA").mkdir(parents=True)
    pdf = sub_dir / "FDA" / "X.pdf"
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name == "apalutamide"
    assert source == "path_inference"


def test_infer_substance_returns_none_source_when_both_missing(tmp_path):
    pdf = tmp_path / "random" / "X.pdf"
    pdf.parent.mkdir()
    pdf.touch()
    name, source = extract_figures.infer_substance(pdf)
    assert name is None
    assert source == "none"


def test_infer_substance_path_uses_recognized_agency_dirs():
    """Substance name is the directory immediately above any AGENCY dir."""
    p = Path("c:/tmp/roxadustat/EMA/X.pdf")
    # Use a synthesized path; load_substance_metadata won't find anything.
    name, source = extract_figures.infer_substance(p)
    assert name == "roxadustat"
    assert source == "path_inference"


def test_is_header_decoration_top_band_short():
    """Bbox in top 5% with 5% height -> agency logo, drop."""
    bbox = (0.10, 0.02, 0.30, 0.07)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is True


def test_is_header_decoration_below_band():
    """Bbox in middle of page -> keep."""
    bbox = (0.10, 0.40, 0.50, 0.70)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False


def test_is_header_decoration_top_but_tall():
    """Bbox starts near top but is tall (real figure spanning header zone) -> keep."""
    bbox = (0.10, 0.05, 0.50, 0.40)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False


def test_is_header_decoration_below_top_band_but_short():
    """Below top band but short -> keep (not a logo, just a small figure)."""
    bbox = (0.10, 0.30, 0.30, 0.34)
    assert extract_figures.is_header_decoration(
        bbox, top_fraction=0.15, min_height=0.08
    ) is False


def _make_uniform_png(width: int, height: int, gray_level: int) -> bytes:
    """Synthesize a uniform-gray PNG via fitz.Pixmap (no PIL dep)."""
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, (gray_level, gray_level, gray_level))
    return pix.tobytes("png")


def _make_noisy_png(width: int, height: int) -> bytes:
    """Synthesize a high-variance PNG (chequerboard)."""
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    for y in range(height):
        for x in range(width):
            v = 255 if (x // 4 + y // 4) % 2 == 0 else 0
            pix.set_pixel(x, y, (v, v, v))
    return pix.tobytes("png")


def test_is_redaction_uniform_gray():
    png = _make_uniform_png(40, 40, gray_level=200)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is True


def test_is_redaction_real_figure_negative():
    png = _make_noisy_png(40, 40)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


def test_is_redaction_too_small_negative():
    """Below min_area_px: don't flag (could be a tiny icon)."""
    png = _make_uniform_png(10, 10, gray_level=200)  # 100 < 400
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


def test_is_redaction_white_too_bright_negative():
    """Pure white = page background, not a redaction."""
    png = _make_uniform_png(40, 40, gray_level=255)
    assert extract_figures.is_redaction(
        png, stddev_max=15, mean_max=245, min_area_px=400
    ) is False


# Calibration corpus is seeded post-implementation per spec
# ("Chicken-and-egg note"). Until then this list is empty.
KNOWN_REDACTIONS: list[tuple[str, int]] = []


@pytest.mark.skipif(not KNOWN_REDACTIONS, reason="KNOWN_REDACTIONS seeded post-implementation")
def test_is_redaction_against_known_corpus_redactions():
    """Pin against known (b)(4) pages. Seeded by running extract_figures.py
    on the apalutamide corpus once and recording observed redactions."""
    # Future: load page, extract figure at known bbox, assert is_redaction True
    pass
