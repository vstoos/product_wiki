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


# Calibration corpus seeded 2026-05-16 from a full apalutamide backfill
# (40 PDFs, 1418 pages, 1504 figures, 128 redactions detected). Tuples are
# (agency, filename, page_number). Each is a page with at least one (b)(4)
# raster redaction at default detector thresholds (stddev_max=15, mean_max=245).
APALUTAMIDE_DIR = Path(__file__).resolve().parents[3] / "apalutamide"
KNOWN_REDACTIONS: list[tuple[str, str, int]] = [
    # FDA NDA cover sheet: one large (~76% page width) horizontal (b)(4) block.
    ("FDA", "210951Orig1s000ChemR.pdf", 38),
    # FDA Multidiscipline review: cover-of-the-clinical-review tables with
    # many small (b)(4) line redactions; pages 5-7 are densely redacted.
    ("FDA", "210951Orig1s000MultidisciplineR.pdf", 5),
    ("FDA", "210951Orig1s000MultidisciplineR.pdf", 6),
    ("FDA", "210951Orig1s000MultidisciplineR.pdf", 7),
    # FDA label supplement with embedded (b)(4) values scattered throughout.
    ("FDA", "SUPPL_004_210951s004lbl.pdf", 2),
    # TGA PI: single mid-page (~34% width) redacted block.
    ("TGA", "TGA_PI_-_AusPAR__Apalutamide.pdf", 15),
]


@pytest.mark.parametrize("agency,filename,page_number", KNOWN_REDACTIONS)
def test_is_redaction_against_known_corpus_redactions(agency, filename, page_number):
    """Re-extract a page from the apalutamide corpus and assert at least one
    figure is flagged redacted. Locks in (b)(4) detection against silent
    threshold drift or PyMuPDF rendering changes."""
    pdf_path = APALUTAMIDE_DIR / agency / filename
    if not pdf_path.exists():
        pytest.skip(f"corpus PDF missing: {pdf_path}")

    with fitz.open(pdf_path) as doc:
        figs, _ = extract_figures.extract_figures_from_page(
            doc, page_number - 1,
            header_fraction=0.15,
            header_min_height=0.08,
            redaction_thresholds=(15.0, 245.0),
            min_area_px=400,
            nearby_text_max_chars=2500,
        )
    redacted = [f for f in figs if f.get("redacted")]
    assert redacted, (
        f"{filename} p.{page_number}: expected >=1 redacted figure, got "
        f"{len(figs)} figures with redacted={[f.get('redacted') for f in figs]}"
    )


# Per-source figure-yield baselines seeded 2026-05-16 from the same full backfill.
# Values are (agency, expected_figures, expected_redacted). Regression test
# below pins each within +-20% (with a +-2 absolute floor for tiny yields).
# A drop signals silent under-coverage; a spike signals false-positive surge.
# Source: <stem>.figures.json sidecars from
# `extract_figures.py --pdf <p> --out apalutamide/<agency> --quiet` over the
# full apalutamide corpus.
COVERAGE_EXPECTATIONS: dict[str, dict] = {
    # FDA NDA reviews
    "210951Orig1s000MultidisciplineR.pdf": {"agency": "FDA", "figures": 188, "redacted": 109},
    "210951Orig1s000ChemR.pdf":            {"agency": "FDA", "figures":  38, "redacted":   1},
    # FDA labels / PSG / DailyMed
    "SUPPL_011_210951Orig1s011lbl.pdf":    {"agency": "FDA", "figures":   3, "redacted":   0},
    "SUPPL_004_210951s004lbl.pdf":         {"agency": "FDA", "figures":  22, "redacted":  17},
    "DailyMed_label_d1cda4f7-cb33-46ea-b9ac-431f6452b1a5.pdf":
                                           {"agency": "FDA", "figures":   7, "redacted":   0},
    "PSG_210951.pdf":                      {"agency": "FDA", "figures":   0, "redacted":   0},
    # EMA EPAR set (raster-only; EPAR Assessment Report still under-yields
    # vector plots; Phase 3.1 closes that gap)
    "Erleada_-_Erleada___EPAR_-_Public_assessment_report.pdf":
                                           {"agency": "EMA", "figures": 674, "redacted":   0},
    "Erleada_-_Erleada-H-C-4452-II-0001___EPAR_-_Assessment_Report_-_Variation.pdf":
                                           {"agency": "EMA", "figures": 400, "redacted":   0},
    "Erleada_-_Erleada___EPAR_-_Product_information.pdf":
                                           {"agency": "EMA", "figures":  44, "redacted":   0},
    "Erleada_-_Erleada-H-C-004452-X-0028-G___EPAR_-_Assessment_report_-_Extension.pdf":
                                           {"agency": "EMA", "figures":  10, "redacted":   0},
    # HC Product Monograph
    "Product_Monograph_-_ERLEADA.pdf":     {"agency": "HC",  "figures":   8, "redacted":   0},
    # PMDA review
    "PMDA_Review_Report_-_Erleada__Apalutamide_.pdf":
                                           {"agency": "PMDA","figures":  14, "redacted":   0},
    # TGA
    "TGA_AusPAR_-_AusPAR__Apalutamide.pdf":{"agency": "TGA", "figures":  14, "redacted":   0},
    "TGA_PI_-_AusPAR__Apalutamide.pdf":    {"agency": "TGA", "figures":   2, "redacted":   1},
}


