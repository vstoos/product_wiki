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


def test_page_text_verbatim_returns_page_get_text():
    class _FakePage:
        def get_text(self, mode="text"):
            if mode == "text":
                return "Page one full text in document order.\nLine two.\n"
            return None
    assert (
        extract_figures.page_text_verbatim(_FakePage())
        == "Page one full text in document order.\nLine two.\n"
    )


def test_nearby_text_captures_caption_candidate():
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [
                    (50, 100, 550, 130, "Figure 2. Plasma concentration over 24h.", 0, 0),
                    (50, 200, 550, 600, "[image]", 1, 1),
                    (50, 650, 550, 700, "Source: Sponsor analysis.", 2, 0),
                ]
            return "Figure 2. Plasma concentration over 24h.\n[image]\nSource: Sponsor analysis.\n"

    bbox_pdf = (50, 200, 550, 600)
    nearby, candidate = extract_figures.nearby_text_for_bbox(
        _FakePage(), bbox_pdf, max_chars=600
    )
    assert "Figure 2" in candidate
    assert "Plasma concentration" in candidate
    assert ("Plasma" in nearby) or ("Source" in nearby)


def test_nearby_text_ranks_closest_first():
    """Closer block appears earlier in nearby_text."""
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [
                    # Far-above block
                    (50, 10, 550, 40, "FAR_ABOVE_TEXT", 0, 0),
                    # Just-above block (closest)
                    (50, 380, 550, 400, "JUST_ABOVE_TEXT", 1, 0),
                    # Figure region
                    (50, 410, 550, 600, "[image]", 2, 1),
                    # Just-below block (close)
                    (50, 610, 550, 640, "JUST_BELOW_TEXT", 3, 0),
                ]
            return "irrelevant for this test"

    bbox_pdf = (50, 410, 550, 600)
    nearby, _ = extract_figures.nearby_text_for_bbox(
        _FakePage(), bbox_pdf, max_chars=10000
    )
    just_above_idx = nearby.find("JUST_ABOVE_TEXT")
    far_above_idx = nearby.find("FAR_ABOVE_TEXT")
    assert just_above_idx != -1 and far_above_idx != -1
    assert just_above_idx < far_above_idx, (
        f"closest-first violated: {nearby!r}"
    )


def test_nearby_text_truncates_to_max_chars():
    long = "X" * 5000
    class _FakePage:
        rect = type("R", (), {"width": 600.0, "height": 800.0})()
        def get_text(self, mode="text"):
            if mode == "blocks":
                return [(50, 100, 550, 130, long, 0, 0)]
            return long

    nearby, _ = extract_figures.nearby_text_for_bbox(
        _FakePage(), (50, 200, 550, 600), max_chars=600
    )
    assert len(nearby) <= 600


import fitz  # noqa: E402 -- after sys.modules registration above


def test_extract_figures_from_page_returns_pair(multidisc_pdf):
    """Returns (figures, dropped_header_decorations) tuple."""
    with fitz.open(multidisc_pdf) as doc:
        out = extract_figures.extract_figures_from_page(
            doc, 0,
            header_fraction=0.15,
            header_min_height=0.08,
            redaction_thresholds=(15.0, 245.0),
            min_area_px=400,
            nearby_text_max_chars=2500,
        )
    assert isinstance(out, tuple) and len(out) == 2
    figures, dropped = out
    assert isinstance(figures, list)
    assert isinstance(dropped, list)


def test_extract_figures_from_page_attaches_page_text_verbatim_to_every_figure(multidisc_pdf):
    """If a page has multiple figures, page_text_verbatim is identical across them."""
    with fitz.open(multidisc_pdf) as doc:
        page_count = doc.page_count
        for i in range(min(220, page_count)):
            figures, _ = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if len(figures) >= 2:
                texts = {f["page_text_verbatim"] for f in figures}
                assert len(texts) == 1, "page_text_verbatim must be shared per page"
                return
    pytest.skip("no page with 2+ figures in first 220 pages")


def test_extract_figures_from_page_returns_required_keys(multidisc_pdf):
    """Each figure dict has every key the downstream JSON schema needs."""
    required = {
        "page_number", "page_index_within", "bbox_normalized", "image_bytes",
        "raw_caption_candidate", "nearby_text", "page_text_verbatim",
        "redacted", "width_px", "height_px", "size_bytes", "extraction_method",
    }
    with fitz.open(multidisc_pdf) as doc:
        for i in range(min(220, doc.page_count)):
            figures, _ = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if figures:
                missing = required - set(figures[0].keys())
                assert not missing, f"missing keys: {missing}"
                return
    pytest.skip("no figures found in first 220 pages of MultidisciplineR")


def test_extract_figures_from_page_dropped_decoration_shape(multidisc_pdf):
    """When the filter drops a candidate, the entry has the documented shape."""
    with fitz.open(multidisc_pdf) as doc:
        for i in range(min(220, doc.page_count)):
            _, dropped = extract_figures.extract_figures_from_page(
                doc, i,
                header_fraction=0.15,
                header_min_height=0.08,
                redaction_thresholds=(15.0, 245.0),
                min_area_px=400,
                nearby_text_max_chars=2500,
            )
            if dropped:
                d = dropped[0]
                for k in ("page_number", "bbox_normalized", "size_bytes", "reason"):
                    assert k in d, f"missing dropped-key: {k}"
                assert d["reason"] == "header_band"
                return
    pytest.skip("no header decorations dropped in first 220 pages")
