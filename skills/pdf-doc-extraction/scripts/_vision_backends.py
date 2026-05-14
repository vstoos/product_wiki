"""Shared vision backends for ocr_page and caption_figure.

Contains the prompt constants and HTTP transcription helpers that are
reused by multiple CLI tools in this skill. Kept as an internal module
(leading underscore) because it is not a standalone CLI tool.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request


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

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"


def transcribe_lmstudio(
    image_png_bytes: bytes,
    *,
    host: str,
    model: str,
    timeout: int,
    prompt: str = OCR_PROMPT,
) -> str:
    """POST the image to a local LMStudio OpenAI-compatible vision endpoint.

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
        "max_tokens": 4096,
    }
    req = urllib.request.Request(
        url=f"{host.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
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
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
    }
    url = GEMINI_ENDPOINT.format(model=model, api_key=api_key)
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    out_parts = body["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in out_parts if "text" in p)
    return text.strip()


def _gemini_with_round_robin(
    image_png_bytes: bytes,
    *,
    pairs: list[tuple[str, str]],
    timeout: int,
    prompt: str,
) -> str:
    """Try each (api_key, model) pair in order. Advance on HTTP 429, raise otherwise.

    Raises RuntimeError if every pair returns 429.
    """
    last_429: Exception | None = None
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
            if e.code == 429:
                last_429 = e
                continue
            raise
    raise RuntimeError(
        f"all gemini (api_key, model) pairs returned 429 ({len(pairs)} tried)"
    ) from last_429


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
        return f"could not query {host}/v1/models ({type(e).__name__}: {e}) - is LMStudio running?"
    loaded_ids = [m.get("id") for m in body.get("data", [])]
    if model in loaded_ids:
        return None
    return f"model '{model}' is not loaded; loaded: {loaded_ids}. Try: lms load {model} --gpu max -y"
