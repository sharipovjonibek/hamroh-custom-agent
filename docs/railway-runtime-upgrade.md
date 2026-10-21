# Repair and verify the Railway Codex runtime

Ticket 006-HCA has three related failures:

- The old Dockerfile selected framework `65a4886` independently of the
  submodule, installing SDK `0.1.0b3` and CLI `0.137.0a4`.
- Framework `60c1ce9` upgraded both packages to `0.163.0` but retained a
  patch for the beta SDK's private notification router. On the new SDK that
  patch accesses the missing `_pending_turn_notifications` field.
- The worker treated the resulting SDK exception as a model rejection and
  tried to reset a session through the dead connection, causing a timeout.

The corrected framework removes the old patch and reconnects SDK stream
failures through its supervisor while retaining the saved session ID. Typed
model errors still follow the engine's existing API error handling.

Railway now fetches the full SHA in `framework-revision.txt`, verifies the
checkout, installs the frozen production lock, and records the actual fetched
SHA at `/app/HAMROH_COMMIT`. A build argument or service variable cannot
override that revision. The final image and each boot check:

```text
SDK: 0.163.0
Runtime: 0.163.0
Binary: codex-cli 0.163.0
Framework: <the full SHA in framework-revision.txt>
Worker import: ok
```

The database, session ID, config, memories, skills, and ChatGPT login continue
to use the existing volume. Image verification reads no credentials. The live
model check uses an ephemeral thread and never writes the bot's session ID,
logs out, or copies auth files. Codex can renew its login normally during the
check.

## Check the repository and image

Run from `hamroh-custom-agent/` with Python 3.11+, uv, and Docker available:

```bash
git submodule update --init --recursive
python3 scripts/pin_railway_framework.py --check
uv sync --project framework --frozen --extra dev --python 3.11
framework/.venv/bin/python -m pytest tests -q
cd framework
uv run --frozen python -m pytest --reruns 0 tests/unit/test_codex_worker.py tests/unit/test_codex_startup.py tests/unit/test_codex_login.py tests/unit/test_api_error_turn.py tests/unit/test_reset_session.py tests/unit/test_recovery_and_limits.py
cd ..
make railway-smoke
```

The Docker smoke test uses a disposable volume and dummy credentials. It
checks first boot, staged auth promotion, database/session/auth preservation
on redeploy, and maintenance readiness without calling Telegram or OpenAI.
GitHub Actions runs these checks when changes are pushed.

For future framework bumps, update the submodule, run
`python3 scripts/pin_railway_framework.py`, and commit `framework/` together
with `framework-revision.txt`. `make update` now does both.

## Deploy the committed fix

These commands use Railway CLI 5.71.0 or a version whose `redeploy --help`
includes `--from-source`. Run from `hamroh-custom-agent/`.

In Railway settings, confirm:

- Source repository: `sharipovjonibek/hamroh-custom-agent`, branch `main`.
- Root directory: repository root; config file: `/railway.json`.
- Builder: Dockerfile; path: `Dockerfile.railway`.
- Start command and pre-deploy command: empty, so the image entrypoint runs.
- Existing `agent-data` volume stays attached to `agent` at `/data`.
- One replica, zero deployment overlap, no HTTP healthcheck.
- Remove any `CODEX_BIN` variable so the verified bundled runtime is used.

Link to the existing production project; replace only the project ID:

```bash
railway link --project YOUR_EXISTING_PROJECT_ID --environment production --service agent
railway status
```

Stage maintenance and the requested model, publish the framework before the
parent, and fetch the updated source:

```bash
railway variable set --service agent --skip-deploys HAMROH_MAINTENANCE=true HAMROH_PROVIDER=codex HAMROH_MODEL=gpt-5.6-sol
git -C framework push origin HEAD:main
git push origin main
railway redeploy --service agent --from-source --yes
railway logs --service agent --build --latest --lines 100
railway logs --service agent --latest --lines 100
```

The new deployment must show the expected version lines and
`MAINTENANCE_READY`. Repeat the final log command until that deployment is
ready. If GitHub autodeploy has already started the same commit, the explicit
redeploy may create another maintenance deployment; wait for the latest one.

A plain `railway redeploy` reuses the existing image. Use
`--from-source` when deploying updated source. Check the deployment's source
commit in Railway; if it does not match `git rev-parse HEAD`, inspect the
repository, branch, root directory, and config settings above.

## Verify inside the deployed container

Compare the running image to the local framework pin:

```bash
railway ssh --service agent -- python /app/scripts/verify_railway_runtime.py --expected-commit "$(cat framework-revision.txt)"
railway ssh --service agent -- python -c "import importlib.metadata as m; print('SDK:', m.version('openai-codex')); print('Runtime:', m.version('openai-codex-cli-bin'))"
```

Then perform one small real inference using the existing ChatGPT login and
the deployed `HAMROH_MODEL` setting:

```bash
railway ssh --service agent -- python /app/scripts/verify_railway_runtime.py --check-model
```

Expected final line:

```text
ChatGPT auth + model gpt-5.6-sol: ok
```

This requires the current deployment's maintenance marker, preventing a
second process from sharing the login with the running bot. It denies
approvals, disables native tools, and sends only a fixed verification prompt.
Model access is established by a successful inference, not by listing models.
If the check fails, retain maintenance while inspecting the error; do not
erase the volume or re-upload credentials to fix a version mismatch.

Resume production after a successful check:

```bash
railway variable delete --service agent HAMROH_MAINTENANCE
railway logs --service agent --latest --lines 100
```

Wait for `Codex runtime ready` with `model=gpt-5.6-sol` and `hamroh is live`,
then send the bot a normal Telegram message. Keep the local bot stopped.

The ChatGPT account must have access to the selected model. The
[OpenAI SDK documentation](https://learn.chatgpt.com/docs/codex-sdk) describes
the bundled runtime, and the
[authentication documentation](https://learn.chatgpt.com/docs/auth) describes
the file-backed login and automatic token renewal.

## Ticket verification recorded on 2026-10-21

- All 31 deployment tests passed, including the diagnostic CLI, stale version
  rejection, pin synchronization, and preservation of existing volume files.
- Python 3.11 syntax, shell syntax, dependency/lock alignment, and the new
  framework pin were checked locally.
- The framework SDK suite could not run locally because its dependencies and
  Python 3.11 could not be downloaded in the restricted environment.
- Docker access was denied, so the final image build and container smoke test
  remain to be run using the commands above or GitHub Actions.
- No Railway project was linked in this checkout. A real ChatGPT inference
  with `gpt-5.6-sol` remains unverified until the deployed model check succeeds.
