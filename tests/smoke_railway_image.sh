#!/usr/bin/env bash
set -euo pipefail

image="${1:-shahnoza-agent:railway-test}"
smoke_volume="shahnoza-railway-smoke-$$"
maintenance_container="shahnoza-railway-maintenance-$$"
cleanup() {
    docker rm -f "$maintenance_container" >/dev/null 2>&1 || true
    docker volume rm "$smoke_volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$smoke_volume" >/dev/null

# Put a deliberately permissive staged login on the test volume. The bootstrap
# must validate it, atomically promote it, and tighten its mode before launch.
docker run --rm \
    -v "$smoke_volume:/data" \
    --entrypoint python \
    "$image" \
    -c '
import json
from pathlib import Path

auth = Path("/data/codex/auth.json.next")
auth.parent.mkdir(parents=True)
auth.write_text(
    json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": "smoke-id-token",
                "access_token": "smoke-access-token",
                "refresh_token": "smoke-refresh-token",
            },
        }
    ),
    encoding="utf-8",
)
auth.chmod(0o644)
'

docker run --rm \
    -v "$smoke_volume:/data" \
    -e RAILWAY_SERVICE_ID=smoke-service \
    -e RAILWAY_VOLUME_MOUNT_PATH=/data \
    "$image" \
    python -c '
import os
import stat
from pathlib import Path

state = Path("/data")
auth = state / "codex/auth.json"
project = state / "config/project.md"
assert os.environ["HAMROH_DATA_DIR"] == "/data/hamroh"
assert os.environ["CODEX_HOME"] == "/data/codex"
assert Path("/app/prompts/project.md").resolve() == project
assert Path("/app/skills").resolve() == state / "skills"
assert stat.S_IMODE(auth.stat().st_mode) == 0o600
assert stat.S_IMODE(auth.parent.stat().st_mode) == 0o700
assert not (state / "codex/auth.json.next").exists()
project.write_text("owner production edit\n", encoding="utf-8")
print("railway first boot: ok")
'

# A second container represents a Railway redeploy. The seed must not replace
# the edit made by the first container.
docker run --rm \
    -v "$smoke_volume:/data" \
    -e RAILWAY_SERVICE_ID=smoke-service \
    -e RAILWAY_VOLUME_MOUNT_PATH=/data \
    "$image" \
    python -c '
from pathlib import Path

project = Path("/data/config/project.md")
assert project.read_text(encoding="utf-8") == "owner production edit\n"
print("railway persistent redeploy: ok")
'

# Maintenance must leave an active container for Railway SFTP while keeping the
# Telegram/Codex worker stopped.
docker run -d --name "$maintenance_container" \
    -v "$smoke_volume:/data" \
    -e RAILWAY_SERVICE_ID=smoke-service \
    -e RAILWAY_VOLUME_MOUNT_PATH=/data \
    -e SHAHNOZA_MAINTENANCE=true \
    "$image" >/dev/null

maintenance_ready=false
for _ in {1..20}; do
    if docker logs "$maintenance_container" 2>&1 | grep -Fq MAINTENANCE_READY; then
        maintenance_ready=true
        break
    fi
    sleep 1
done
test "$maintenance_ready" = true
test "$(docker inspect -f '{{.State.Running}}' "$maintenance_container")" = true
docker run --rm \
    -v "$smoke_volume:/data" \
    --entrypoint python \
    "$image" \
    -c '
import stat
from pathlib import Path

sentinel = Path("/data/.shahnoza-maintenance-ready")
assert sentinel.is_file()
assert stat.S_IMODE(sentinel.stat().st_mode) == 0o600
'
echo "railway maintenance mode: ok"

docker rm -f "$maintenance_container" >/dev/null
docker run --rm \
    -v "$smoke_volume:/data" \
    -e RAILWAY_SERVICE_ID=smoke-service \
    -e RAILWAY_VOLUME_MOUNT_PATH=/data \
    "$image" \
    python -c '
from pathlib import Path

assert not Path("/data/.shahnoza-maintenance-ready").exists()
print("railway maintenance gate reset: ok")
'
