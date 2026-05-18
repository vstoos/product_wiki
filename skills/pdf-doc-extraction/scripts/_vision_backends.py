"""Shared vision backends for ocr_page and caption_figure.

Contains the prompt constants and HTTP transcription helpers that are
reused by multiple CLI tools in this skill. Kept as an internal module
(leading underscore) because it is not a standalone CLI tool.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request


def _compute_hard_timeout(timeout: int) -> int:
    """Hard wall-clock timeout = max(timeout + 60, ceil(timeout * 1.5)).

    The socket-level urllib timeout SHOULD catch hangs on its own, but in
    practice (Windows + idle keep-alive HTTPS to Google) it doesn't always
    fire — the call has been observed to block for hours past the requested
    timeout. The hard wall-clock cap above guarantees the call returns in
    finite time even if urllib's internal timeout doesn't trigger.
    """
    return max(timeout + 60, int(timeout * 1.5) + 1)


def _with_hard_timeout(fn, *, hard_timeout: int, url_for_error: str = ""):
    """Run `fn()` in a daemon thread; raise HTTPError(504) if it hangs.

    The wrapped call runs in a daemon thread so the main thread can wait
    on it with a finite deadline. On deadline overrun, we raise a synthetic
    urllib.error.HTTPError with code 504 (Gateway Timeout), which the
    round-robin retry layer treats as a transient failure and advances to
    the next (api_key, model) pair.

    The orphan thread is left to finish on its own — the underlying socket
    eventually closes (OS keep-alive or remote FIN) or the process exits.
    Daemon threads do not prevent process exit.
    """
    box: dict = {"value": None, "exc": None, "done": False}

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - we re-raise on the main thread
            box["exc"] = e
        finally:
            box["done"] = True

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(hard_timeout)
    if not box["done"]:
        raise urllib.error.HTTPError(
            url=url_for_error,
            code=504,
            msg=f"hard wall-clock timeout after {hard_timeout}s "
                f"(urllib socket timeout did not fire)",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
    if box["exc"] is not None:
        raise box["exc"]
    return box["value"]


OCR_MODEL_PATTERN = re.compile(r"ocr", re.IGNORECASE)

OCR_PROMPT = (
    "Transcribe all readable text from this document page image.\n"
    "\n"
    "Rules:\n"
    "- Preserve line breaks where they appear meaningful (between paragraphs).\n"
    "- Preserve tables: HTML <table> if complex (rowspans, nested headers); "
    "GFM pipe table if simple.\n"
    "- Preserve special characters literally (degree-sign, mu, plus-minus, "
    "less-equal, greater-equal, en-dash, em-dash, right-arrow, "
    "checkbox-checked, checkbox-empty). Do not convert these to words or booleans.\n"
    "- Preserve redaction markers: (b)(4) stays as (b)(4).\n"
    "- Do not add commentary, headers, or section labels you cannot see.\n"
    "- If the page is blank or unreadable, output exactly: [BLANK PAGE]\n"
)

CAPTION_PROMPT_TEMPLATE = (
    "You will receive a figure image from a regulatory document. Output a JSON\n"
    "object with exactly two fields:\n"
    "  - \"type\": one of \"figure\" or \"table\"\n"
    "  - \"content\": see rules below\n"
    "\n"
    "Context:\n"
    "- Substance: {substance}\n"
    "- Nearby text from the surrounding document: {nearby_text}\n"
    "- Caption candidate (if found): {raw_caption_candidate}\n"
    "\n"
    "Rules for type=\"table\":\n"
    "- Use this type if the image is a scanned table (rows and columns of cell\n"
    "  data with headers, and no plotting elements).\n"
    "- \"content\" is an HTML <table> transcription using rowspan/colspan for\n"
    "  merged cells. Preserve cell text verbatim. No surrounding prose.\n"
    "\n"
    "Rules for type=\"figure\":\n"
    "- Use this type for plots, charts, schematics, photographs, micrographs.\n"
    "- \"content\" is a 3-5 sentence description.\n"
    "- State the figure type (PK plot, dissolution profile, Kaplan-Meier curve,\n"
    "  forest plot, scatter plot, schematic, photograph, etc.) in sentence 1.\n"
    "- State axis labels and units if visible.\n"
    "- Values policy:\n"
    "   * Discrete labeled data points (dissolution % at named timepoints,\n"
    "     mean +/- SD bars with annotated values, table-like overlays):\n"
    "     transcribe the values literally.\n"
    "   * Continuous curves (Kaplan-Meier survival, scatter, dose-response,\n"
    "     concentration-time profiles without per-point labels): describe\n"
    "     shape and inflection points; do NOT interpolate specific values.\n"
    "- Always describe trends and relationships visible in the data.\n"
    "- Be consistent with the caption candidate if one is provided.\n"
    "- Never invent. If the image is unreadable, set content to \"[UNREADABLE]\".\n"
    "\n"
    "Output: a single JSON object, no surrounding prose, no markdown fences.\n"
)


# Captioning-model denylist. Lowercased substring patterns, NOT a generic
# /ocr/i regex (which would falsely reject a future general vision model
# named e.g. "vision-ocr-1"). Substring (not exact-set) so the same patterns
# match both LM Studio short ids (`lightonocr-2-1b-ocr-soup`) and llama.cpp
# filenames (`LightOnOCR-2-1B-ocr-soup-BF16.gguf`). Check via
# `is_caption_denied(model_id)`.
CAPTION_DENYLIST = frozenset({
    "glm-ocr",
    "lightonocr",
    "deepseek-ocr",
})


def is_caption_denied(model_id: str) -> str | None:
    """Return the matching pattern if `model_id` is OCR-specialised, else None.

    Case-insensitive substring match against CAPTION_DENYLIST. Used by
    caption_figure.validate_captioning_model.
    """
    lowered = (model_id or "").lower()
    for pattern in CAPTION_DENYLIST:
        if pattern in lowered:
            return pattern
    return None

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"


def transcribe_llama_cpp(
    image_png_bytes: bytes,
    *,
    host: str,
    model: str,
    timeout: int,
    prompt: str = OCR_PROMPT,
) -> str:
    """POST the image to a local llama.cpp OpenAI-compatible vision endpoint.

    Returns the model's response content, stripped of leading/trailing whitespace.
    Raises on HTTP errors, network errors, and malformed responses.

    One image per request: no conversation context is carried between pages.
    If `prompt` is empty, the request is image-only (no text content item) -
    appropriate for OCR-specialized models that are confused by instructions.
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    content: list[dict] = []
    if prompt:
        content.append({"type": "text", "text": prompt})
    content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}"},
    })
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
        # 16384 leaves headroom for OCR-specialized models that internally emit
        # thinking tokens before the visible transcription. 4096 was hit on long
        # pages and silently truncated mid-sentence.
        "max_tokens": 16384,
    }
    url = f"{host.rstrip('/')}/v1/chat/completions"
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _do() -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    body = _with_hard_timeout(
        _do,
        hard_timeout=_compute_hard_timeout(timeout),
        url_for_error=url,
    )
    return body["choices"][0]["message"]["content"].strip()


