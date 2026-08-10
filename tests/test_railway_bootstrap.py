from __future__ import annotations

import importlib.util
import json
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "scripts" / "railway_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("railway_bootstrap", BOOTSTRAP_PATH)
assert SPEC is not None and SPEC.loader is not None
railway_bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(railway_bootstrap)


def _make_seed(root: Path) -> Path:
    seed = root / "seed"
    config = seed / "config"
    config.mkdir(parents=True)
    (config / "access.json").write_text('{"policy":"owner_only"}', encoding="utf-8")
    (config / "default-reminders.json").write_text("[]", encoding="utf-8")
    (config / "plugins.json").write_text('{"version":1}', encoding="utf-8")
    (config / "project.md").write_text("Agent seed\n", encoding="utf-8")
    (seed / "skills").mkdir()
    (seed / "skills" / "README.md").write_text("skills seed\n", encoding="utf-8")
    (seed / "memories").mkdir()
    (seed / "memories" / "README.md").write_text("memories seed\n", encoding="utf-8")
    return seed


def _make_app(root: Path) -> Path:
    app = root / "app"
    (app / "prompts").mkdir(parents=True)
    return app


def _write_fake_auth(state: Path) -> Path:
    auth = state / "codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": "test-id-token",
                    "access_token": "test-access-token",
                    "refresh_token": "test-refresh-token",
                },
            }
        ),
        encoding="utf-8",
    )
    auth.chmod(0o644)
    return auth


