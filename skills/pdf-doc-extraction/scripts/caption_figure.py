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
hash_thresholds = _vision_backends.hash_thresholds
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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_pdf_path(sidecar: dict, figures_json_path: Path) -> Path:
    """Resolve the source PDF path from sidecar metadata, assuming it sits
    alongside the figures.json."""
    source_file = sidecar.get("source_file") or ""
    return figures_json_path.parent / source_file


def check_sidecar_freshness(
    sidecar: dict,
    *,
    pdf_path: Path,
    current_thresholds_hash: str,
) -> str | None:
    """Return None if sidecar is fresh; else a human-readable diagnostic.

    Checks:
      - The source PDF exists at pdf_path
      - PDF sha256 matches sidecar.source_pdf_sha256
      - current_thresholds_hash matches sidecar.extractor_thresholds_hash

    A diagnostic is returned (not raised) so the caller can decide whether
    to refuse, warn, or proceed (--force / --accept-stale).
    """
    if not pdf_path.is_file():
        return f"source PDF missing at {pdf_path} (sidecar expects this file)"

    sidecar_sha = sidecar.get("source_pdf_sha256")
    if not isinstance(sidecar_sha, str) or len(sidecar_sha) != 64:
        return "sidecar missing valid source_pdf_sha256"
    current_sha = _sha256_file(pdf_path)
    if current_sha != sidecar_sha:
        return (
            f"PDF sha256 mismatch: sidecar={sidecar_sha[:12]}... "
            f"current={current_sha[:12]}... (re-run extract_figures.py)"
        )

    sidecar_thresh = sidecar.get("extractor_thresholds_hash")
    if sidecar_thresh != current_thresholds_hash:
        return (
            f"thresholds hash mismatch: sidecar={sidecar_thresh!r:.16}... "
            f"current={current_thresholds_hash[:12]}... (re-run extract_figures.py "
            f"with the new thresholds, or pass --accept-stale)"
        )
    return None


def _gemini_with_round_robin_structured(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> tuple[str | None, str, str]:
    """Round-robin gemini pairs in structured-output mode.

    Returns (type, content, used_model). Advances pairs on HTTP 429; on
    every-pair-exhausted raises RuntimeError. Local copy (not re-export)
    so patch.object(caption_figure, 'transcribe_gemini_structured')
    intercepts cleanly in tests.
    """
    last_429: Exception | None = None
    for api_key, model in pairs:
        try:
            t, c = transcribe_gemini_structured(
                image_png_bytes,
                api_key=api_key,
                model=model,
                timeout=timeout,
                prompt=prompt,
            )
            return t, c, model
        except urllib.error.HTTPError as e:
            if e.code == 429:
                last_429 = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs returned 429 ({len(pairs)} tried)"
    ) from last_429


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def caption_one_figure(
    figure_entry: dict,
    *,
    assets_root: Path,
    substance: str | None,
    engine: str,
    backend_kwargs: dict,
) -> dict:
    """Caption one figure. Returns a NEW dict (does not mutate input).

    For redacted figures: returns the entry unchanged (already pre-filled
    by write_figure_assets). No HTTP call.

    For real figures: reads the PNG, renders the prompt, calls the
    structured-output backend, populates description/content_type/
    captioner/prompt_hash/description_tier/error.

    Per-figure error containment (no exception escapes).
    """
    out = dict(figure_entry)
    if out.get("redacted"):
        return out

    asset_rel = out.get("asset_path")
    if not asset_rel:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = "missing asset_path on non-redacted figure"
        out["captioner"] = f"{engine}:skipped:no_asset"
        return out

    image_path = assets_root / asset_rel
    try:
        image_bytes = image_path.read_bytes()
    except OSError as e:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = f"could not read {image_path}: {e}"
        out["captioner"] = f"{engine}:skipped:read_error"
        return out

    prompt = render_prompt(
        substance=substance,
        nearby_text=out.get("nearby_text", "") or "",
        raw_caption_candidate=out.get("raw_caption_candidate", "") or "",
    )
    p_hash = compute_prompt_hash(prompt)
    out["prompt_hash"] = p_hash
    today = _utc_today()

    try:
        if engine == "lmstudio":
            model = backend_kwargs["model"]
            t, c = transcribe_lmstudio_structured(
                image_bytes,
                host=backend_kwargs["host"],
                model=model,
                timeout=backend_kwargs["timeout"],
                prompt=prompt,
            )
            used_model = model
        elif engine == "gemini":
            pairs = backend_kwargs["pairs"]
            t, c, used_model = _gemini_with_round_robin_structured(
                image_bytes,
                pairs=pairs,
                timeout=backend_kwargs["timeout"],
                prompt=prompt,
            )
        else:
            raise ValueError(f"unknown engine {engine!r}")
    except Exception as e:  # noqa: BLE001 - per-figure containment
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        out["error"] = f"{type(e).__name__}: {e}"
        out["captioner"] = f"{engine}:error"
        return out

    if t is None:
        out["content_type"] = "error"
        out["description"] = ""
        out["description_tier"] = None
        # Truncate raw text for the error string to keep JSON manageable
        preview = (c or "")[:200].replace("\n", " ")
        out["error"] = f"structured-output parse failed: {preview!r}"
        out["captioner"] = f"{engine}:parse_error"
        return out

    out["description"] = c
    out["content_type"] = t  # 'figure' or 'table'
    out["description_tier"] = 2
    out["captioner"] = f"{engine}:{used_model}@{today}"
    return out


