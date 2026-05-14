"""Tests for ocr_page.py. HTTP is mocked; no live model calls."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ocr_page.py"


def _load_ocr_page():
    spec = importlib.util.spec_from_file_location("ocr_page", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ocr_page"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_page_spec_basic():
    ocr_page = _load_ocr_page()
    assert ocr_page.parse_page_spec("3,5,7-9") == [3, 5, 7, 8, 9]


def test_parse_page_spec_dedupes_and_sorts():
    ocr_page = _load_ocr_page()
    assert ocr_page.parse_page_spec("5,1,3-5") == [1, 3, 4, 5]


def test_parse_page_spec_rejects_invalid():
    ocr_page = _load_ocr_page()
    with pytest.raises(ValueError):
        ocr_page.parse_page_spec("3,abc")