def test_first_boot_seeds_and_wires_every_persistent_path(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"
    auth = _write_fake_auth(state)
    environ: dict[str, str] = {}

    result = railway_bootstrap.prepare_environment(
        environ=environ,
        state_root=state,
        seed_root=seed,
        app_root=app,
    )

    assert result == state
    assert (state / "config" / "project.md").read_text() == "Agent seed\n"
    assert (state / "skills" / "README.md").is_file()
    assert (state / "memories" / "README.md").is_file()
    assert (app / "prompts" / "project.md").is_symlink()
    assert (app / "prompts" / "project.md").resolve() == (
        state / "config" / "project.md"
    )
    assert (app / "skills").is_symlink()
    assert (app / "skills").resolve() == state / "skills"
    assert environ["HAMROH_DATA_DIR"] == str(state / "hamroh")
    assert environ["CODEX_HOME"] == str(state / "codex")
    assert environ["HAMROH_MEMORIES_DIR"] == str(state / "memories")
    assert stat.S_IMODE(auth.stat().st_mode) == 0o600
    assert stat.S_IMODE((state / "codex").stat().st_mode) == 0o700


def test_redeploy_never_overwrites_volume_customizations(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"
    _write_fake_auth(state)

    railway_bootstrap.prepare_environment(
        environ={}, state_root=state, seed_root=seed, app_root=app
    )
    (state / "config" / "project.md").write_text(
        "owner production edit\n", encoding="utf-8"
    )
    (state / "skills" / "README.md").write_text(
        "production skill edit\n", encoding="utf-8"
    )
    (seed / "config" / "project.md").write_text("new image seed\n", encoding="utf-8")
    (seed / "skills" / "README.md").write_text("new image skill\n", encoding="utf-8")

    railway_bootstrap.prepare_environment(
        environ={}, state_root=state, seed_root=seed, app_root=app
    )

    assert (state / "config" / "project.md").read_text() == ("owner production edit\n")
    assert (state / "skills" / "README.md").read_text() == ("production skill edit\n")


def test_missing_auth_wait_condition_is_distinct(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)

    with pytest.raises(railway_bootstrap.MissingCodexAuth):
        railway_bootstrap.prepare_environment(
            environ={},
            state_root=tmp_path / "volume",
            seed_root=seed,
            app_root=app,
        )


def test_maintenance_prepares_volume_without_starting_auth(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"

    result = railway_bootstrap.prepare_environment(
        environ={},
        state_root=state,
        seed_root=seed,
        app_root=app,
        require_auth=False,
    )

    assert result == state
    assert stat.S_IMODE((state / "codex").stat().st_mode) == 0o700
    assert (app / "prompts/project.md").is_symlink()


def test_maintenance_sentinel_proves_ready_and_resets_on_normal_boot(
    tmp_path: Path,
) -> None:
    state = tmp_path / "volume"
    state.mkdir()
    environ = {"RAILWAY_DEPLOYMENT_ID": "deployment-test-id"}

    railway_bootstrap._set_maintenance_sentinel(
        state,
        enabled=True,
        environ=environ,
    )
    sentinel = state / railway_bootstrap.MAINTENANCE_SENTINEL

    assert sentinel.read_text(encoding="utf-8") == "deployment-test-id\n"
    assert stat.S_IMODE(sentinel.stat().st_mode) == 0o600

    railway_bootstrap._set_maintenance_sentinel(
        state,
        enabled=False,
        environ=environ,
    )
    assert not sentinel.exists()


def test_invalid_auth_is_rejected_without_echoing_its_body(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"
    auth = state / "codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("not-json-secret-body", encoding="utf-8")

    with pytest.raises(railway_bootstrap.InvalidCodexAuth) as error:
        railway_bootstrap.prepare_environment(
            environ={}, state_root=state, seed_root=seed, app_root=app
        )

    assert "not-json-secret-body" not in str(error.value)


def test_staged_auth_is_validated_and_promoted_atomically(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"
    old_auth = _write_fake_auth(state)
    old_auth.write_text(
        old_auth.read_text(encoding="utf-8").replace(
            "test-refresh-token", "old-refresh-token"
        ),
        encoding="utf-8",
    )
    staged = state / "codex" / "auth.json.next"
    staged.write_text(
        old_auth.read_text(encoding="utf-8").replace(
            "old-refresh-token", "new-refresh-token"
        ),
        encoding="utf-8",
    )

    railway_bootstrap.prepare_environment(
        environ={}, state_root=state, seed_root=seed, app_root=app
    )

    assert not staged.exists()
    assert "new-refresh-token" in old_auth.read_text(encoding="utf-8")
    assert stat.S_IMODE(old_auth.stat().st_mode) == 0o600


def test_incomplete_chatgpt_auth_is_rejected(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    app = _make_app(tmp_path)
    state = tmp_path / "volume"
    auth = state / "codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text('{"auth_mode":"chatgpt","tokens":{}}', encoding="utf-8")

    with pytest.raises(railway_bootstrap.InvalidCodexAuth, match="complete ChatGPT"):
        railway_bootstrap.prepare_environment(
            environ={}, state_root=state, seed_root=seed, app_root=app
        )


def test_railway_runtime_requires_an_attached_volume() -> None:
    with pytest.raises(railway_bootstrap.BootstrapError, match="volume is missing"):
        railway_bootstrap.resolve_state_root({"RAILWAY_SERVICE_ID": "service-id"})

    root = railway_bootstrap.resolve_state_root(
        {
            "RAILWAY_SERVICE_ID": "service-id",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
        }
    )
    assert root == Path("/data")


def test_non_railway_state_root_uses_generic_override() -> None:
    root = railway_bootstrap.resolve_state_root(
        {"HAMROH_STATE_ROOT": "/srv/custom-agent"}
    )

    assert root == Path("/srv/custom-agent")


def test_railway_contract_uses_the_pinned_self_contained_image() -> None:
    config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert config["build"] == {
        "builder": "DOCKERFILE",
        "dockerfilePath": "Dockerfile.railway",
    }
    assert config["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert config["deploy"]["overlapSeconds"] == 0
    assert "healthcheckPath" not in config["deploy"]

    dockerfile = (ROOT / "Dockerfile.railway").read_text(encoding="utf-8")
    assert "FROM hamroh-base" not in dockerfile
    assert "3f8c53f8d1943d4813e4ad4c4d04f1692c015b4d" in dockerfile
    assert "railway_bootstrap.py" in dockerfile
    assert "/opt/agent-seed" in dockerfile
    assert ("SHAH" + "NOZA") not in dockerfile.upper()
    assert "astral-sh/uv:latest" not in dockerfile

    git = shutil.which("git")
    if git is not None:
        result = subprocess.run(
            [git, "rev-parse", "HEAD:framework"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        pinned = re.search(r"ARG HAMROH_COMMIT=([0-9a-f]{40})", dockerfile)
        if result.returncode == 0:
            assert pinned is not None
            assert pinned.group(1) == result.stdout.strip()