def transcribe_gemini(
    image_png_bytes: bytes,
    *,
    api_key: str,
    model: str,
    timeout: int,
    prompt: str = OCR_PROMPT,
) -> str:
    """POST the image to Gemini's generateContent endpoint. Returns text.

    One image per request. If `prompt` is empty, the request is image-only.
    Raises HTTPError on non-2xx responses (caller handles 429 routing).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    parts: list[dict] = []
    if prompt:
        parts.append({"text": prompt})
    parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192},
    }
    url = GEMINI_ENDPOINT.format(model=model, api_key=api_key)
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _do() -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    body = _with_hard_timeout(
        _do,
        hard_timeout=_compute_hard_timeout(timeout),
        url_for_error=url,
    )
    out_parts = body["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in out_parts if "text" in p)
    return text.strip()


import re as _re

_JSON_FENCE_RE = _re.compile(r"^```(?:json)?\s*(.*?)\s*```\s*$", _re.DOTALL | _re.IGNORECASE)


def _parse_structured_response(raw_text: str) -> tuple[str | None, str]:
    """Parse a model's text into (type, content) or (None, raw_text) on failure.

    Strips ```json ... ``` fences (common small-model failure mode), then
    json.loads. Validates {type, content} shape and that type is in
    {"figure", "table"}. On any failure returns (None, raw_text).
    """
    text = raw_text.strip()
    m = _JSON_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, raw_text
    if not isinstance(obj, dict):
        return None, raw_text
    t = obj.get("type")
    c = obj.get("content")
    if t not in ("figure", "table") or not isinstance(c, str):
        return None, raw_text
    return t, c


def transcribe_llama_cpp_structured(
    image_png_bytes: bytes,
    *,
    host: str,
    model: str,
    timeout: int,
    prompt: str,
) -> tuple[str | None, str]:
    """Structured-output captioning via llama.cpp (OpenAI-compat JSON mode).

    Returns (type, content) on a parseable {type, content} response, else
    (None, raw_text). llama.cpp's OpenAI-compat layer supports
    response_format={"type":"json_object"} but not arbitrary JSON Schema
    enforcement, so the schema is also stated in the prompt (which is what
    `prompt` already contains via CAPTION_PROMPT_TEMPLATE).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
        # 8192 is generous for a {type, content} caption (3-5 sentences or a
        # bounded HTML table) while keeping the cap small enough to fail-fast
        # on misconfigured servers that spill weights to shared memory and
        # generate at 1 tok/min.
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    url = f"{host.rstrip('/')}/v1/chat/completions"
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _do() -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    body = _with_hard_timeout(
        _do,
        hard_timeout=_compute_hard_timeout(timeout),
        url_for_error=url,
    )
    raw_text = body["choices"][0]["message"]["content"]
    return _parse_structured_response(raw_text)


