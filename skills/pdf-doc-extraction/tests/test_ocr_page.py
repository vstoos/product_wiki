"""Tests for ocr_page.py. HTTP is mocked; no live model calls."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the module from an explicit path to avoid sys.path collisions
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_ocr_page_path = SCRIPTS / "ocr_page.py"
_spec = importlib.util.spec_from_file_location("ocr_page", _ocr_page_path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/ocr_page.py at {_ocr_page_path}. "
        "Task 1 must create it before these tests can pass."
    )
ocr_page = importlib.util.module_from_spec(_spec)
sys.modules["ocr_page"] = ocr_page  # required for dataclass module lookup
_spec.loader.exec_module(ocr_page)


def test_parse_page_spec_basic():
    assert ocr_page.parse_page_spec("3,5,7-9") == [3, 5, 7, 8, 9]


def test_parse_page_spec_dedupes_and_sorts():
    assert ocr_page.parse_page_spec("5,1,3-5") == [1, 3, 4, 5]


def test_parse_page_spec_rejects_invalid():
    with pytest.raises(ValueError):
        ocr_page.parse_page_spec("3,abc")


def test_select_pages_prefers_explicit_pages():
    result = ocr_page.select_pages(pages_spec="3,5", extract_metadata={"problem_pages": [10, 20]})
    assert result == [3, 5]


def test_select_pages_falls_back_to_extract_metadata():
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": [10, 20]})
    assert result == [10, 20]


def test_select_pages_requires_one_source():
    with pytest.raises(ValueError):
        ocr_page.select_pages(pages_spec=None, extract_metadata=None)


def test_select_pages_empty_problem_pages_returns_empty():
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": []})
    assert result == []


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_page_png_returns_png_bytes(suppl11_pdf):
    data = ocr_page.render_page_png(suppl11_pdf, page_number=1, dpi=150)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 1000


def test_render_page_png_invalid_page_raises(suppl11_pdf):
    with pytest.raises((IndexError, ValueError)):
        ocr_page.render_page_png(suppl11_pdf, page_number=9999, dpi=150)


import json as _json
from unittest.mock import patch


class _MockResponse:
    """Minimal context-manager response for urlopen."""

    def __init__(self, body_dict, status: int = 200):
        self._body = _json.dumps(body_dict).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_transcribe_lmstudio_sends_vision_payload():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _MockResponse({"choices": [{"message": {"content": "TRANSCRIBED"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG\r\n\x1a\nFAKEBYTES",
            host="http://localhost:1234",
            model="glm-ocr",
            timeout=60,
        )
    assert result == "TRANSCRIBED"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["timeout"] == 60
    body = captured["body"]
    assert body["model"] == "glm-ocr"
    assert body["temperature"] == 0.0
    content = body["messages"][0]["content"]
    types = [item["type"] for item in content]
    assert "text" in types and "image_url" in types
    img_item = next(c for c in content if c["type"] == "image_url")
    assert img_item["image_url"]["url"].startswith("data:image/png;base64,")


def test_transcribe_lmstudio_strips_trailing_whitespace():
    body = {"choices": [{"message": {"content": "  hello world  \n"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
        )
    assert result == "hello world"


def test_transcribe_lmstudio_propagates_http_error():
    import urllib.error
    err = urllib.error.HTTPError(
        url="x", code=503, msg="unavailable", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            ocr_page.transcribe_lmstudio(
                b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
            )
