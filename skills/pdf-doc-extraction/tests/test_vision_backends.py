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


import json as _json
from unittest.mock import patch


class _MockResponse:
    def __init__(self, body_dict, status: int = 200):
        self._body = _json.dumps(body_dict).encode("utf-8")
        self.status = status
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


# --- transcribe_lmstudio_structured ---

def test_lmstudio_structured_returns_parsed_type_and_content():
    fake_body = {"choices": [{"message": {"content": '{"type":"figure","content":"A PK plot."}'}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t == "figure"
    assert c == "A PK plot."


def test_lmstudio_structured_returns_none_on_parse_failure():
    """Model emitted non-JSON text. Helper returns (None, raw_text), caller decides."""
    fake_body = {"choices": [{"message": {"content": "This is not JSON, sorry."}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t is None
    assert c == "This is not JSON, sorry."


def test_lmstudio_structured_returns_none_on_schema_mismatch():
    """Valid JSON but missing required keys -> (None, raw)."""
    fake_body = {"choices": [{"message": {"content": '{"only_one_field":"oops"}'}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t is None
    assert '"only_one_field"' in c


def test_lmstudio_structured_strips_markdown_fences():
    """Common 4B-model failure mode: wraps JSON in ```json fences."""
    fenced = "```json\n{\"type\":\"figure\",\"content\":\"A plot.\"}\n```"
    fake_body = {"choices": [{"message": {"content": fenced}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_lmstudio_structured(
            b"\x89PNG\r\n\x1a\nFAKE",
            host="http://localhost:1234",
            model="gemma-4-e4b-it",
            timeout=10,
            prompt="hello",
        )
    assert t == "figure"
    assert c == "A plot."


def test_lmstudio_structured_sends_json_object_response_format():
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"choices": [{"message": {"content": '{"type":"figure","content":"x"}'}}]})
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vb.transcribe_lmstudio_structured(
            b"FAKE", host="http://localhost:1234", model="gemma-4-e4b-it", timeout=10, prompt="hi",
        )
    assert captured["body"].get("response_format") == {"type": "json_object"}


# --- transcribe_gemini_structured ---

def test_gemini_structured_returns_parsed_type_and_content():
    fake_body = {
        "candidates": [
            {"content": {"parts": [{"text": '{"type":"table","content":"<table>x</table>"}'}]}}
        ]
    }
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    assert t == "table"
    assert c == "<table>x</table>"


def test_gemini_structured_sends_response_schema():
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"candidates": [{"content": {"parts": [{"text": '{"type":"figure","content":"x"}'}]}}]})
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    gen_cfg = captured["body"]["generationConfig"]
    assert gen_cfg["response_mime_type"] == "application/json"
    schema = gen_cfg["response_schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"type", "content"}
    assert "type" in schema["required"] and "content" in schema["required"]


def test_gemini_structured_returns_none_on_parse_failure():
    fake_body = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(fake_body)):
        t, c = vb.transcribe_gemini_structured(
            b"FAKE", api_key="K", model="gemma-4-31b-it", timeout=10, prompt="hi",
        )
    assert t is None
    assert c == "not json"


def test_hash_thresholds_exists_at_shared_level():
    assert hasattr(vb, "hash_thresholds")
    h = vb.hash_thresholds({"a": 1, "b": 2})
    assert isinstance(h, str) and len(h) == 64


def test_hash_thresholds_is_key_order_invariant():
    assert vb.hash_thresholds({"a": 1, "b": 2}) == vb.hash_thresholds({"b": 2, "a": 1})
