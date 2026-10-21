#!/usr/bin/env python3
"""Prepare an agent's persistent Railway state, then start Hamroh.

Railway mounts one persistent volume when the container starts. This bootstrap
seeds mutable files on their first boot, preserves them on every later deploy,
and keeps Codex's renewable browser-OAuth credentials on that volume.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from collections.abc import MutableMapping, Sequence
from pathlib import Path


class BootstrapError(RuntimeError):
    """A deployment prerequisite is missing or unsafe."""


class CodexAuthError(BootstrapError):
    """Codex credentials are absent or not ready yet."""


class MissingCodexAuth(CodexAuthError):
    """The persistent volume has not received auth.json yet."""


class InvalidCodexAuth(CodexAuthError):
    """The uploaded auth.json is incomplete or malformed."""


RAILWAY_MARKERS = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_ENVIRONMENT_ID",
)
AUTH_FILENAME = "auth.json"
STAGED_AUTH_FILENAME = "auth.json.next"
REQUIRED_CHATGPT_TOKEN_FIELDS = ("id_token", "access_token", "refresh_token")
MAINTENANCE_SENTINEL = ".agent-maintenance-ready"


def resolve_state_root(environ: MutableMapping[str, str]) -> Path:
    """Use Railway's actual mount path, and reject a volume-less deploy."""
    railway_runtime = any(environ.get(name) for name in RAILWAY_MARKERS)
    railway_mount = environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_runtime and not railway_mount:
        raise BootstrapError(
            "Railway volume is missing. Attach one volume to this service and "
            "set its mount path to /data, then redeploy."
        )
    raw = railway_mount or environ.get("HAMROH_STATE_ROOT", "/data")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise BootstrapError(f"persistent state path must be absolute: {root}")
    return root


