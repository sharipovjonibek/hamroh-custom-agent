#!/usr/bin/env bash
set -euo pipefail

running_services="$(docker compose ps --status running --services 2>/dev/null || true)"
if printf '%s\n' "$running_services" | grep -Fxq agent; then
    echo "Local Shahnoza is running. Run 'make down' first." >&2
    exit 1
fi

echo "This removes only the laptop copy of Shahnoza's Codex login."
echo "It does not log out or revoke the production login on Railway."
read -r -p "Type RETIRE to continue: " confirmation
if [[ "$confirmation" != "RETIRE" ]]; then
    echo "Cancelled; the local login was not changed."
    exit 1
fi

docker compose run --rm --no-deps -T --entrypoint sh codex-auth \
    -c 'rm -f -- "$CODEX_HOME/auth.json"'
rm -f -- .railway/codex/auth.json .railway/codex/auth.json.tmp.*
rmdir --ignore-fail-on-non-empty .railway/codex .railway 2>/dev/null || true
echo "The duplicate local Shahnoza login has been removed without logging out."
echo "Keep the local bot stopped while Railway is active."
