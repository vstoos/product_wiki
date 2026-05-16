"""Tests for caption_figure.py. HTTP mocked; no live model calls."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_path = SCRIPTS / "caption_figure.py"
_spec = importlib.util.spec_from_file_location("caption_figure", _path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/caption_figure.py at {_path}. "
        "Task 11 must create it before these tests can pass."
    )
caption_figure = importlib.util.module_from_spec(_spec)
sys.modules["caption_figure"] = caption_figure
_spec.loader.exec_module(caption_figure)


# --- render_prompt ---

def test_render_prompt_full_substitution():
    out = caption_figure.render_prompt(
        substance="apalutamide",
        nearby_text="Plasma concentration",
        raw_caption_candidate="Figure 2. PK profile.",
    )
    assert "apalutamide" in out
    assert "Plasma concentration" in out
    assert "Figure 2. PK profile." in out
    assert "{substance}" not in out
    assert "{nearby_text}" not in out
    assert "{raw_caption_candidate}" not in out


def test_render_prompt_drops_substance_when_none():
    out = caption_figure.render_prompt(
        substance=None,
        nearby_text="some context",
        raw_caption_candidate="Figure 1.",
    )
    assert "Substance:" not in out
    assert "some context" in out


def test_render_prompt_drops_empty_nearby_and_candidate():
    out = caption_figure.render_prompt(
        substance="apalutamide",
        nearby_text="",
        raw_caption_candidate="",
    )
    assert "Nearby text" not in out
    assert "Caption candidate" not in out
    assert "apalutamide" in out


# --- compute_prompt_hash ---

def test_compute_prompt_hash_is_deterministic():
    a = caption_figure.compute_prompt_hash("hello world")
    b = caption_figure.compute_prompt_hash("hello world")
    assert a == b
    assert len(a) == 16


def test_compute_prompt_hash_differs_for_different_input():
    a = caption_figure.compute_prompt_hash("hello world")
    b = caption_figure.compute_prompt_hash("hello world.")
    assert a != b


# --- validate_captioning_model ---

def test_validate_captioning_model_rejects_glm_ocr():
    err = caption_figure.validate_captioning_model("lmstudio", "glm-ocr")
    assert err is not None
    assert "general vision" in err.lower() or "denylist" in err.lower()


def test_validate_captioning_model_rejects_lightonocr():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "lightonocr-2-1b-ocr-soup"
    ) is not None


def test_validate_captioning_model_rejects_deepseek_ocr():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "deepseek-ocr"
    ) is not None


def test_validate_captioning_model_accepts_gemma_4b():
    assert caption_figure.validate_captioning_model(
        "lmstudio", "gemma-4-e4b-it"
    ) is None


def test_validate_captioning_model_ignores_engine_gemini():
    """Denylist applies to LMStudio engine only (Gemini doesn't serve those models)."""
    assert caption_figure.validate_captioning_model(
        "gemini", "glm-ocr"  # nonsense for gemini but not our concern here
    ) is None


# --- check_sidecar_freshness ---

def test_check_sidecar_freshness_passes_when_hashes_match(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"PDF BODY")
    sidecar = {
        "source_pdf_sha256": caption_figure._sha256_file(pdf),
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    assert caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8
    ) is None


def test_check_sidecar_freshness_fails_when_pdf_changed(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"NEW PDF BODY")
    sidecar = {
        "source_pdf_sha256": "0" * 64,  # stale
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8
    )
    assert diag is not None
    assert "sha256" in diag.lower() or "pdf" in diag.lower()


def test_check_sidecar_freshness_fails_when_thresholds_differ(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"PDF BODY")
    sidecar = {
        "source_pdf_sha256": caption_figure._sha256_file(pdf),
        "extractor_thresholds_hash": "old" + "0" * 61,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="new" + "0" * 61,
    )
    assert diag is not None
    assert "threshold" in diag.lower()


def test_check_sidecar_freshness_handles_missing_pdf(tmp_path):
    """If the source PDF is gone, treat as stale with a clear diagnostic."""
    pdf = tmp_path / "doc.pdf"  # not created
    sidecar = {
        "source_pdf_sha256": "0" * 64,
        "extractor_thresholds_hash": "deadbeef" * 8,
    }
    diag = caption_figure.check_sidecar_freshness(
        sidecar, pdf_path=pdf, current_thresholds_hash="deadbeef" * 8,
    )
    assert diag is not None
    assert "missing" in diag.lower() or "not found" in diag.lower()


def _seed_assets(tmp_path: Path) -> Path:
    """Create a minimal assets dir with one PNG."""
    assets = tmp_path / "stem.assets"
    assets.mkdir(parents=True)
    (assets / "figure_p1_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return tmp_path


def _make_figure(asset_rel: str | None, *, redacted: bool = False,
                 captioner: str | None = None,
                 description: str | None = None) -> dict:
    return {
        "figure_id": "p1_f1",
        "page_number": 1,
        "page_index_within": 1,
        "asset_path": asset_rel,
        "asset_sha256": "x" * 64 if asset_rel else None,
        "bbox_normalized": [0.1, 0.2, 0.8, 0.6],
        "extraction_method": "native_extract_image",
        "size_bytes": 16,
        "width_px": 100,
        "height_px": 80,
        "raw_caption_candidate": "Figure 1." if not redacted else "(b)(4)",
        "raw_caption_candidate_tier": 1,
        "page_text_verbatim": "Page 1 full text.",
        "page_text_verbatim_tier": 1,
        "nearby_text": "context" if not redacted else "",
        "nearby_text_tier": None,
        "redacted": redacted,
        "captioner": captioner,
        "prompt_hash": None,
        "description": description,
        "description_tier": 2 if description and not redacted else None,
        "content_type": ("redaction" if redacted else
                         ("figure" if description else None)),
        "error": None,
    }


def test_caption_one_figure_skips_redacted(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure(None, redacted=True,
                       captioner="skipped:redacted",
                       description="[REDACTED: (b)(4)]")
    fig["content_type"] = "redaction"
    with patch("urllib.request.urlopen") as urlopen:
        out = caption_figure.caption_one_figure(
            fig,
            assets_root=root,
            substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("k", "m")], "timeout": 10},
        )
        assert urlopen.call_count == 0
    assert out["description"] == "[REDACTED: (b)(4)]"
    assert out["content_type"] == "redaction"


def test_caption_one_figure_lmstudio_structured_success(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_lmstudio_structured",
                      return_value=("figure", "A PK plot.")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="lmstudio",
            backend_kwargs={"host": "http://localhost:1234", "model": "gemma-4-e4b-it", "timeout": 60},
        )
    assert out["description"] == "A PK plot."
    assert out["content_type"] == "figure"
    assert out["description_tier"] == 2
    assert out["captioner"].startswith("lmstudio:gemma-4-e4b-it@")
    assert isinstance(out["prompt_hash"], str) and len(out["prompt_hash"]) == 16


def test_caption_one_figure_gemini_table_success(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("table", "<table><tr><td>x</td></tr></table>")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "table"
    assert out["description"].startswith("<table")
    assert out["description_tier"] == 2
    assert out["captioner"].startswith("gemini:gemma-4-31b-it@")


def test_caption_one_figure_records_parse_error(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=(None, "not json sorry")):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "error"
    assert "parse" in out["error"].lower()
    assert out["description"] == ""
    assert out["description_tier"] is None


def test_caption_one_figure_records_http_error(tmp_path):
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    def boom(*a, **kw):
        raise RuntimeError("HTTPError 500")
    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=boom):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K1", "gemma-4-31b-it")], "timeout": 60},
        )
    assert out["content_type"] == "error"
    assert "HTTPError" in out["error"]