def process_figures(
    figures: list[dict],
    *,
    assets_root: Path,
    substance: str | None,
    engine: str,
    backend_kwargs: dict,
    force: bool,
    rate_budget_calls: int | None,
) -> tuple[list[dict], dict]:
    """Caption every figure. Skip already-done unless force; honour budget cap.

    Stats:
      captioned        - successful new captions written this run
      skipped_done     - figures already had a description (and force=False)
      errored          - figures whose content_type became 'error' this run
      skipped_redacted - figures pre-filled with redaction marker (no call)
      budget_exhausted - True iff rate_budget_calls was hit
    """
    out: list[dict] = []
    stats = {
        "captioned": 0,
        "skipped_done": 0,
        "errored": 0,
        "skipped_redacted": 0,
        "budget_exhausted": False,
    }
    calls_made = 0
    for f in figures:
        if f.get("redacted"):
            out.append(dict(f))
            stats["skipped_redacted"] += 1
            continue
        already_done = (
            f.get("captioner") not in (None, "")
            and f.get("description") not in (None, "")
            and f.get("content_type") not in (None, "", "error")
        )
        if already_done and not force:
            out.append(dict(f))
            stats["skipped_done"] += 1
            continue
        if rate_budget_calls is not None and calls_made >= rate_budget_calls:
            # Budget hit. Pass through remaining figures unchanged.
            out.append(dict(f))
            stats["budget_exhausted"] = True
            continue
        new_entry = caption_one_figure(
            f,
            assets_root=assets_root,
            substance=substance,
            engine=engine,
            backend_kwargs=backend_kwargs,
        )
        calls_made += 1
        out.append(new_entry)
        if new_entry.get("content_type") == "error":
            stats["errored"] += 1
        else:
            stats["captioned"] += 1
    return out, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Caption extracted figures via a vision model (Phase 3b).",
    )
    parser.add_argument("--figures-json", type=Path, required=True)
    parser.add_argument("--substance", default=None,
                        help="Override; otherwise uses sidecar substance field.")
    parser.add_argument("--engine", default="gemini", choices=["gemini", "lmstudio"])
    parser.add_argument("--model", default=None,
                        help="LMStudio model name (default: gemma-4-e4b-it). "
                             "Ignored with --engine gemini.")
    parser.add_argument("--host", default="http://localhost:1234")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--api-key", action="append", default=None,
                        help="Gemini API key. Repeatable. Falls back to "
                             "GEMINI_API_KEY/GOOGLE_API_KEY env var.")
    parser.add_argument("--gemini-models",
                        default="gemma-4-31b-it,gemma-4-26b-a4b-it",
                        help="Comma-separated Gemini models for round-robin")
    parser.add_argument("--force", action="store_true",
                        help="Re-caption already-done figures; bypass freshness check")
    parser.add_argument("--accept-stale", action="store_true",
                        help="Proceed against a stale sidecar (warns instead of refusing)")
    parser.add_argument("--check-stale", action="store_true",
                        help="Print freshness diagnostic and exit 0; no HTTP")
    parser.add_argument("--rate-budget-calls", type=int, default=None,
                        help="Hard stop after N successful backend calls")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # 1. Load sidecar
    payload = json.loads(args.figures_json.read_text(encoding="utf-8"))
    pdf_path = _resolve_pdf_path(payload, args.figures_json)
    # Recompute the thresholds hash from the dict in the sidecar.
    # This catches tampered or corrupted sidecars where extractor_thresholds_hash
    # was hand-edited or where the dict was modified without updating the hash.
    thresholds_dict = payload.get("extractor_thresholds", {})
    current_thresholds_hash = hash_thresholds(thresholds_dict) if thresholds_dict else ""

    # 2. Freshness check (always run; --check-stale short-circuits, --force
    #    and --accept-stale only relax the refusal).
    freshness_diag = check_sidecar_freshness(
        payload,
        pdf_path=pdf_path,
        current_thresholds_hash=current_thresholds_hash,
    )

    if args.check_stale:
        if freshness_diag:
            print(json.dumps({
                "figures_json": str(args.figures_json),
                "status": "stale",
                "diagnostic": freshness_diag,
            }, indent=2))
        else:
            print(json.dumps({
                "figures_json": str(args.figures_json),
                "status": "fresh",
            }, indent=2))
        return 0

    if freshness_diag and not (args.force or args.accept_stale):
        print(f"error: sidecar is stale: {freshness_diag}", file=sys.stderr)
        print("       pass --accept-stale to proceed, or re-run extract_figures.py "
              "and try again.", file=sys.stderr)
        return 3

    if freshness_diag and (args.force or args.accept_stale) and not args.quiet:
        print(f"WARNING: sidecar is stale ({freshness_diag}); proceeding due to flag",
              file=sys.stderr)

    # 3. Resolve backend kwargs + denylist check
    if args.engine == "lmstudio":
        model = args.model or "gemma-4-e4b-it"
        err = validate_captioning_model("lmstudio", model)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        backend_kwargs = {"host": args.host, "model": model, "timeout": args.timeout}
    else:  # gemini
        keys = list(args.api_key or [])
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not keys and env_key:
            keys = [env_key]
        if not keys:
            print("error: --engine gemini requires --api-key or "
                  "GEMINI_API_KEY/GOOGLE_API_KEY env var", file=sys.stderr)
            return 2
        models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]
        if not models:
            print("error: --gemini-models is empty after parsing", file=sys.stderr)
            return 2
        pairs = [(k, m) for k in keys for m in models]
        backend_kwargs = {"pairs": pairs, "timeout": args.timeout}

    # 4. Process
    substance = args.substance or payload.get("substance")
    assets_root = args.figures_json.parent

    t0 = time.monotonic()
    new_figures, stats = process_figures(
        payload.get("figures", []),
        assets_root=assets_root,
        substance=substance,
        engine=args.engine,
        backend_kwargs=backend_kwargs,
        force=args.force,
        rate_budget_calls=args.rate_budget_calls,
    )
    duration = round(time.monotonic() - t0, 3)

    # 5. Atomic write
    payload["figures"] = new_figures
    payload["captioning_date"] = _utc_now_iso()
    payload["captioning_engine"] = args.engine
    payload["captioning_seconds"] = duration
    payload["budget_exhausted"] = stats["budget_exhausted"]
    atomic_write_json(args.figures_json, payload)

    if not args.quiet:
        print(json.dumps({
            "figures_json": str(args.figures_json),
            "engine": args.engine,
            **stats,
            "total_seconds": duration,
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
