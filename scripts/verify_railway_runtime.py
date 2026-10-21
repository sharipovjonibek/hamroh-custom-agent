#!/usr/bin/env python3
"""Verify the built image; optionally run one ChatGPT-authenticated model turn."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

# The image installs dependencies with --no-install-project. When invoked as
# a script, Python otherwise searches /app/scripts but cannot import /app/hamroh.
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

EXPECTED_VERSION = "0.163.0"
COMMIT_PATH = APP_ROOT / "HAMROH_COMMIT"
PIN_PATH = APP_ROOT / "framework-revision.txt"
MODEL_REPLY = "HAMROH_CODEX_OK"


def verify_image(*, expected_commit: str | None = None) -> None:
    for label, package in (
        ("SDK", "openai-codex"),
        ("Runtime", "openai-codex-cli-bin"),
    ):
        version = importlib.metadata.version(package)
        print(f"{label}: {version}", flush=True)
        if version != EXPECTED_VERSION:
            raise RuntimeError(f"{package}: expected {EXPECTED_VERSION}, found {version}")
    # Import the worker against the installed SDK to catch removed types/APIs.
    importlib.import_module("hamroh.codex_worker")
    from codex_cli_bin import bundled_codex_path

    binary = subprocess.run(
        [str(bundled_codex_path()), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    print(f"Binary: {binary}", flush=True)
    if binary.split()[-1:] != [EXPECTED_VERSION]:
        raise RuntimeError("the bundled Codex binary does not match the installed SDK")
    revision = COMMIT_PATH.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("image framework provenance is missing or invalid")
    print(f"Framework: {revision}", flush=True)
    selected_revision = PIN_PATH.read_text(encoding="utf-8").strip()
    if revision != selected_revision:
        raise RuntimeError("fetched framework does not match framework-revision.txt")
    if expected_commit is not None and revision != expected_commit:
        raise RuntimeError(f"wrong framework image: expected {expected_commit}")
    if os.environ.get("CODEX_BIN"):
        raise RuntimeError("unset CODEX_BIN so Hamroh uses the verified bundled runtime")
    print("Worker import: ok", flush=True)


def model_check_settings() -> tuple[Path, str]:
    # Use maintenance in the deployed service so there is only one process
    # using its renewable login. Never copy, replace, or print the credentials.
    from railway_bootstrap import (
        MAINTENANCE_SENTINEL,
        _validate_codex_auth_file,
        resolve_state_root,
    )

    root = resolve_state_root(os.environ)
    sentinel = root / MAINTENANCE_SENTINEL
    if not sentinel.is_file():
        raise RuntimeError("enable HAMROH_MAINTENANCE=true and wait for MAINTENANCE_READY")
    deployment = os.environ.get("RAILWAY_DEPLOYMENT_ID")
    if deployment and sentinel.read_text(encoding="utf-8").strip() != deployment:
        raise RuntimeError("maintenance marker belongs to a different deployment")
    codex_home = root / "codex"
    _validate_codex_auth_file(codex_home / "auth.json")
    model = os.environ.get("HAMROH_MODEL", "").strip()
    if not model:
        raise RuntimeError("set HAMROH_MODEL=gpt-5.6-sol before checking model access")
    return codex_home, model


async def verify_model(codex_home: Path, model: str) -> None:
    from codex_cli_bin import bundled_codex_path, bundled_path_dir
    from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

    path = os.pathsep.join(
        part for part in (str(bundled_path_dir() or ""), os.environ.get("PATH", "")) if part
    )
    # Match the worker's clean launch: API keys and Telegram/plugin secrets
    # never reach the Codex process, so this turn proves ChatGPT auth works.
    launch = (
        "/usr/bin/env", "-i", f"PATH={path}", f"HOME={codex_home}",
        f"CODEX_HOME={codex_home}", "LANG=C.UTF-8",
        str(bundled_codex_path()), "app-server", "--listen", "stdio://",
    )
    async with AsyncCodex(CodexConfig(launch_args_override=launch, cwd="/app")) as codex:
        account = await codex.account(refresh_token=False)
        if account.account is None or account.account.root.type != "chatgpt":
            raise RuntimeError("the runtime is not authenticated with ChatGPT")
        thread = await codex.thread_start(
            model=model,
            ephemeral=True,
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            config={
                "features": {
                    "shell_tool": False, "unified_exec": False,
                    "multi_agent": False, "apps": False, "remote_plugin": False,
                    "shell_snapshot": False, "hooks": False, "goals": False,
                    "memories": False, "personality": False,
                },
                "web_search": "disabled",
            },
            developer_instructions="Return the requested token without using tools.",
        )
        result = await thread.run(
            f"Reply with exactly {MODEL_REPLY}.",
            model=model,
            approval_mode=ApprovalMode.deny_all,
            sandbox=Sandbox.read_only,
        )
        if result.final_response.strip() != MODEL_REPLY:
            raise RuntimeError("model verification did not return the expected token")
    print(f"ChatGPT auth + model {model}: ok", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit")
    parser.add_argument("--check-model", action="store_true")
    args = parser.parse_args(argv)
    try:
        verify_image(expected_commit=args.expected_commit)
        if args.check_model:
            codex_home, model = model_check_settings()
            asyncio.run(asyncio.wait_for(verify_model(codex_home, model), timeout=120))
    except Exception as exc:
        print(f"Runtime verification failed: {str(exc) or type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
