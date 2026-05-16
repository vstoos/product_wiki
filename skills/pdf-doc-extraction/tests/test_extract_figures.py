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
