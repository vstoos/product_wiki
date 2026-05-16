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
