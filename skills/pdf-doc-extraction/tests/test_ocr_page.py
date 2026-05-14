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