def test_caption_one_figure_gemini_round_robin_advances_on_429(tmp_path):
    """First pair 429s; second pair succeeds. caption_one_figure must not error."""
    import urllib.error
    root = _seed_assets(tmp_path)
    fig = _make_figure("stem.assets/figure_p1_f1.png")
    calls: list[tuple[str, str]] = []
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        calls.append((api_key, model))
        if api_key == "K1":
            raise urllib.error.HTTPError(
                url="http://x", code=429, msg="rate", hdrs=None, fp=None,
            )
        return ("figure", "A plot.")
    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out = caption_figure.caption_one_figure(
            fig, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={
                "pairs": [("K1", "m1"), ("K2", "m2")],
                "timeout": 60,
            },
        )
    assert calls == [("K1", "m1"), ("K2", "m2")]
    assert out["content_type"] == "figure"


def test_process_figures_skips_already_captioned(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure("stem.assets/figure_p1_f1.png",
                         captioner="gemini:gemma-4-31b-it@2026-05-15",
                         description="Existing caption.")]
    with patch.object(caption_figure, "transcribe_gemini_structured") as gem:
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=None,
        )
        assert gem.call_count == 0
    assert out[0]["description"] == "Existing caption."
    assert stats["captioned"] == 0
    assert stats["skipped_done"] == 1


