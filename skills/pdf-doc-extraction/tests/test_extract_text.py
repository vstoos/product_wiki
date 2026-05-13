"""Tests for extract_text.py — PyMuPDF text extraction tool."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load the module from an explicit path to avoid sys.path collisions
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_extract_text_path = SCRIPTS / "extract_text.py"
_spec = importlib.util.spec_from_file_location("extract_text", _extract_text_path)
if _spec is None or _spec.loader is None:
    raise ModuleNotFoundError(
        f"Cannot find scripts/extract_text.py at {_extract_text_path}. "
        "Task 3 must create it before these tests can pass."
    )
extract_text = importlib.util.module_from_spec(_spec)
sys.modules["extract_text"] = extract_text  # required for dataclass module lookup
_spec.loader.exec_module(extract_text)


def test_extract_returns_per_page_text(chemr_pdf):
    """extract() returns a dict with per-page text and metadata."""
    result = extract_text.extract(chemr_pdf)
    assert "pages" in result
    assert "metadata" in result
    assert isinstance(result["pages"], list)
    assert len(result["pages"]) == 51  # ChemR has 51 pages
    assert all(isinstance(p, dict) and "text" in p for p in result["pages"])