def _coverage_tolerance(expected: int) -> int:
    """+-20% with a +-2 absolute floor for tiny yields."""
    return max(2, int(round(expected * 0.20)))


@pytest.mark.parametrize("filename,expected", list(COVERAGE_EXPECTATIONS.items()))
def test_corpus_figure_yield_within_tolerance(filename, expected):
    """Pin per-source figure yield to the seeded baseline within +-20%.

    Reads pre-generated sidecars rather than re-extracting (fast). Skips when
    the sidecar is missing - run `extract_figures.py --pdf <p> --out
    apalutamide/<agency>` once across the corpus to seed.
    """
    sidecar = APALUTAMIDE_DIR / expected["agency"] / f"{Path(filename).stem}.figures.json"
    if not sidecar.exists():
        pytest.skip(f"sidecar missing - run extract_figures.py first: {sidecar}")

    payload = json.loads(sidecar.read_text(encoding="utf-8"))

    actual_f = payload["figure_count"]
    exp_f = expected["figures"]
    tol_f = _coverage_tolerance(exp_f)
    assert abs(actual_f - exp_f) <= tol_f, (
        f"{filename}: figure_count expected {exp_f}+-{tol_f}, got {actual_f}"
    )

    actual_r = payload["redacted_count"]
    exp_r = expected["redacted"]
    if exp_r == 0:
        assert actual_r == 0, (
            f"{filename}: expected 0 redactions, got {actual_r} - false-positive surge?"
        )
    else:
        tol_r = _coverage_tolerance(exp_r)
        assert abs(actual_r - exp_r) <= tol_r, (
            f"{filename}: redacted_count expected {exp_r}+-{tol_r}, got {actual_r}"
        )


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


def test_write_figure_assets_writes_non_redacted_pngs(tmp_path):
    figs = [
        {
            "page_number": 47, "page_index_within": 1,
            "bbox_normalized": [0.1, 0.3, 0.8, 0.6],
            "image_bytes": b"\x89PNG\r\n\x1a\nFAKE_OK",
            "raw_caption_candidate": "Figure 2.",
            "nearby_text": "context",
            "page_text_verbatim": "Page 47 full text.",
            "redacted": False,
            "width_px": 100, "height_px": 80, "size_bytes": 13,
            "extraction_method": "native_extract_image",
        },
        {
            "page_number": 51, "page_index_within": 1,
            "bbox_normalized": [0.4, 0.2, 0.7, 0.4],
            "image_bytes": b"REDACTED-BYTES",
            "raw_caption_candidate": "(b)(4)",
            "nearby_text": "",
            "page_text_verbatim": "Page 51 full text including (b)(4).",
            "redacted": True,
            "width_px": 50, "height_px": 30, "size_bytes": 14,
            "extraction_method": "native_extract_image",
        },
    ]
    assets_dir = tmp_path / "stem.assets"
    out = extract_figures.write_figure_assets(figs, assets_dir)

    assert len(out) == 2
    # non-redacted: file written, asset_path set, asset_sha256 set, image_bytes stripped
    a = out[0]
    assert a["asset_path"] == "stem.assets/figure_p47_f1.png"
    assert (assets_dir / "figure_p47_f1.png").exists()
    assert isinstance(a["asset_sha256"], str) and len(a["asset_sha256"]) == 64
    assert "image_bytes" not in a
    assert a["figure_id"] == "p47_f1"
    assert a["captioner"] is None
    assert a["description"] is None
    assert a["content_type"] is None
    assert a["description_tier"] is None
    assert a["raw_caption_candidate_tier"] == 1
    assert a["page_text_verbatim_tier"] == 1
    assert a["nearby_text_tier"] is None
    assert a["prompt_hash"] is None
    assert a["error"] is None

    # redacted: no file, asset_path None, pre-filled redaction values
    r = out[1]
    assert r["asset_path"] is None
    assert not (assets_dir / "figure_p51_f1.png").exists()
    assert "image_bytes" not in r
    assert r["redacted"] is True
    assert r["captioner"] == "skipped:redacted"
    assert r["description"] == "[REDACTED: (b)(4)]"
    assert r["content_type"] == "redaction"
    assert r["description_tier"] is None
    assert r["raw_caption_candidate_tier"] == 1
    assert r["page_text_verbatim_tier"] == 1
    assert r["nearby_text_tier"] is None


