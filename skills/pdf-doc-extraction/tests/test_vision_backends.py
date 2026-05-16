"""Tests for additions to _vision_backends.py shared across tools."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "_vision_backends.py"
_spec = importlib.util.spec_from_file_location("_vision_backends", SCRIPT)
vb = importlib.util.module_from_spec(_spec)
sys.modules["_vision_backends"] = vb
_spec.loader.exec_module(vb)


# --- CAPTION_PROMPT_TEMPLATE ---

def test_caption_prompt_template_exists():
    assert hasattr(vb, "CAPTION_PROMPT_TEMPLATE")
    assert isinstance(vb.CAPTION_PROMPT_TEMPLATE, str)


def test_caption_prompt_template_has_substitution_keys():
    t = vb.CAPTION_PROMPT_TEMPLATE
    assert "{substance}" in t
    assert "{nearby_text}" in t
    assert "{raw_caption_candidate}" in t


def test_caption_prompt_template_declares_structured_output():
    t = vb.CAPTION_PROMPT_TEMPLATE.lower()
    assert "json" in t
    assert '"type"' in t
    assert '"content"' in t
    assert "figure" in t
    assert "table" in t


def test_caption_prompt_template_values_policy_is_coherent():
    t = vb.CAPTION_PROMPT_TEMPLATE.lower()
    assert "discrete" in t
    assert "continuous" in t


# --- CAPTION_DENYLIST ---

def test_caption_denylist_is_a_set_of_strings():
    assert hasattr(vb, "CAPTION_DENYLIST")
    assert isinstance(vb.CAPTION_DENYLIST, (set, frozenset))
    for m in vb.CAPTION_DENYLIST:
        assert isinstance(m, str)


def test_caption_denylist_contains_known_ocr_specialists():
    assert "glm-ocr" in vb.CAPTION_DENYLIST
    assert "lightonocr-2-1b-ocr-soup" in vb.CAPTION_DENYLIST
    assert "deepseek-ocr" in vb.CAPTION_DENYLIST


# --- atomic_write_json ---

def test_atomic_write_json_creates_file(tmp_path):
    target = tmp_path / "out.json"
    vb.atomic_write_json(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}


def test_atomic_write_json_overwrites_atomically(tmp_path):
    target = tmp_path / "out.json"
    target.write_text(json.dumps({"original": True}), encoding="utf-8")
    vb.atomic_write_json(target, {"replaced": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"replaced": True}


def test_atomic_write_json_uses_tmp_sibling(tmp_path, monkeypatch):
    """Tmp file is a sibling of target. After successful replace, no .tmp left."""
    target = tmp_path / "out.json"
    vb.atomic_write_json(target, {"x": 1})
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_atomic_write_json_leaves_canonical_intact_on_failure(tmp_path, monkeypatch):
    """If os.replace raises, the canonical file is unchanged."""
    target = tmp_path / "out.json"
    target.write_text(json.dumps({"original": True}), encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        vb.atomic_write_json(target, {"replaced": True})
    # Canonical still has original content
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
