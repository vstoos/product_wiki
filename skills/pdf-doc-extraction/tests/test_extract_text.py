"""Tests for extract_text.py — PyMuPDF text extraction tool."""
from pathlib import Path
import json
import sys

import pytest

# Make scripts/ importable
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_text  # noqa: E402


def test_extract_returns_per_page_text(chemr_pdf):
    """extract() returns a dict with per-page text and metadata."""
    result = extract_text.extract(chemr_pdf)
    assert "pages" in result
    assert "metadata" in result
    assert isinstance(result["pages"], list)
    assert len(result["pages"]) == 51  # ChemR has 51 pages
    assert all(isinstance(p, dict) and "text" in p for p in result["pages"])