def transcribe_gemini_structured(
    image_png_bytes: bytes,
    *,
    api_key: str,
    model: str,
    timeout: int,
    prompt: str,
) -> tuple[str | None, str]:
    """Structured-output captioning via Gemini (response_schema enforced).

    Returns (type, content) on parse success, else (None, raw_text).
    Raises urllib HTTPError on non-2xx (caller handles 429 routing).
    """
    b64 = base64.b64encode(image_png_bytes).decode("ascii")
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png", "data": b64}},
    ]
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 8192,
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["figure", "table"]},
                    "content": {"type": "string"},
                },
                "required": ["type", "content"],
            },
        },
    }
    url = GEMINI_ENDPOINT.format(model=model, api_key=api_key)
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _do() -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    body = _with_hard_timeout(
        _do,
        hard_timeout=_compute_hard_timeout(timeout),
        url_for_error=url,
    )
    out_parts = body["candidates"][0]["content"]["parts"]
    raw_text = "".join(p.get("text", "") for p in out_parts if "text" in p)
    return _parse_structured_response(raw_text)


def _gemini_with_round_robin(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> str:
    """Try each (api_key, model) pair in order. Retry on transient failures.

    Advances to the next pair on HTTP 429 (rate limit) and HTTP 5xx
    (transient server error or hard-timeout 504 emitted by the wall-clock
    guard in transcribe_gemini). Non-transient HTTPErrors propagate.
    Raises RuntimeError if every pair is exhausted, carrying the last error.

    Local copies of this function exist in ocr_page.py and caption_figure.py
    so that tests can patch.object cleanly without touching this module;
    this version is the canonical reference implementation.
    """
    last_err: Exception | None = None
    for api_key, model in pairs:
        try:
            return transcribe_gemini(
                image_png_bytes,
                api_key=api_key,
                model=model,
                timeout=timeout,
                prompt=prompt,
            )
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                last_err = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs exhausted ({len(pairs)} tried); last={last_err}"
    ) from last_err


def resolve_prompt(*, user_prompt: str | None, model: str) -> tuple[str, str]:
    """Decide which prompt to send and label its source.

    Returns (prompt, mode) where mode is one of:
      - 'user'         : --prompt was given (including empty string)
      - 'auto-empty'   : model name matches OCR_MODEL_PATTERN -> no instruction
      - 'auto-default' : general vision model -> use OCR_PROMPT
    """
    if user_prompt is not None:
        return user_prompt, "user"
    if OCR_MODEL_PATTERN.search(model):
        return "", "auto-empty"
    return OCR_PROMPT, "auto-default"


def check_model_loaded(*, host: str, model: str, timeout: int = 5) -> str | None:
    """Query <host>/v1/models. Return None if model is loaded, else a warning string.

    Network/HTTP errors yield a warning rather than raising - per-page errors
    in process_pages give the user the real diagnostic.
    """
    try:
        with urllib.request.urlopen(
            f"{host.rstrip('/')}/v1/models", timeout=timeout
        ) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        return f"could not query {host}/v1/models ({type(e).__name__}: {e}) - is llama-server running on {host}?"
    loaded_ids = [m.get("id") for m in body.get("data", [])]
    if model in loaded_ids:
        return None
    return (
        f"model {model!r} is not loaded; loaded: {loaded_ids}. "
        f"Restart llama-server with --model pointing at the right GGUF (one server at a time)."
    )


def atomic_write_json(path, payload) -> None:
    """Write JSON to `path` atomically via a sibling tmp file + os.replace.

    Crash mid-write leaves the canonical file unchanged. Raises OSError on
    write/replace failure; in that case the caller should NOT assume the
    canonical content was updated.

    Path may be str or pathlib.Path. Payload is anything json.dumps can encode.
    """
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Use NamedTemporaryFile in the target's directory so os.replace is atomic
    # (must be on the same filesystem).
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except Exception:
        # Best-effort cleanup of the tmp file; canonical is unchanged.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def hash_thresholds(thresholds: dict) -> str:
    """SHA-256 hex of a JSON-canonical thresholds dict (key-order invariant).

    Shared between extract_figures (Phase 3a) and caption_figure (Phase 3b)
    so the freshness contract is enforced from a single source of truth.
    """
    import hashlib
    canon = json.dumps(thresholds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()
