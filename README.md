# Shahnoza Telegram Agent

A deployable Telegram AI assistant developed and customized by **Jonibek
Sharipov**. It uses the [hamroh](https://github.com/sharipovjonibek/hamroh)
runtime pinned as a git submodule under `framework/`; this repository owns
Shahnoza's persona, skills, memories, MCP config, reminders, and access policy.

Shahnoza identifies Jonibek Sharipov as the developer of this version. Internal
runtime implementation details are not part of her public-facing identity.

## Setup

```bash
git clone --recurse-submodules https://github.com/sharipovjonibek/hamroh-custom-agent && cd hamroh-custom-agent
# already cloned without --recurse-submodules?
git submodule update --init

cp .env.example .env    # set TELEGRAM_BOT_TOKEN and HAMROH_OWNER_ID only
chmod 600 .env

make auth               # build, then sign the bot into your ChatGPT account once
make up                 # start Shahnoza
make logs
```

`make up` runs two steps — build the framework base (`hamroh-base`), then build
your agent on top of it and start it. `docker compose up` alone won't work: the
`Dockerfile` needs `hamroh-base` to exist first.

The agent runs through the official Codex Python SDK. `make auth` prints a
ChatGPT authorization URL and waits for the browser to return to the local
OAuth callback on port `1455`. Open that URL on this computer and finish
signing in. The resulting login is stored in a private Docker volume named
`codex-home`. It does not mount your personal `~/.codex`, and a ChatGPT/Codex
subscription does not need an OpenAI API key here. Check it later with
`make auth-status`.

Device-code login is not enabled by default. On a remote or headless machine
where the localhost browser callback cannot be forwarded, invoke it explicitly
as a fallback:

```bash
docker compose run --rm codex-auth python -m hamroh.codex_login --device-code
```

If Docker says it cannot access `/var/run/docker.sock`, add your login user to
the Docker group, then log out and back in:

```bash
sudo usermod -aG docker "$USER"
```

Do not work around that with `chmod 666 /var/run/docker.sock` or `sudo make up`.

## Updating the framework

The framework lives as a git submodule under `framework/`, pinned to one exact
commit (detached HEAD — it doesn't track a branch). Two situations:

**You want the latest upstream framework.** Bump the pinned commit and commit the
new pointer:

```bash
git submodule update --remote framework   # fetch + check out latest upstream
git add framework && git commit -m "bump framework"
make up
```

`--remote` follows the submodule's tracked branch (the remote's default, `main`),
so you never hardcode a branch or merge into the detached HEAD by hand. On a
deployed server, `make update` does this for you (see "Updating a deployed
bot" below).

**You pulled this repo and the pointer moved** (someone else bumped it). A plain
`git pull` updates the superproject but leaves `framework/` on the old commit.
Sync it:

```bash
git submodule update --init --recursive   # --init is harmless if already initialized
make up
```

To do this automatically on every pull, set it once per machine:

```bash
git config --global submodule.recurse true
```

Either way, no framework files need to be copied — `system.md`,
`subagents.md`, and the skill runtime are rebuilt from the submodule at build
time (`make up`).

## Updating a deployed bot

On the server, update with one command:

```bash
make update   # commit the bot's new memories, pull, bump framework to latest, rebuild
```

The bot writes its memories into `memories/` but never commits them, and an
uncommitted memory file that also changed upstream makes `git pull` abort.
`make update` runs `scripts/commit-and-push.sh` first, which commits and pushes
those notes so the pull always goes through. Run the script by hand (or via
cron) anytime you want the server's memories pushed sooner.

`make update` also moves `framework/` to the latest upstream `main` and, if the
pointer moved, commits and pushes the bump — so every update runs the newest
framework without a separate bump step. Prefer a pinned, hand-picked framework
commit? Drop `--remote framework` and the `git diff --quiet framework || …`
line from the `update` target and bump manually as described above.

If you and the bot ever edit the same memory file, git keeps both sides' lines
(`merge=union` in `.gitattributes`) — no conflict markers to resolve by hand.
Skim the merged file if you both touched the same lines.

## How it works

Two layers:

- **`framework/`** — the hamroh engine, pinned as a git submodule to one exact
  commit. It ships the Dockerfile, the base system prompt, the skill runtime,
  and all the Python. You never edit it.
- **This repo** — your agent's identity. The build stacks it onto the framework:

```
agent image = hamroh-base (built from framework/) + your agent baked on top
├── /app/hamroh                engine                                  (framework)
└── /app/prompts/ (system.md,  ← COPY framework/prompts/               (from submodule)
       subagents.md, …)

mounted live at runtime:
├── /app/prompts/project.md      ◄── ./prompts/project.md
├── /app/skills/                 ◄── ./skills/ (custom skills, if any)
├── /app/plugins.json            ◄── ./plugins.json
├── /app/access.json             ◄── ./access.json
├── /app/default-reminders.json  ◄── ./default-reminders.json
├── /app/memories/               ◄── ./memories/
└── /app/data/                   ◄── ./data/
```

The image still contains fallback copies of `project.md` and `skills/`, but the
Compose deployment overlays them with this checkout. `project.md` is mounted as
one file so it cannot hide the framework's `system.md`; `skills/` is mounted as
a whole directory because this repo owns Shahnoza's complete custom skill set.
Prompts and the skill index are assembled at startup, so restart after editing
either one.

**When changes take effect:**

| Change | Applies |
|---|---|
| `access.json` | live (hot-reloaded) |
| `memories/` | live (read and written on demand) |
| `plugins.json`, `default-reminders.json` | on `docker compose restart agent` |
| `prompts/project.md`, `skills/` | on `docker compose restart agent` |

## What this repo owns

| File / dir | Configures | Git-tracked |
|---|---|---|
| `prompts/project.md` | Persona / developer-instruction overlay | ✅ |
| `skills/` | Shahnoza-specific skill tree | ✅ |
| `memories/` | The bot's memory — it reads and writes here | ✅ |
| `plugins.json` | Tools + MCP capability surface | ✅ |
| `default-reminders.json` | Scheduled reminders | ✅ |
| `access.json` | Access policy (DM / group) | ✅ |
| `Dockerfile` | Bakes the above onto the framework image | ✅ |
| `.env` | Bot token, owner id, optional model, MCP secrets | ❌ secrets |
| `data/` | SQLite, session state, logs | ❌ runtime |

`system.md` and `subagents.md` are **not** maintained in this repo — they come
from the framework at build time. `access.json` is the tracked source of truth;
owner commands `/allow`, `/deny`, and `/policy` edit it live, so commit the
change afterward if you want it preserved in Git.

## Customizing

- **Persona** → edit `prompts/project.md` (this checkout is already `Shahnoza`),
  then `docker compose restart agent`.
- **Skills** → drop a `skills/<name>/SKILL.md` folder, then restart the agent.
- **MCPs** → in `plugins.json` set an MCP `"enabled": true`, add its secret to
  `.env`, then `docker compose restart`. See `framework/docs/tools.md`.
- **Reminders** → add entries to `default-reminders.json`, then restart.
- **Memories** → add `memories/**/*.md` with `name` + `description` frontmatter
  (live, no restart).

## Installing extra packages

Need a system binary (ffmpeg, a font) or an extra Python dep for a custom tool?
Add it to the `Dockerfile` — it already builds `FROM hamroh-base`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN /app/.venv/bin/pip install --no-cache-dir yt-dlp
```

Then `make up`. Never edit `framework/` — it's the pinned submodule.