def test_hash_thresholds_is_deterministic():
    h1 = extract_figures.hash_thresholds({"a": 1, "b": 2})
    h2 = extract_figures.hash_thresholds({"b": 2, "a": 1})  # key order irrelevant
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 64  # sha256 hex


def test_hash_thresholds_changes_with_value():
    h1 = extract_figures.hash_thresholds({"x": 0.15})
    h2 = extract_figures.hash_thresholds({"x": 0.16})
    assert h1 != h2


def test_compute_pdf_sha256_prefers_meta_json(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"DUMMY PDF")
    meta = tmp_path / "doc.meta.json"
    meta.write_text(json.dumps({"sha256": "deadbeef" * 8}), encoding="utf-8")
    assert extract_figures.compute_pdf_sha256(pdf) == "deadbeef" * 8


def test_compute_pdf_sha256_computes_when_meta_absent(tmp_path):
    import hashlib
    pdf = tmp_path / "doc.pdf"
    body = b"REAL CONTENT"
    pdf.write_bytes(body)
    assert extract_figures.compute_pdf_sha256(pdf) == hashlib.sha256(body).hexdigest()


def test_cli_writes_full_sidecar_shape(multidisc_pdf, tmp_path):
    rc = extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    # Required top-level fields
    for k in (
        "schema_version", "source_file", "source_pdf_sha256",
        "extraction_date", "extractor_version", "extractor_thresholds",
        "extractor_thresholds_hash", "substance", "substance_source",
        "page_count", "figure_count", "redacted_count",
        "dropped_header_decorations", "figures",
    ):
        assert k in payload, f"missing top-level key: {k}"
    assert payload["schema_version"] == "1.0"
    assert payload["page_count"] >= 100
    assert len(payload["source_pdf_sha256"]) == 64
    assert len(payload["extractor_thresholds_hash"]) == 64


def test_cli_writes_assets_dir(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assets_dir = tmp_path / f"{multidisc_pdf.stem}.assets"
    if assets_dir.exists():
        pngs = list(assets_dir.glob("figure_p*_f*.png"))
        # Lower bound from spec Coverage table; actual seeded later.
        assert len(pngs) >= 1


def test_cli_skips_existing_without_force(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    first_mtime = json_path.stat().st_mtime

    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    assert json_path.stat().st_mtime == first_mtime


def test_cli_force_rewrites(multidisc_pdf, tmp_path):
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    first_mtime = json_path.stat().st_mtime

    # Force needs visible mtime change; sleep impractical, just touch and re-run
    import os, time
    os.utime(json_path, (first_mtime - 10, first_mtime - 10))
    pre_force_mtime = json_path.stat().st_mtime

    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--force",
        "--quiet",
    ])
    assert json_path.stat().st_mtime > pre_force_mtime


def test_cli_different_thresholds_produce_different_hash(multidisc_pdf, tmp_path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(out_a),
        "--header-fraction", "0.15",
        "--quiet",
    ])
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(out_b),
        "--header-fraction", "0.25",
        "--quiet",
    ])
    pa = json.loads((out_a / f"{multidisc_pdf.stem}.figures.json").read_text())
    pb = json.loads((out_b / f"{multidisc_pdf.stem}.figures.json").read_text())
    assert pa["extractor_thresholds_hash"] != pb["extractor_thresholds_hash"]


def test_cli_writes_atomically(multidisc_pdf, tmp_path, monkeypatch):
    """If atomic_write_json's os.replace fails, canonical file is unchanged."""
    # First run writes a valid sidecar
    extract_figures.main([
        "--pdf", str(multidisc_pdf),
        "--out", str(tmp_path),
        "--quiet",
    ])
    json_path = tmp_path / f"{multidisc_pdf.stem}.figures.json"
    original = json_path.read_text(encoding="utf-8")

    # Re-run with --force but patch os.replace to fail mid-write
    import os as _os
    def boom(src, dst):
        raise OSError("simulated disk error")
    monkeypatch.setattr(_os, "replace", boom)

    with pytest.raises(OSError):
        extract_figures.main([
            "--pdf", str(multidisc_pdf),
            "--out", str(tmp_path),
            "--force",
            "--quiet",
        ])
    assert json_path.read_text(encoding="utf-8") == original
