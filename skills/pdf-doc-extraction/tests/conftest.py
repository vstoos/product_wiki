"""Shared fixtures. The apalutamide/ data is gitignored but local."""
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
APALUTAMIDE_FDA = REPO_ROOT / "apalutamide" / "FDA"


@pytest.fixture(scope="session")
def chemr_pdf() -> Path:
    """Small-but-real fixture: 6.4 MB FDA Chemistry Review PDF."""
    p = APALUTAMIDE_FDA / "210951Orig1s000ChemR.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p


@pytest.fixture(scope="session")
def suppl11_pdf() -> Path:
    """Smoke target: 2.8 MB previously-unextracted FDA supplement label."""
    p = APALUTAMIDE_FDA / "SUPPL_011_210951Orig1s011lbl.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p


@pytest.fixture(scope="session")
def multidisc_pdf() -> Path:
    """Figure-rich corpus: 259-page FDA clinical review with PK/KM plots."""
    p = APALUTAMIDE_FDA / "210951Orig1s000MultidisciplineR.pdf"
    if not p.exists():
        pytest.skip(f"test fixture missing: {p}")
    return p
