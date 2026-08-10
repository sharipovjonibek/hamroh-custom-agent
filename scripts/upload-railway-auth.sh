#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/agent-name.sh"
load_agent_identity

export_root=".railway/codex"
export_path="$export_root/auth.json"
expected_volume_name="agent-data"
expected_service_name="agent"
cleanup() {
    rm -f -- "$export_path" "$export_root"/auth.json.tmp.*
    rmdir --ignore-fail-on-non-empty "$export_root" .railway 2>/dev/null || true
}
trap cleanup EXIT

if ! command -v railway >/dev/null 2>&1; then
    echo "Railway CLI is not installed. Follow docs/railway-deployment.md first." >&2
    exit 1
fi

volume_id="$(
    railway volume list --json | python3 -c '
import json
import sys

expected_volume, expected_service = sys.argv[1:]
payload = json.load(sys.stdin)
matches = [
    item
    for item in payload.get("volumes", [])
    if item.get("name") == expected_volume
]
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one Railway volume named {expected_volume} "
        "in the linked environment"
    )
volume = matches[0]
if volume.get("mountPath") != "/data" or volume.get("serviceName") != expected_service:
    raise SystemExit(
        f"{expected_volume} must be mounted at /data on the {expected_service} service"
    )
print(volume["id"])
' "$expected_volume_name" "$expected_service_name"
)"

remote_listing="$(
    railway volume files --volume "$volume_id" list /codex --json
)"
read -r has_current_auth has_staged_auth < <(
    python3 -c '
import json
import sys

names = {item.get("name") for item in json.load(sys.stdin).get("files", [])}
print("yes" if "auth.json" in names else "no", end=" ")
print("yes" if "auth.json.next" in names else "no")
' <<<"$remote_listing"
)
unset remote_listing

if [[ "$has_staged_auth" == "yes" ]]; then
    echo "Railway already has a staged login at /codex/auth.json.next." >&2
    echo "Wait 10 seconds and check the logs before trying another upload." >&2
    exit 1
fi

if [[ "$has_current_auth" == "yes" ]]; then
    if ! railway variable list --service "$expected_service_name" --json | python3 -c '
import json
import sys

value = str(json.load(sys.stdin).get("HAMROH_MAINTENANCE", "")).lower()
raise SystemExit(0 if value in {"1", "true", "yes", "on"} else 1)
'; then
        echo "Railway already has a production login." >&2
        echo "Enable HAMROH_MAINTENANCE=true and wait for MAINTENANCE_READY first." >&2
        exit 1
    fi
    root_listing="$(
        railway volume files --volume "$volume_id" list / --json
    )"
    if ! python3 -c '
import json
import sys

names = {item.get("name") for item in json.load(sys.stdin).get("files", [])}
raise SystemExit(0 if ".agent-maintenance-ready" in names else 1)
' <<<"$root_listing"; then
        echo "The active Railway deployment has not entered maintenance yet." >&2
        echo "Wait for MAINTENANCE_READY in its logs, then retry." >&2
        exit 1
    fi
    unset root_listing
fi

running_services="$(docker compose ps --status running --services 2>/dev/null || true)"
if printf '%s\n' "$running_services" | grep -Fxq agent; then
    echo "Local $AGENT_NAME is still running. Run 'make down' before cutover." >&2
    echo "Never run the local and Railway copies from the same Codex login." >&2
    exit 1
fi

./scripts/export-railway-auth.sh
railway volume files --volume "$volume_id" upload \
    "$export_path" /codex/auth.json.next
cleanup
trap - EXIT
echo "Codex login staged on the verified $AGENT_NAME volume."
echo "Railway will validate it and atomically promote it to /codex/auth.json."
echo "The temporary local export has been deleted."
echo "Keep local $AGENT_NAME stopped while the Railway deployment is active."
