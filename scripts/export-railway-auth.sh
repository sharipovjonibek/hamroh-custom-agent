#!/usr/bin/env bash
set -euo pipefail

# Export the bot-specific Codex login without ever printing it. This file is
# password-equivalent and is ignored by both Git and Docker.
if (( $# != 0 )); then
    echo "Credential exports are restricted to the ignored .railway/codex directory." >&2
    exit 2
fi

output_path=".railway/codex/auth.json"
output_dir="$(dirname -- "$output_path")"

if [[ -e "$output_path" ]]; then
    echo "Refusing to overwrite existing credential export: $output_path" >&2
    exit 1
fi

umask 077
mkdir -p -- "$output_dir"
if [[ "$output_dir" == ".railway" || "$output_dir" == .railway/* ]]; then
    chmod 700 .railway
    chmod 700 "$output_dir"
fi
# A SIGKILL or power loss cannot run an EXIT trap. Remove only the exact
# interrupted-export filenames before creating a fresh credential copy.
rm -f -- "$output_dir"/auth.json.tmp.*
temporary="$(mktemp "${output_path}.tmp.XXXXXX")"
cleanup() {
    rm -f -- "$temporary"
}
trap cleanup EXIT

if ! docker compose run --rm --no-deps -T codex-auth \
    python -m hamroh.codex_login --status; then
    echo "The isolated Codex login did not pass a fresh account check." >&2
    echo "Run 'make auth' using the browser URL, then try again." >&2
    exit 1
fi

if ! docker compose run --rm --no-deps -T --entrypoint sh codex-auth \
    -c 'test -s "$CODEX_HOME/auth.json" && cat "$CODEX_HOME/auth.json"' \
    >"$temporary"; then
    echo "Could not read Shahnoza's isolated Codex login." >&2
    echo "Run 'make auth' first, finish the URL login, then try again." >&2
    exit 1
fi

python3 - "$temporary" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
tokens = payload.get("tokens") if isinstance(payload, dict) else None
required = ("id_token", "access_token", "refresh_token")
valid_tokens = isinstance(tokens, dict) and all(
    isinstance(tokens.get(field), str) and bool(tokens[field].strip())
    for field in required
)
if (
    not isinstance(payload, dict)
    or payload.get("auth_mode") != "chatgpt"
    or not valid_tokens
    or payload.get("OPENAI_API_KEY") not in (None, "")
):
    raise SystemExit("Codex login export is not a complete ChatGPT login")
PY

chmod 600 "$temporary"
mv -- "$temporary" "$output_path"
trap - EXIT
echo "Credential export created safely at $output_path (mode 600)."
echo "Do not open, paste, or commit it. Delete it immediately after upload."
