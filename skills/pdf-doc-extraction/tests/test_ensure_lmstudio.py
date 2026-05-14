"""Tests for ensure_lmstudio.py. subprocess and shutil.which are mocked."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ensure_lmstudio.py"
_spec = importlib.util.spec_from_file_location("ensure_lmstudio", SCRIPT)
ensure_lmstudio = importlib.util.module_from_spec(_spec)
sys.modules["ensure_lmstudio"] = ensure_lmstudio
_spec.loader.exec_module(ensure_lmstudio)


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_model_is_loaded_matches_model_key():
    loaded = [{"modelKey": "glm-ocr", "identifier": "glm-ocr:2"}]
    assert ensure_lmstudio.model_is_loaded("glm-ocr", loaded) is True


def test_model_is_loaded_matches_identifier():
    loaded = [{"modelKey": "glm-ocr", "identifier": "glm-ocr:2"}]
    assert ensure_lmstudio.model_is_loaded("glm-ocr:2", loaded) is True


def test_model_is_loaded_returns_false_when_absent():
    loaded = [{"modelKey": "other", "identifier": "other:1"}]
    assert ensure_lmstudio.model_is_loaded("glm-ocr", loaded) is False


def test_model_is_loaded_handles_empty():
    assert ensure_lmstudio.model_is_loaded("glm-ocr", []) is False


def test_ensure_aborts_when_lms_not_on_path(capsys):
    with patch("shutil.which", return_value=None):
        rc = ensure_lmstudio.ensure(model="glm-ocr", gpu="max", ttl=600)
    assert rc == 1
    err = capsys.readouterr().err
    assert "lms CLI not found" in err


def test_ensure_starts_server_when_down_then_loads_model(capsys):
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        calls.append(list(cmd))
        # status: first call says not running, second call says running
        if cmd[:3] == ["lms", "server", "status"]:
            running = any(c[:3] == ["lms", "server", "start"] for c in calls[:-1])
            body = json.dumps({"running": running, "port": 1234})
            return _completed(stdout=body)
        if cmd[:2] == ["lms", "ps"]:
            return _completed(stdout="[]")
        # server start / load: succeed silently
        return _completed()

    with patch("shutil.which", return_value="C:\\fake\\lms.exe"), \
         patch("subprocess.run", side_effect=fake_run):
        rc = ensure_lmstudio.ensure(model="glm-ocr", gpu="max", ttl=600)
    assert rc == 0
    cmd_heads = [tuple(c[:3]) for c in calls]
    assert ("lms", "server", "status") in cmd_heads
    assert ("lms", "server", "start") in cmd_heads
    assert ("lms", "load", "glm-ocr") in cmd_heads


def test_ensure_skips_start_when_server_already_running(capsys):
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        calls.append(list(cmd))
        if cmd[:3] == ["lms", "server", "status"]:
            return _completed(stdout=json.dumps({"running": True, "port": 1234}))
        if cmd[:2] == ["lms", "ps"]:
            return _completed(stdout="[]")
        return _completed()

    with patch("shutil.which", return_value="C:\\fake\\lms.exe"), \
         patch("subprocess.run", side_effect=fake_run):
        rc = ensure_lmstudio.ensure(model="glm-ocr", gpu="max", ttl=600)
    assert rc == 0
    cmd_heads = [tuple(c[:3]) for c in calls]
    assert ("lms", "server", "start") not in cmd_heads
    assert ("lms", "load", "glm-ocr") in cmd_heads


def test_ensure_skips_load_when_model_already_loaded(capsys):
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        calls.append(list(cmd))
        if cmd[:3] == ["lms", "server", "status"]:
            return _completed(stdout=json.dumps({"running": True, "port": 1234}))
        if cmd[:2] == ["lms", "ps"]:
            return _completed(stdout=json.dumps([
                {"modelKey": "glm-ocr", "identifier": "glm-ocr:1"}
            ]))
        return _completed()

    with patch("shutil.which", return_value="C:\\fake\\lms.exe"), \
         patch("subprocess.run", side_effect=fake_run):
        rc = ensure_lmstudio.ensure(model="glm-ocr", gpu="max", ttl=600)
    assert rc == 0
    cmd_heads = [tuple(c[:3]) for c in calls]
    assert ("lms", "load", "glm-ocr") not in cmd_heads
    out = capsys.readouterr().out
    assert "already loaded" in out


def test_main_passes_args_through():
    captured = {}

    def fake_ensure(*, model, gpu, ttl):
        captured["model"] = model
        captured["gpu"] = gpu
        captured["ttl"] = ttl
        return 0

    with patch.object(ensure_lmstudio, "ensure", side_effect=fake_ensure):
        rc = ensure_lmstudio.main(["--model", "gemma-4-e4b-it", "--gpu", "0.5", "--ttl", "1800"])
    assert rc == 0
    assert captured == {"model": "gemma-4-e4b-it", "gpu": "0.5", "ttl": 1800}
