"""Deployment diagnostics must catch stale images without touching credentials."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pin_railway_framework as pin
import verify_railway_runtime as verify


@pytest.fixture
def image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    commit = tmp_path / "HAMROH_COMMIT"
    commit.write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(verify, "COMMIT_PATH", commit)
    pin_file = tmp_path / "framework-revision.txt"
    pin_file.write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(verify, "PIN_PATH", pin_file)
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr(verify.importlib.metadata, "version", lambda _name: "0.163.0")
    imported = []
    monkeypatch.setattr(verify.importlib, "import_module", imported.append)
    monkeypatch.setitem(
        sys.modules, "codex_cli_bin",
        SimpleNamespace(bundled_codex_path=lambda: Path("/fake/codex")),
    )
    monkeypatch.setattr(
        verify.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="codex-cli 0.163.0\n")
    )
    return commit, imported


def test_image_verifies_worker_versions_binary_and_provenance(image, capsys):
    _, imported = image
    verify.verify_image(expected_commit="a" * 40)
    assert imported == ["hamroh.codex_worker"]
    assert "SDK: 0.163.0" in capsys.readouterr().out


@pytest.mark.parametrize("package", ["openai-codex", "openai-codex-cli-bin"])
def test_stale_distribution_is_rejected(image, monkeypatch, package):
    monkeypatch.setattr(
        verify.importlib.metadata, "version",
        lambda name: "0.1.0b3" if name == package else "0.163.0",
    )
    with pytest.raises(RuntimeError, match="expected 0.163.0"):
        verify.verify_image()


def test_stale_executable_is_rejected_even_with_current_metadata(image, monkeypatch):
    monkeypatch.setattr(
        verify.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codex-cli 0.137.0a4\n"),
    )
    with pytest.raises(RuntimeError, match="binary does not match"):
        verify.verify_image()


def test_wrong_framework_image_is_rejected(image):
    with pytest.raises(RuntimeError, match="wrong framework image"):
        verify.verify_image(expected_commit="b" * 40)


def test_fetched_source_must_match_manifest(image):
    commit, _ = image
    commit.write_text("b" * 40 + "\n")
    with pytest.raises(RuntimeError, match="does not match framework-revision.txt"):
        verify.verify_image()


def test_script_imports_uninstalled_application_from_image_root(tmp_path):
    app = tmp_path / "app"
    scripts = app / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "verify_railway_runtime.py"
    script.write_text((ROOT / "scripts/verify_railway_runtime.py").read_text())
    (app / "HAMROH_COMMIT").write_text("a" * 40 + "\n")
    (app / "framework-revision.txt").write_text("a" * 40 + "\n")
    for name in ("openai_codex", "openai_codex_cli_bin"):
        metadata = app / f"{name}-0.163.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(f"Name: {name.replace('_', '-')}\nVersion: 0.163.0\n")
    (app / "hamroh").mkdir()
    (app / "hamroh/__init__.py").touch()
    (app / "hamroh/codex_worker.py").touch()
    binary = app / "codex"
    binary.write_text("#!/bin/sh\nprintf 'codex-cli 0.163.0\\n'\n")
    binary.chmod(0o755)
    (app / "codex_cli_bin.py").write_text(f"def bundled_codex_path():\n    return {str(binary)!r}\n")
    environ = {key: value for key, value in os.environ.items() if key != "CODEX_BIN"}
    result = subprocess.run(
        [sys.executable, str(script), "--expected-commit", "a" * 40],
        cwd=tmp_path, env=environ, capture_output=True, text=True, check=True,
    )
    assert "Worker import: ok" in result.stdout


def test_runtime_override_cannot_bypass_verified_binary(image, monkeypatch):
    monkeypatch.setenv("CODEX_BIN", "/old/codex")
    with pytest.raises(RuntimeError, match="unset CODEX_BIN"):
        verify.verify_image()


def test_verifier_matches_both_framework_dependency_pins():
    project = tomllib.loads((ROOT / "framework/pyproject.toml").read_text())
    locked = tomllib.loads((ROOT / "framework/uv.lock").read_text())
    for name in ("openai-codex", "openai-codex-cli-bin"):
        assert f"{name}=={verify.EXPECTED_VERSION}" in project["project"]["dependencies"]
        assert next(p["version"] for p in locked["package"] if p["name"] == name) == verify.EXPECTED_VERSION


def test_model_check_requires_active_maintenance(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMROH_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="MAINTENANCE_READY"):
        verify.model_check_settings()


def test_model_check_uses_existing_chatgpt_login_without_rewriting_it(tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deployment-test")
    monkeypatch.setenv("HAMROH_MODEL", "gpt-5.6-sol")
    (tmp_path / ".agent-maintenance-ready").write_text("deployment-test\n")
    auth = tmp_path / "codex/auth.json"
    auth.parent.mkdir()
    body = json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": "id", "access_token": "access", "refresh_token": "refresh"},
    })
    auth.write_text(body)
    assert verify.model_check_settings() == (auth.parent, "gpt-5.6-sol")
    assert auth.read_text() == body


def test_stale_maintenance_marker_cannot_start_second_auth_user(tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "new-deployment")
    (tmp_path / ".agent-maintenance-ready").write_text("old-deployment\n")
    with pytest.raises(RuntimeError, match="different deployment"):
        verify.model_check_settings()


@pytest.mark.parametrize("account_type", ["chatgpt", "apiKey"])
def test_live_check_uses_requested_model_with_clean_chatgpt_runtime(
    tmp_path, monkeypatch, account_type,
):
    launches = []
    threads = []
    turns = []

    class FakeThread:
        async def run(self, prompt, **kwargs):
            turns.append((prompt, kwargs))
            return SimpleNamespace(final_response=verify.MODEL_REPLY)

    class FakeCodex:
        def __init__(self, config):
            launches.append(config)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def account(self, **kwargs):
            assert kwargs == {"refresh_token": False}
            return SimpleNamespace(account=SimpleNamespace(root=SimpleNamespace(type=account_type)))

        async def thread_start(self, **kwargs):
            threads.append(kwargs)
            return FakeThread()

    monkeypatch.setitem(sys.modules, "openai_codex", SimpleNamespace(
        AsyncCodex=FakeCodex, CodexConfig=lambda **kwargs: kwargs,
        ApprovalMode=SimpleNamespace(deny_all="deny_all"),
        Sandbox=SimpleNamespace(read_only="read_only"),
    ))
    monkeypatch.setitem(sys.modules, "codex_cli_bin", SimpleNamespace(
        bundled_codex_path=lambda: Path("/bundled/codex"),
        bundled_path_dir=lambda: Path("/bundled"),
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-runtime")
    check = verify.verify_model(tmp_path / "codex", "gpt-5.6-sol")
    if account_type == "apiKey":
        with pytest.raises(RuntimeError, match="not authenticated with ChatGPT"):
            asyncio.run(check)
        assert threads == turns == []
    else:
        asyncio.run(check)
        assert threads[0]["model"] == turns[0][1]["model"] == "gpt-5.6-sol"
        assert threads[0]["ephemeral"] is True
        assert threads[0]["sandbox"] == "read_only"
        assert threads[0]["approval_mode"] == "deny_all"
    launch = launches[0]["launch_args_override"]
    assert launch[:2] == ("/usr/bin/env", "-i")
    assert "must-not-reach-runtime" not in repr(launch)
    assert f"CODEX_HOME={tmp_path / 'codex'}" in launch


def test_pin_helper_updates_manifest_to_framework_head(tmp_path):
    framework = tmp_path / "framework"
    framework.mkdir()
    subprocess.run(["git", "init", "-q", str(framework)], check=True)
    subprocess.run(
        ["git", "-C", str(framework), "-c", "user.name=Test", "-c",
         "user.email=test@example.com", "commit", "--allow-empty", "-qm", "framework"],
        check=True,
    )
    manifest = tmp_path / "framework-revision.txt"
    manifest.write_text("0" * 40 + "\n")
    with pytest.raises(RuntimeError, match="stale"):
        pin.sync_pin(tmp_path, check=True)
    revision = pin.sync_pin(tmp_path)
    assert manifest.read_text() == revision + "\n"
    assert pin.sync_pin(tmp_path, check=True) == revision


def test_pin_helper_rejects_missing_submodule(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c",
         "user.email=test@example.com", "commit", "--allow-empty", "-qm", "parent"],
        check=True,
    )
    (tmp_path / "framework").mkdir()
    with pytest.raises(RuntimeError, match="initialize the framework"):
        pin.sync_pin(tmp_path)
