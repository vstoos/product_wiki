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


def test_select_pages_prefers_explicit_pages():
    result = ocr_page.select_pages(pages_spec="3,5", extract_metadata={"problem_pages": [10, 20]})
    assert result == [3, 5]


def test_select_pages_falls_back_to_extract_metadata():
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": [10, 20]})
    assert result == [10, 20]


def test_select_pages_requires_one_source():
    with pytest.raises(ValueError):
        ocr_page.select_pages(pages_spec=None, extract_metadata=None)


def test_select_pages_empty_problem_pages_returns_empty():
    result = ocr_page.select_pages(pages_spec=None, extract_metadata={"problem_pages": []})
    assert result == []


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_page_png_returns_png_bytes(suppl11_pdf):
    data = ocr_page.render_page_png(suppl11_pdf, page_number=1, dpi=150)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 1000


def test_render_page_png_invalid_page_raises(suppl11_pdf):
    with pytest.raises((IndexError, ValueError)):
        ocr_page.render_page_png(suppl11_pdf, page_number=9999, dpi=150)


import json as _json
from unittest.mock import patch


class _MockResponse:
    """Minimal context-manager response for urlopen."""

    def __init__(self, body_dict, status: int = 200):
        self._body = _json.dumps(body_dict).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_transcribe_lmstudio_sends_vision_payload():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _MockResponse({"choices": [{"message": {"content": "TRANSCRIBED"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG\r\n\x1a\nFAKEBYTES",
            host="http://localhost:1234",
            model="glm-ocr",
            timeout=60,
        )
    assert result == "TRANSCRIBED"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["timeout"] == 60
    body = captured["body"]
    assert body["model"] == "glm-ocr"
    assert body["temperature"] == 0.0
    content = body["messages"][0]["content"]
    types = [item["type"] for item in content]
    assert "text" in types and "image_url" in types
    img_item = next(c for c in content if c["type"] == "image_url")
    assert img_item["image_url"]["url"].startswith("data:image/png;base64,")


def test_transcribe_lmstudio_strips_trailing_whitespace():
    body = {"choices": [{"message": {"content": "  hello world  \n"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        result = ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
        )
    assert result == "hello world"


def test_transcribe_lmstudio_propagates_http_error():
    import urllib.error
    err = urllib.error.HTTPError(
        url="x", code=503, msg="unavailable", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            ocr_page.transcribe_lmstudio(
                b"\x89PNG", host="http://localhost:1234", model="m", timeout=60
            )


def test_process_pages_records_per_page_errors(suppl11_pdf):
    call_count = {"n": 0}

    def fake_transcribe(image_bytes, *, host, model, timeout, prompt=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("backend exploded")
        return f"page-text-{call_count['n']}"

    with patch.object(ocr_page, "transcribe_lmstudio", side_effect=fake_transcribe):
        results = ocr_page.process_pages(
            pdf_path=suppl11_pdf,
            page_numbers=[1, 2, 3],
            dpi=100,
            host="http://localhost:1234",
            model="m",
            timeout=60,
        )

    assert [r["page_number"] for r in results] == [1, 2, 3]
    assert results[0]["status"] == "ok"
    assert results[0]["text"] == "page-text-1"
    assert results[1]["status"] == "error"
    assert "backend exploded" in results[1]["error"]
    assert results[1]["text"] == ""
    assert results[2]["status"] == "ok"
    assert results[2]["text"] == "page-text-3"
    for r in results:
        assert "duration_sec" in r
        assert "char_count" in r


def test_process_pages_empty_list_returns_empty():
    results = ocr_page.process_pages(
        pdf_path=Path("nonexistent.pdf"),
        page_numbers=[],
        dpi=100,
        host="x",
        model="x",
        timeout=1,
    )
    assert results == []


def test_load_existing_cache_missing_returns_none(tmp_path):
    assert ocr_page.load_existing_cache(tmp_path / "missing.ocr.json") is None


def test_load_existing_cache_reads_json(tmp_path):
    path = tmp_path / "stem.ocr.json"
    path.write_text(_json.dumps({"pages": [{"page_number": 5, "status": "ok", "text": "x"}]}))
    cache = ocr_page.load_existing_cache(path)
    assert cache is not None
    assert cache["pages"][0]["page_number"] == 5


def test_pages_to_process_excludes_cached_ok():
    cache = {"pages": [
        {"page_number": 5, "status": "ok"},
        {"page_number": 7, "status": "error"},
    ]}
    to_do = ocr_page.pages_to_process(
        requested=[5, 6, 7, 8], cache=cache, force=False
    )
    # 5 is cached-ok -> skip; 7 is cached-error -> retry; 6, 8 are new
    assert to_do == [6, 7, 8]


def test_pages_to_process_force_reprocesses_all():
    cache = {"pages": [
        {"page_number": 5, "status": "ok"},
        {"page_number": 7, "status": "error"},
    ]}
    assert ocr_page.pages_to_process(
        requested=[5, 6, 7], cache=cache, force=True
    ) == [5, 6, 7]


def test_pages_to_process_no_cache_returns_all():
    assert ocr_page.pages_to_process(
        requested=[1, 2, 3], cache=None, force=False
    ) == [1, 2, 3]


def test_merge_with_cache_new_wins_over_old():
    cache = {"pages": [
        {"page_number": 5, "status": "ok", "text": "OLD"},
        {"page_number": 7, "status": "error"},
    ]}
    new = [{"page_number": 7, "status": "ok", "text": "NEW"}]
    merged = ocr_page.merge_with_cache(new_pages=new, cache=cache)
    by_pn = {p["page_number"]: p for p in merged}
    assert by_pn[5]["text"] == "OLD"
    assert by_pn[7]["text"] == "NEW"
    assert [p["page_number"] for p in merged] == [5, 7]  # sorted by page_number


def test_merge_with_cache_no_cache_returns_new_sorted():
    new = [{"page_number": 7, "text": "b"}, {"page_number": 3, "text": "a"}]
    merged = ocr_page.merge_with_cache(new_pages=new, cache=None)
    assert [p["page_number"] for p in merged] == [3, 7]


def test_cli_writes_ocr_json(suppl11_pdf, tmp_path):
    # Provide a fake extract.json indicating page 1 is a problem page
    extract_json = tmp_path / f"{suppl11_pdf.stem}.extract.json"
    extract_json.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "problem_pages": [1],
        "page_count": 35,
    }))

    body = {"choices": [{"message": {"content": "FAKE OCR TEXT"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--extract-json", str(extract_json),
            "--out", str(tmp_path),
            "--engine", "lmstudio",
            "--model", "glm-ocr",
            "--quiet",
        ])
    assert rc == 0

    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    assert ocr_json_path.exists()
    payload = _json.loads(ocr_json_path.read_text())
    assert payload["engine"] == "lmstudio"
    assert payload["model"] == "glm-ocr"
    assert payload["dpi"] == 200
    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["page_number"] == 1
    assert payload["pages"][0]["status"] == "ok"
    assert payload["pages"][0]["text"] == "FAKE OCR TEXT"
    assert "ocr_date" in payload
    assert "total_seconds" in payload


def test_cli_cache_skips_already_ok_pages(suppl11_pdf, tmp_path):
    # Pre-seed cache with page 1 already ok
    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    ocr_json_path.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "engine": "lmstudio",
        "model": "glm-ocr",
        "host": "http://localhost:1234",
        "dpi": 200,
        "pages": [{
            "page_number": 1, "text": "CACHED", "char_count": 6,
            "duration_sec": 0.1, "status": "ok",
        }],
    }))

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        return _MockResponse({"choices": [{"message": {"content": "FRESH"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--quiet",
        ])
    assert rc == 0
    assert call_count["n"] == 0  # cache hit, no HTTP call

    payload = _json.loads(ocr_json_path.read_text())
    assert payload["pages"][0]["text"] == "CACHED"


def test_cli_force_reprocesses_cached_page(suppl11_pdf, tmp_path):
    ocr_json_path = tmp_path / f"{suppl11_pdf.stem}.ocr.json"
    ocr_json_path.write_text(_json.dumps({
        "source_file": suppl11_pdf.name,
        "engine": "lmstudio",
        "model": "glm-ocr",
        "host": "http://localhost:1234",
        "dpi": 200,
        "pages": [{
            "page_number": 1, "text": "CACHED", "char_count": 6,
            "duration_sec": 0.1, "status": "ok",
        }],
    }))

    body = {"choices": [{"message": {"content": "FRESH"}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--force",
            "--quiet",
        ])
    assert rc == 0

    payload = _json.loads(ocr_json_path.read_text())
    assert payload["pages"][0]["text"] == "FRESH"


# ---- Phase 2.1: prompt resolution + image-only path + model-loaded check ----


def test_resolve_prompt_user_override_wins():
    p, mode = ocr_page.resolve_prompt(user_prompt="ABC", model="glm-ocr")
    assert p == "ABC" and mode == "user"


def test_resolve_prompt_user_empty_string_is_explicit():
    p, mode = ocr_page.resolve_prompt(user_prompt="", model="gemma-4-e2b-it")
    assert p == "" and mode == "user"


def test_resolve_prompt_auto_empty_for_ocr_models():
    for name in ["glm-ocr", "GLM-OCR-GGUF", "deepseek-ocr", "lightonocr-2-1b"]:
        p, mode = ocr_page.resolve_prompt(user_prompt=None, model=name)
        assert p == "" and mode == "auto-empty", f"failed for {name}"


def test_resolve_prompt_auto_default_for_general_vision():
    for name in ["gemma-4-e2b-it", "gemma-4-e4b-it", "qwen3.5-2b"]:
        p, mode = ocr_page.resolve_prompt(user_prompt=None, model=name)
        assert p == ocr_page.OCR_PROMPT and mode == "auto-default", f"failed for {name}"


def test_transcribe_lmstudio_omits_text_item_when_prompt_empty():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"choices": [{"message": {"content": "OUT"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="glm-ocr",
            timeout=60, prompt="",
        )
    content = captured["body"]["messages"][0]["content"]
    types = [c["type"] for c in content]
    assert types == ["image_url"], f"expected image-only, got {types}"


def test_transcribe_lmstudio_includes_text_item_when_prompt_set():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"choices": [{"message": {"content": "OUT"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="m",
            timeout=60, prompt="custom-prompt",
        )
    content = captured["body"]["messages"][0]["content"]
    text_items = [c for c in content if c["type"] == "text"]
    assert len(text_items) == 1
    assert text_items[0]["text"] == "custom-prompt"


def test_check_model_loaded_returns_none_when_loaded():
    body = {"data": [{"id": "glm-ocr"}, {"id": "other"}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        warning = ocr_page.check_model_loaded(host="http://localhost:1234", model="glm-ocr")
    assert warning is None


def test_check_model_loaded_warns_when_missing():
    body = {"data": [{"id": "other"}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        warning = ocr_page.check_model_loaded(host="http://localhost:1234", model="glm-ocr")
    assert warning is not None
    assert "glm-ocr" in warning
    assert "lms load" in warning


def test_check_model_loaded_warns_on_network_error():
    import urllib.error
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        warning = ocr_page.check_model_loaded(host="http://localhost:1234", model="m")
    assert warning is not None
    assert "could not query" in warning


def test_cli_records_prompt_mode_in_output(suppl11_pdf, tmp_path):
    body = {"choices": [{"message": {"content": "OUT"}}]}
    models_body = {"data": [{"id": "glm-ocr"}]}

    def fake_urlopen(req, timeout=None):
        # /v1/models is called with a URL string; /v1/chat/completions with a Request
        url = req if isinstance(req, str) else req.full_url
        if "/v1/models" in url:
            return _MockResponse(models_body)
        return _MockResponse(body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--quiet",
        ])
    assert rc == 0
    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert payload["prompt_mode"] == "auto-empty"  # default model contains "ocr"


# ---- Phase 2b: Gemini fallback ----


def test_transcribe_gemini_sends_inline_data_payload():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({
            "candidates": [{"content": {"parts": [{"text": "OCR_TEXT"}]}}]
        })

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ocr_page.transcribe_gemini(
            b"\x89PNG_FAKE",
            api_key="KEY123",
            model="gemma-4-31b-it",
            timeout=60,
            prompt="describe",
        )
    assert result == "OCR_TEXT"
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert "gemma-4-31b-it:generateContent" in captured["url"]
    assert "key=KEY123" in captured["url"]
    parts = captured["body"]["contents"][0]["parts"]
    text_parts = [p for p in parts if "text" in p]
    inline_parts = [p for p in parts if "inline_data" in p]
    assert len(text_parts) == 1 and text_parts[0]["text"] == "describe"
    assert len(inline_parts) == 1
    assert inline_parts[0]["inline_data"]["mime_type"] == "image/png"
    assert inline_parts[0]["inline_data"]["data"]


def test_transcribe_gemini_concatenates_multi_part_response():
    body = {"candidates": [{"content": {"parts": [
        {"text": "thinking..."},
        {"text": "ACTUAL ANSWER"},
    ]}}]}
    with patch("urllib.request.urlopen", return_value=_MockResponse(body)):
        result = ocr_page.transcribe_gemini(
            b"\x89PNG", api_key="K", model="m", timeout=60, prompt="x",
        )
    assert "ACTUAL ANSWER" in result


def test_transcribe_gemini_omits_text_part_when_prompt_empty():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({
            "candidates": [{"content": {"parts": [{"text": "OUT"}]}}]
        })

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ocr_page.transcribe_gemini(
            b"\x89PNG", api_key="K", model="m", timeout=60, prompt="",
        )
    parts = captured["body"]["contents"][0]["parts"]
    types = ["text" if "text" in p else "inline_data" for p in parts]
    assert types == ["inline_data"]


def test_gemini_round_robin_advances_on_429():
    import urllib.error

    pairs_seen = []

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        pairs_seen.append((api_key, model))
        if api_key == "K1":
            raise urllib.error.HTTPError("u", 429, "rate limit", None, None)
        return f"ok-from-{api_key}"

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        text = ocr_page._gemini_with_round_robin(
            b"\x89PNG",
            pairs=[("K1", "m1"), ("K2", "m2")],
            timeout=60,
            prompt="x",
        )
    assert text == "ok-from-K2"
    assert pairs_seen == [("K1", "m1"), ("K2", "m2")]


def test_gemini_round_robin_raises_when_all_pairs_429():
    import urllib.error

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        raise urllib.error.HTTPError("u", 429, "rate limit", None, None)

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        with pytest.raises(RuntimeError) as ei:
            ocr_page._gemini_with_round_robin(
                b"\x89PNG",
                pairs=[("K1", "m1"), ("K2", "m2")],
                timeout=60,
                prompt="x",
            )
    assert "all gemini" in str(ei.value).lower()


def test_gemini_round_robin_propagates_non_429_errors():
    import urllib.error

    def fake_transcribe(image, *, api_key, model, timeout, prompt):
        raise urllib.error.HTTPError("u", 500, "server error", None, None)

    with patch.object(ocr_page, "transcribe_gemini", side_effect=fake_transcribe):
        with pytest.raises(urllib.error.HTTPError):
            ocr_page._gemini_with_round_robin(
                b"\x89PNG",
                pairs=[("K1", "m1")],
                timeout=60,
                prompt="x",
            )


def test_cli_gemini_dispatches_to_gemini_backend(suppl11_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ENV_KEY")
    captured_calls = []

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        captured_calls.append(url)
        if "/v1/models" in url:
            return _MockResponse({"data": []})
        if "generativelanguage.googleapis.com" in url:
            return _MockResponse({"candidates": [{"content": {"parts": [{"text": "GEM"}]}}]})
        raise AssertionError(f"unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--engine", "gemini",
            "--gemini-models", "gemma-4-31b-it",
            "--skip-model-check",
            "--quiet",
        ])
    assert rc == 0
    gem_calls = [u for u in captured_calls if "generativelanguage" in u]
    assert len(gem_calls) == 1
    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert payload["engine"] == "gemini"
    assert payload["pages"][0]["text"] == "GEM"
    assert payload["pages"][0]["status"] == "ok"


def test_cli_gemini_requires_api_key(suppl11_pdf, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    rc = ocr_page.main([
        "--pdf", str(suppl11_pdf),
        "--pages", "1",
        "--out", str(tmp_path),
        "--engine", "gemini",
        "--gemini-models", "gemma-4-31b-it",
        "--skip-model-check",
        "--quiet",
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err or "GOOGLE_API_KEY" in err or "--api-key" in err


def test_cli_gemini_accepts_google_api_key_env(suppl11_pdf, tmp_path, monkeypatch):
    """GOOGLE_API_KEY should work as a fallback for GEMINI_API_KEY (Google's canonical name)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "FROM_GOOGLE_VAR")

    captured_url = {"url": None}

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        captured_url["url"] = url
        if "generativelanguage.googleapis.com" in url:
            return _MockResponse({"candidates": [{"content": {"parts": [{"text": "X"}]}}]})
        return _MockResponse({"data": []})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--engine", "gemini",
            "--gemini-models", "gemma-4-31b-it",
            "--skip-model-check",
            "--quiet",
        ])
    assert rc == 0
    assert "key=FROM_GOOGLE_VAR" in captured_url["url"]


def test_lmstudio_payload_uses_higher_max_tokens(suppl11_pdf):
    """max_tokens for LMStudio bumped to 16384 to leave headroom for thinking-token models."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = _json.loads(req.data.decode("utf-8"))
        return _MockResponse({"choices": [{"message": {"content": "X"}}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ocr_page.transcribe_lmstudio(
            b"\x89PNG", host="http://localhost:1234", model="glm-ocr", timeout=60,
        )
    assert captured["body"]["max_tokens"] == 16384


def test_cli_gemini_requires_models(suppl11_pdf, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    rc = ocr_page.main([
        "--pdf", str(suppl11_pdf),
        "--pages", "1",
        "--out", str(tmp_path),
        "--engine", "gemini",
        "--skip-model-check",
        "--quiet",
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "--gemini-models" in err


def test_cli_gemini_uses_first_gemini_model_for_prompt_resolution(suppl11_pdf, tmp_path, monkeypatch):
    """Prompt mode is decided against the actual model that will receive the request.

    With --engine gemini and --gemini-models gemma-4-31b-it, prompt_mode must be
    'auto-default' (general vision -> use OCR_PROMPT) even though --model still
    defaults to glm-ocr (which never reaches the wire).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "K")
    captured_payloads = []

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "generativelanguage.googleapis.com" in url:
            body = _json.loads(req.data.decode("utf-8"))
            captured_payloads.append(body)
            return _MockResponse({"candidates": [{"content": {"parts": [{"text": "X"}]}}]})
        return _MockResponse({"data": []})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--engine", "gemini",
            "--gemini-models", "gemma-4-31b-it",
            "--skip-model-check",
            "--quiet",
        ])
    assert rc == 0

    # Sent payload should include the OCR_PROMPT text (general vision model)
    parts = captured_payloads[0]["contents"][0]["parts"]
    text_parts = [p for p in parts if "text" in p]
    assert len(text_parts) == 1
    assert text_parts[0]["text"] == ocr_page.OCR_PROMPT

    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert payload["prompt_mode"] == "auto-default"


def test_cli_gemini_records_gemini_models_in_output(suppl11_pdf, tmp_path, monkeypatch):
    """For ALCOA provenance, gemini_models must be persisted in the output JSON."""
    monkeypatch.setenv("GEMINI_API_KEY", "K")

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "generativelanguage.googleapis.com" in url:
            return _MockResponse({"candidates": [{"content": {"parts": [{"text": "X"}]}}]})
        return _MockResponse({"data": []})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--engine", "gemini",
            "--gemini-models", "gemma-4-31b-it,gemma-4-26b-a4b-it",
            "--skip-model-check",
            "--quiet",
        ])
    assert rc == 0
    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert payload["gemini_models"] == "gemma-4-31b-it,gemma-4-26b-a4b-it"


def test_cli_lmstudio_does_not_record_gemini_models(suppl11_pdf, tmp_path):
    """LMStudio runs should not have a stale gemini_models field."""
    body = {"choices": [{"message": {"content": "X"}}]}
    models_body = {"data": [{"id": "glm-ocr"}]}

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "/v1/models" in url:
            return _MockResponse(models_body)
        return _MockResponse(body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = ocr_page.main([
            "--pdf", str(suppl11_pdf),
            "--pages", "1",
            "--out", str(tmp_path),
            "--quiet",
        ])
    assert rc == 0
    payload = _json.loads((tmp_path / f"{suppl11_pdf.stem}.ocr.json").read_text())
    assert "gemini_models" not in payload