def test_process_figures_force_recaptions(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure("stem.assets/figure_p1_f1.png",
                         captioner="gemini:gemma-4-31b-it@2026-05-15",
                         description="Stale.")]
    with patch.object(caption_figure, "transcribe_gemini_structured",
                      return_value=("figure", "Fresh.")):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "gemma-4-31b-it")], "timeout": 10},
            force=True, rate_budget_calls=None,
        )
    assert out[0]["description"] == "Fresh."
    assert stats["captioned"] == 1


def test_process_figures_rate_budget_stops_after_n(tmp_path):
    root = _seed_assets(tmp_path)
    figs = [_make_figure(f"stem.assets/figure_p{i}_f1.png") for i in range(1, 6)]
    # Seed extra PNGs
    for i in range(2, 6):
        (root / "stem.assets" / f"figure_p{i}_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nF")
        figs[i - 1]["figure_id"] = f"p{i}_f1"
        figs[i - 1]["page_number"] = i

    call_count = {"n": 0}
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        call_count["n"] += 1
        return ("figure", f"caption {call_count['n']}")

    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=3,
        )
    assert call_count["n"] == 3
    assert stats["budget_exhausted"] is True
    # First three are captioned; last two left untouched
    assert sum(1 for f in out if f.get("description")) == 3


def test_process_figures_resume_after_budget(tmp_path):
    """Re-run with same figures (3 already done) plus remaining budget completes the rest."""
    root = _seed_assets(tmp_path)
    figs = [_make_figure(f"stem.assets/figure_p{i}_f1.png") for i in range(1, 6)]
    for i in range(2, 6):
        (root / "stem.assets" / f"figure_p{i}_f1.png").write_bytes(b"\x89PNG\r\n\x1a\nF")
        figs[i - 1]["figure_id"] = f"p{i}_f1"
        figs[i - 1]["page_number"] = i
    # Pre-mark figures 1-3 as already captioned
    for f in figs[:3]:
        f["captioner"] = "gemini:gemma-4-31b-it@2026-05-15"
        f["description"] = "done earlier"
        f["content_type"] = "figure"
        f["description_tier"] = 2

    call_count = {"n": 0}
    def fake(image_png_bytes, *, api_key, model, timeout, prompt):
        call_count["n"] += 1
        return ("figure", f"resumed {call_count['n']}")

    with patch.object(caption_figure, "transcribe_gemini_structured", side_effect=fake):
        out, stats = caption_figure.process_figures(
            figs, assets_root=root, substance="apalutamide",
            engine="gemini",
            backend_kwargs={"pairs": [("K", "m")], "timeout": 10},
            force=False, rate_budget_calls=None,
        )
    assert call_count["n"] == 2  # only the two unfinished figures
    assert stats["captioned"] == 2
    assert stats["skipped_done"] == 3
    assert all(f["description"] for f in out)
