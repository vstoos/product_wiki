"""Ensure LMStudio's local server is up and a model is loaded.

Idempotent. Safe to call repeatedly. Calls the `lms` CLI under the hood,
so it works from any shell (cmd, PowerShell, git-bash) without execution-
policy friction. Companion to `ocr_page.py`.

Usage:
  python ensure_lmstudio.py                       # default: glm-ocr, ttl=600s, gpu=max
  python ensure_lmstudio.py --model gemma-4-e2b-it
  python ensure_lmstudio.py --model glm-ocr --ttl 1800 --gpu 0.5

Requires the `lms` CLI on PATH (LM Studio installs it at
%USERPROFILE%\\.cache\\lm-studio\\bin\\lms.exe on Windows).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raising on non-zero exit. Captures stdout when asked."""
    return subprocess.run(cmd, capture_output=capture, text=True, check=True)


def is_server_running() -> tuple[bool, int]:
    """Return (running, port) from `lms server status --json`."""
    r = _run(["lms", "server", "status", "--json"])
    data = json.loads(r.stdout)
    return bool(data.get("running")), int(data.get("port", 0))


def list_loaded_models() -> list[dict]:
    """Return the list of currently-loaded model dicts from `lms ps --json`."""
    r = _run(["lms", "ps", "--json"])
    text = r.stdout.strip()
    return json.loads(text) if text else []


def model_is_loaded(model: str, loaded: list[dict]) -> bool:
    """True if `model` matches any loaded entry's modelKey or identifier."""
    return any(
        m.get("modelKey") == model or m.get("identifier") == model
        for m in loaded
    )


def start_server() -> None:
    """`lms server start` (passes stdout through for visibility)."""
    _run(["lms", "server", "start"], capture=False)


def load_model(model: str, *, gpu: str, ttl: int) -> None:
    """`lms load <model> --gpu <gpu> --ttl <ttl> -y` (passes spinner through)."""
    _run(
        ["lms", "load", model, "--gpu", gpu, "--ttl", str(ttl), "-y"],
        capture=False,
    )


def ensure(*, model: str, gpu: str, ttl: int) -> int:
    """Bring server up and model loaded. Returns 0 on success, 1 on hard fail."""
    if shutil.which("lms") is None:
        print(
            "error: lms CLI not found on PATH. Install LM Studio and ensure "
            "its bin/ directory is on PATH.",
            file=sys.stderr,
        )
        return 1

    running, port = is_server_running()
    if not running:
        print("Starting LMStudio server...")
        start_server()
        running, port = is_server_running()
        if not running:
            print("error: server still not running after start", file=sys.stderr)
            return 1
    else:
        print(f"LMStudio server already running on port {port}.")

    loaded = list_loaded_models()
    if not model_is_loaded(model, loaded):
        print(f"Loading model '{model}' (gpu={gpu}, ttl={ttl}s)...")
        load_model(model, gpu=gpu, ttl=ttl)
    else:
        print(f"Model '{model}' already loaded.")

    print(f"Ready: server up on :{port}, model '{model}' loaded.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ensure LMStudio server is running and a model is loaded."
    )
    parser.add_argument("--model", default="glm-ocr")
    parser.add_argument("--ttl", type=int, default=600,
                        help="Auto-unload after this many seconds idle")
    parser.add_argument("--gpu", default="max",
                        help='GPU offload: "off", "max", or 0..1 (e.g. "0.5")')
    args = parser.parse_args(argv)
    return ensure(model=args.model, gpu=args.gpu, ttl=args.ttl)


if __name__ == "__main__":
    sys.exit(main())
