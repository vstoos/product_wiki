"""Caption extracted figures via a vision model (Phase 3b).

Reads <stem>.figures.json (produced by extract_figures.py), verifies
freshness via source_pdf_sha256 + extractor_thresholds_hash, sends each
non-redacted figure PNG to a vision backend in structured-output mode
({type, content}), and atomically writes descriptions + provenance back.

Usage:
  python caption_figure.py --figures-json <stem>.figures.json
"""
from __future__ import annotations

# Re-export from shared backends (same pattern as ocr_page.py).
import importlib.util as _ilu
from pathlib import Path as _Path
import sys as _sys

_vb_path = _Path(__file__).resolve().parent / "_vision_backends.py"
_vb_spec = _ilu.spec_from_file_location("_vision_backends", _vb_path)
_vision_backends = _ilu.module_from_spec(_vb_spec)
_sys.modules["_vision_backends"] = _vision_backends
_vb_spec.loader.exec_module(_vision_backends)

CAPTION_PROMPT_TEMPLATE = _vision_backends.CAPTION_PROMPT_TEMPLATE
CAPTION_DENYLIST = _vision_backends.CAPTION_DENYLIST
atomic_write_json = _vision_backends.atomic_write_json
transcribe_lmstudio_structured = _vision_backends.transcribe_lmstudio_structured
transcribe_gemini_structured = _vision_backends.transcribe_gemini_structured

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def render_prompt(
    *,
    substance: str | None,
    nearby_text: str,
    raw_caption_candidate: str,
) -> str:
    """Substitute into CAPTION_PROMPT_TEMPLATE; drop empty Context bullets.

    The template has three "Context:" bullets. Any bullet whose value is
    empty/None is removed entirely (line + newline) so the prompt does not
    show "Substance: None" or hanging colons.
    """
    out = CAPTION_PROMPT_TEMPLATE.format(
        substance=substance or "",
        nearby_text=nearby_text or "",
        raw_caption_candidate=raw_caption_candidate or "",
    )
    drop_patterns = [
        r"^- Substance:\s*$\n",
        r"^- Nearby text from the surrounding document:\s*$\n",
        r"^- Caption candidate \(if found\):\s*$\n",
    ]
    for pat in drop_patterns:
        out = re.sub(pat, "", out, flags=re.MULTILINE)
    return out


def compute_prompt_hash(rendered_prompt: str) -> str:
    """First 16 hex chars of sha256(rendered_prompt). Audit-trail identifier."""
    return hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()[:16]


def validate_captioning_model(engine: str, model: str) -> str | None:
    """Return error string if engine=lmstudio + model in CAPTION_DENYLIST; else None.

    Gemini side doesn't serve those models so the check is engine-conditional.
    """
    if engine == "lmstudio" and model in CAPTION_DENYLIST:
        return (
            f"refusing to use OCR-specialized model {model!r} for captioning "
            f"(in CAPTION_DENYLIST). Use a general vision model like "
            f"'gemma-4-e2b-it' or 'gemma-4-e4b-it' for LMStudio, or "
            f"'gemma-4-31b-it' for the default Gemini path."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    """Implemented in Task 14."""
    raise NotImplementedError("main() implemented in Task 14")


if __name__ == "__main__":
    sys.exit(main())