def _copy_file_once(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.seed-{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_tree_once(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.seed-{os.getpid()}")
    try:
        shutil.copytree(source, temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _replace_with_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve(strict=False) == target.resolve(strict=False):
            return
        link.unlink()
    elif link.exists():
        raise BootstrapError(
            f"refusing to replace unexpected image path with a symlink: {link}"
        )
    link.symlink_to(target)


def _validate_codex_auth_file(auth_path: Path) -> None:
    if not auth_path.is_file() or auth_path.stat().st_size == 0:
        raise MissingCodexAuth(
            f"Codex login is missing at the persistent volume path {auth_path}."
        )
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidCodexAuth(
            f"Codex login file at {auth_path} is not valid JSON; upload it again."
        ) from exc
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    valid_tokens = isinstance(tokens, dict) and all(
        isinstance(tokens.get(field), str) and bool(tokens[field].strip())
        for field in REQUIRED_CHATGPT_TOKEN_FIELDS
    )
    if (
        not isinstance(payload, dict)
        or payload.get("auth_mode") != "chatgpt"
        or not valid_tokens
        or payload.get("OPENAI_API_KEY") not in (None, "")
    ):
        raise InvalidCodexAuth(
            f"Codex login file at {auth_path} is not a complete ChatGPT login."
        )


def _promote_staged_codex_auth(codex_home: Path) -> bool:
    """Validate and atomically promote an SFTP-uploaded login on one volume."""
    staged = codex_home / STAGED_AUTH_FILENAME
    if not staged.exists():
        return False
    _validate_codex_auth_file(staged)
    staged.chmod(0o600)
    staged.replace(codex_home / AUTH_FILENAME)
    return True


def _validate_codex_auth(codex_home: Path) -> None:
    auth_path = codex_home / AUTH_FILENAME
    _validate_codex_auth_file(auth_path)
    codex_home.chmod(0o700)
    auth_path.chmod(0o600)


def _enabled(environ: MutableMapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _set_maintenance_sentinel(
    state_root: Path,
    *,
    enabled: bool,
    environ: MutableMapping[str, str],
) -> None:
    sentinel = state_root / MAINTENANCE_SENTINEL
    if not enabled:
        sentinel.unlink(missing_ok=True)
        return
    deployment_id = environ.get("RAILWAY_DEPLOYMENT_ID", "maintenance").strip()
    temporary = sentinel.with_name(f".{sentinel.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(f"{deployment_id or 'maintenance'}\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(sentinel)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_environment(
    *,
    environ: MutableMapping[str, str] | None = None,
    state_root: Path | None = None,
    seed_root: Path = Path("/opt/agent-seed"),
    app_root: Path = Path("/app"),
    require_auth: bool = True,
) -> Path:
    """Seed and wire persistent state. Returns the selected state root."""
    env = os.environ if environ is None else environ
    root = state_root or resolve_state_root(env)
    root.mkdir(parents=True, exist_ok=True)

    paths = {
        "HAMROH_DATA_DIR": root / "hamroh",
        "CODEX_HOME": root / "codex",
        "HAMROH_MEMORIES_DIR": root / "memories",
        "HAMROH_ACCESS_PATH": root / "config" / "access.json",
        "HAMROH_REMINDERS_PATH": root / "config" / "default-reminders.json",
        "HAMROH_PLUGINS_PATH": root / "config" / "plugins.json",
    }
    for key, path in paths.items():
        env[key] = str(path)

    (root / "hamroh").mkdir(parents=True, exist_ok=True)
    (root / "codex").mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "codex").chmod(0o700)
    (root / "config").mkdir(parents=True, exist_ok=True)

    for filename in ("access.json", "default-reminders.json", "plugins.json"):
        _copy_file_once(
            seed_root / "config" / filename,
            root / "config" / filename,
        )
    _copy_file_once(
        seed_root / "config" / "project.md",
        root / "config" / "project.md",
    )
    _copy_tree_once(seed_root / "skills", root / "skills")
    _copy_tree_once(seed_root / "memories", root / "memories")

    _promote_staged_codex_auth(root / "codex")
    if require_auth:
        try:
            _validate_codex_auth(root / "codex")
        except MissingCodexAuth as exc:
            raise MissingCodexAuth(
                f"{exc} Run `make railway-auth-upload` on the already "
                "authenticated laptop."
            ) from exc
    _replace_with_symlink(
        app_root / "prompts" / "project.md",
        root / "config" / "project.md",
    )
    _replace_with_symlink(app_root / "skills", root / "skills")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    from verify_railway_runtime import verify_image

    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        raise BootstrapError("no application command was supplied")
    try:
        verify_image()
    except Exception as exc:
        raise BootstrapError(f"image runtime verification failed: {exc}") from exc
    maintenance = _enabled(os.environ, "HAMROH_MAINTENANCE")
    state_root = resolve_state_root(os.environ)
    state_root.mkdir(parents=True, exist_ok=True)
    _set_maintenance_sentinel(
        state_root,
        enabled=False,
        environ=os.environ,
    )
    last_auth_message = ""
    maintenance_announced = False
    while True:
        staged = state_root / "codex" / STAGED_AUTH_FILENAME
        had_staged_auth = staged.exists()
        try:
            root = prepare_environment(
                state_root=state_root,
                require_auth=not maintenance,
            )
        except CodexAuthError as exc:
            message = str(exc)
            if message != last_auth_message:
                print(
                    f"[agent-bootstrap] WAITING_FOR_CODEX_AUTH: {message}",
                    file=sys.stderr,
                    flush=True,
                )
                last_auth_message = message
            time.sleep(10)
            continue
        if had_staged_auth and not staged.exists():
            print(
                "[agent-bootstrap] STAGED_CODEX_AUTH_READY: "
                "validated and promoted atomically",
                flush=True,
            )
        if maintenance:
            if not maintenance_announced:
                _set_maintenance_sentinel(
                    state_root,
                    enabled=True,
                    environ=os.environ,
                )
                print(
                    "[agent-bootstrap] MAINTENANCE_READY: "
                    "Telegram and Codex are stopped; volume transfer is available",
                    flush=True,
                )
                maintenance_announced = True
            time.sleep(10)
            continue
        break
    print(f"[agent-bootstrap] persistent state ready at {root}", flush=True)
    os.execvpe(command[0], command, os.environ)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"[agent-bootstrap] ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(78) from exc
