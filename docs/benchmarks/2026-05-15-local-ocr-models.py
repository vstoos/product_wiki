"""One-shot OCR benchmark: 3 local LMStudio OCR models on the same 10 pages.

Iterates through `glm-ocr`, `lightonocr-2-1b-ocr-soup`, `deepseek-ocr` by
unloading the current model + loading the next via `lms` CLI between rounds
(VRAM is constrained to ~6 GB). Writes per-model results to a single JSON
sidecar for side-by-side comparison.

Reads .env directly (without exposing key values).

Usage:
    python benchmark_ocr.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent

# Load .env into os.environ
ENV_FILE = REPO / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))

# Normalize: prefer GOOGLE_API_KEY (Google's official name), fall back to GEMINI_API_KEY
GOOGLE_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
GEMINI_MODELS = [
    os.environ.get(f"GEMINI_MODEL{suffix}")
    for suffix in ["", "_2", "_3", "_4"]
]
GEMINI_MODELS = [m for m in GEMINI_MODELS if m]

print(f"Gemini key present: {bool(GOOGLE_KEY)} (length {len(GOOGLE_KEY) if GOOGLE_KEY else 0})")
print(f"Gemini models configured: {GEMINI_MODELS}")

# Load _vision_backends from scripts/
BACKENDS_PATH = REPO / "skills" / "pdf-doc-extraction" / "scripts" / "_vision_backends.py"
spec = importlib.util.spec_from_file_location("_vision_backends", BACKENDS_PATH)
vb = importlib.util.module_from_spec(spec)
sys.modules["_vision_backends"] = vb
spec.loader.exec_module(vb)

# Load ocr_page for render_page_png
OCR_PATH = REPO / "skills" / "pdf-doc-extraction" / "scripts" / "ocr_page.py"
spec2 = importlib.util.spec_from_file_location("ocr_page", OCR_PATH)
ocr = importlib.util.module_from_spec(spec2)
sys.modules["ocr_page"] = ocr
spec2.loader.exec_module(ocr)

# 15 benchmark pages spanning 4 document types
PAGES: list[tuple[str, int, str]] = [
    # (pdf_path, page_number, content_type)
    # ChemR: scanned regulatory filing forms (low-contrast checkbox tables)
    ("apalutamide/FDA/210951Orig1s000ChemR.pdf", 47, "scanned-form"),
    ("apalutamide/FDA/210951Orig1s000ChemR.pdf", 48, "scanned-form"),
    ("apalutamide/FDA/210951Orig1s000ChemR.pdf", 49, "scanned-form"),
    ("apalutamide/FDA/210951Orig1s000ChemR.pdf", 50, "scanned-form"),
    ("apalutamide/FDA/210951Orig1s000ChemR.pdf", 51, "signature-block"),
    # SUPPL_011 label: dense prescribing-information prose + drug-interaction tables
    ("apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf", 1, "label-highlights"),
    ("apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf", 5, "label-prose"),
    ("apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf", 10, "label-table"),
    ("apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf", 20, "label-prose"),
    ("apalutamide/FDA/SUPPL_011_210951Orig1s011lbl.pdf", 30, "label-prose"),
    # MultidisciplineR: 259-page clinical review with tables, figures, study results
    ("apalutamide/FDA/210951Orig1s000MultidisciplineR.pdf", 50, "clinical-review"),
    ("apalutamide/FDA/210951Orig1s000MultidisciplineR.pdf", 100, "clinical-review"),
    ("apalutamide/FDA/210951Orig1s000MultidisciplineR.pdf", 200, "clinical-review"),
    # DailyMed label: alternative label format (NLM source, not FDA review)
    ("apalutamide/FDA/DailyMed_label_d1cda4f7-cb33-46ea-b9ac-431f6452b1a5.pdf", 1, "dailymed-label"),
    # SUPPL_009: small supplement letter
    ("apalutamide/FDA/SUPPL_009_210951.pdf", 1, "supplement-letter"),
]


def lmstudio_call(image_bytes: bytes, model: str) -> tuple[str, float, str | None]:
    """Returns (text, duration_sec, error_message_or_None)."""
    t0 = time.monotonic()
    try:
        text = vb.transcribe_lmstudio(
            image_bytes,
            host="http://localhost:1234",
            model=model,
            timeout=180,
            prompt="",  # all 3 are OCR-specialized: no prompt
        )
        return text, time.monotonic() - t0, None
    except Exception as e:
        return "", time.monotonic() - t0, f"{type(e).__name__}: {e}"


def swap_model(model: str) -> bool:
    """Unload everything then load `model`. Returns True on success."""
    import subprocess
    print(f"  [VRAM] unload all + load {model}...", flush=True)
    subprocess.run(["lms", "unload", "-a"], check=False)
    r = subprocess.run(
        ["lms", "load", model, "--gpu", "max", "--ttl", "1800", "-y"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  [VRAM] load failed: {r.stderr.strip()[:200]}", flush=True)
        return False
    return True


def gemini_call(image_bytes: bytes, model: str) -> tuple[str, float, str | None]:
    """Returns (text, duration_sec, error_message_or_None)."""
    if not GOOGLE_KEY:
        return "", 0.0, "no GOOGLE_API_KEY"
    t0 = time.monotonic()
    try:
        text = vb.transcribe_gemini(
            image_bytes,
            api_key=GOOGLE_KEY,
            model=model,
            timeout=180,
            prompt=vb.OCR_PROMPT,  # general vision: include prompt
        )
        return text, time.monotonic() - t0, None
    except Exception as e:
        return "", time.monotonic() - t0, f"{type(e).__name__}: {e}"


def main() -> int:
    # Three local OCR-specialized models on disk per the user's library.
    LOCAL_OCR_MODELS = [
        "glm-ocr",                    # ~891M, Q8_0, 1.43 GB
        "lightonocr-2-1b-ocr-soup",   # 1B, BF16, 2.84 GB
        "deepseek-ocr",               # 64x550M MoE, Q8_0, 3.57 GB
    ]
    print(f"Models to benchmark: {LOCAL_OCR_MODELS}")
    print()

    # Pre-render all pages once (reusable across models)
    rendered: list[tuple[str, int, str, bytes]] = []
    for pdf_path, page_num, content_type in PAGES:
        full = REPO / pdf_path
        if not full.exists():
            print(f"SKIP (missing): {pdf_path}:{page_num}")
            continue
        png = ocr.render_page_png(full, page_number=page_num, dpi=200)
        rendered.append((pdf_path, page_num, content_type, png))
    print(f"Rendered {len(rendered)} pages.\n")

    # results[page_index][model] = {text, duration_sec, error, char_count}
    results: list[dict] = [
        {
            "pdf": p,
            "page": pn,
            "content_type": ct,
            "by_model": {},
        }
        for (p, pn, ct, _) in rendered
    ]

    for model in LOCAL_OCR_MODELS:
        print(f"========== Model: {model} ==========")
        if not swap_model(model):
            print(f"  SKIP - cannot load {model}")
            for r in results:
                r["by_model"][model] = {
                    "char_count": 0, "duration_sec": 0.0,
                    "error": "model load failed",
                }
            continue
        # Warm-up first call (LM Studio kv-cache prep) — discount its timing
        print("  warming up...", flush=True)
        _ = lmstudio_call(rendered[0][3], model=model)

        for i, (pdf_path, page_num, content_type, png) in enumerate(rendered):
            print(f"  p{page_num} ({content_type})...", end=" ", flush=True)
            text, dur, err = lmstudio_call(png, model=model)
            results[i]["by_model"][model] = {
                "text": text,
                "char_count": len(text),
                "duration_sec": round(dur, 2),
                "error": err,
            }
            print(f"{dur:.1f}s, {len(text)} chars" if not err else f"ERR: {err}", flush=True)

    # Aggregate
    print()
    print("=" * 80)
    print("Aggregate")
    print("=" * 80)
    print(f"{'model':<32} {'ok/total':>8} {'tot s':>7} {'avg s/pg':>9} {'tot chars':>10} {'avg chars/pg':>13}")
    print("-" * 90)
    for model in LOCAL_OCR_MODELS:
        ok = [r for r in results if not r["by_model"].get(model, {}).get("error")]
        if not ok:
            print(f"{model:<32} 0/{len(results):<8}")
            continue
        total_t = sum(r["by_model"][model]["duration_sec"] for r in ok)
        total_c = sum(r["by_model"][model]["char_count"] for r in ok)
        n = len(ok)
        print(f"{model:<32} {n:>3}/{len(results):<5} {total_t:>7.1f} {total_t/n:>9.1f} {total_c:>10,} {total_c//n:>13,}")

    # Per-page breakdown
    print()
    print("Per-page char counts (model-by-model):")
    print(f"{'page':<55}", end="")
    for m in LOCAL_OCR_MODELS:
        print(f"{m[:18]:>20}", end="")
    print()
    for r in results:
        label = f"{r['pdf'].split('/')[-1][:30]}:{r['page']} ({r['content_type']})"
        print(f"{label:<55}", end="")
        for m in LOCAL_OCR_MODELS:
            entry = r["by_model"].get(m, {})
            if entry.get("error"):
                print(f"{'ERR':>20}", end="")
            else:
                print(f"{entry.get('char_count', 0):>20}", end="")
        print()

    out_path = REPO / "benchmark_ocr_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"Full results -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
