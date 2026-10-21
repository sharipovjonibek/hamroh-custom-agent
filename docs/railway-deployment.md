# Put your agent into production on Railway

This is the easy, safe path for moving a working agent from an Ubuntu laptop
to Railway. You do not need a Claude account, an OpenAI API key, or device-code
login. Railway will reuse the bot's existing URL-based ChatGPT login through a
private persistent volume.

Allow roughly 20–40 minutes. Most of that time is Railway building the Python,
Codex, and Chromium image.

For dependable always-on use, the Railway **Hobby** plan is recommended. The
Free plan is limited to 0.5 GB RAM per service, which can be tight when the
agent launches Chromium. Hobby currently has a $5 monthly minimum, with the
first $5 of resource usage included; set a spending limit after deployment.

## Before you start

You need:

- The local agent already working with `make up`.
- The `hamroh-custom-agent` repository visible in your GitHub account.
- A Railway account connected to that GitHub account.
- Your Telegram bot token and numeric Telegram user ID.
- The laptop online for the one-time login transfer.

Important safety rules:

- Never paste or upload `auth.json` to GitHub, Telegram, chat, a ticket, or a
  Railway variable. It is password-equivalent.
- Never run the local and Railway copies at the same time. Telegram
  allows only one long-poller, and two copies can also rotate the same Codex
  refresh token and revoke one another.
- Use `make down`, never `docker compose down -v`. The `-v` form deletes the
  local bot's saved ChatGPT login.
- After the production cutover, keep the local bot stopped. While Railway is
  active, do not run `make up`, `make auth`, `make auth-status`, or Codex
  logout locally. Those commands can refresh or revoke the copied login.

If this Railway deployment was created with an older, person-specific guide,
rename its service to `agent` and its volume to `agent-data` before using the
transfer commands below. Renaming these labels does not erase the volume.

## Part 1 — Create the agent in Railway

1. Open [Railway](https://railway.com/) and sign in with GitHub.

2. Click **New Project** → **Deploy from GitHub repo**.

3. Select **hamroh-custom-agent**. If Railway asks for GitHub permission,
   approve access to this repository.

4. Railway will normally name the new service `hamroh-custom-agent`. Open that
   service's **Settings**, change its name to **agent**, and save. This stable,
   generic service name does not change when you rename the agent.

5. Choose **Add Variables** rather than immediately deploying.

6. Open the service's **Variables** tab, choose **Raw Editor**, and paste this
   block. Replace the first three values:

   ```text
   AGENT_NAME=choose_your_agent_name
   TELEGRAM_BOT_TOKEN=paste_your_BotFather_token_here
   HAMROH_OWNER_ID=paste_your_numeric_Telegram_user_ID_here
   HAMROH_PROVIDER=codex
   HAMROH_EFFORT=high
   HAMROH_BROWSER_HEADLESS=true
   ```

7. Save the variables. Open the menu for `TELEGRAM_BOT_TOKEN` and choose
   **Seal**. Do not add `OPENAI_API_KEY`, Claude variables, or Codex tokens.

8. Return to the project canvas. Right-click an empty area and choose
   **New Volume**. Connect it to the `agent` service and enter this exact
   mount path:

   ```text
   /data
   ```

   After the volume appears, open its settings and name it exactly:

   ```text
   agent-data
   ```

   This one volume stores the database, conversation session, memories,
   persona edits, skills, configuration, logs, and renewable Codex login.

9. Open the `agent` service settings and check these items:

   - Source branch: `main`
   - Replicas: `1`
   - Serverless/App Sleeping: **Off**
   - Public domain: **none**
   - Healthcheck URL: **none**

   The agent is a background Telegram worker, not a website. It therefore
   needs no `PORT`, domain, or HTTP healthcheck.

10. Review the staged changes and click **Deploy**. The first build can take a
   while because Chromium is included.

11. Open **Deployments** → the current deployment → **View Logs**. When the
    build finishes, this message is expected:

    ```text
    WAITING_FOR_CODEX_AUTH
    ```

    This is not a failure. The agent is safely waiting for the one-time private
    login transfer.

## Part 2 — Install and connect the Railway command

Open Terminal on the Ubuntu laptop and run:

```bash
cd /path/to/hamroh-custom-agent
bash <(curl -fsSL railway.com/install.sh)
exec bash
```

Confirm it installed:

```bash
railway --version
```

Now sign in. This opens a normal browser URL:

```bash
railway login
```

Link this folder to the project you just created:

```bash
railway link
```

When prompted, choose your Railway workspace, your project, the `production`
environment, and the `agent` service. Then explicitly link the service that
owns the volume:

```bash
railway service link agent
```

Check the link:

```bash
railway status
```

The displayed project and environment should be yours, and the service should
be `agent`.

## Part 3 — Make the production cutover

First stop the local bot while preserving its login:

```bash
make down
```

Now run the safe one-command transfer:

```bash
make railway-auth-upload
```

The command does four things without displaying the credentials:

1. Verifies the exact `agent-data` volume belongs to the `agent` service
   and is mounted at `/data`.
2. Refuses to continue if the local agent is still running, then performs a
   fresh account check without displaying credentials.
3. Uploads the login as `/codex/auth.json.next`; Railway validates it and
   atomically promotes it to `/codex/auth.json`.
4. Deletes the temporary mode-`600` export and any exact interrupted-export
   leftovers immediately.

The final output should include:

```text
Codex login staged on the verified <your agent name> volume.
Railway will validate it and atomically promote it to /codex/auth.json.
The temporary local export has been deleted.
```

Within about 10 seconds, the waiting Railway container should notice the file
and continue automatically. If it does not, click **Restart** on the service.

## Part 4 — Confirm the agent is live

In Railway logs, look for these messages:

```text
persistent state ready at /data
Codex runtime ready
hamroh is live
```

Then open Telegram and send the bot:

```text
Introduce yourself
```

If it replies normally and identifies itself with the value you set in
`AGENT_NAME`, production is working. Remove the duplicate login from the
laptop without logging out:

```bash
make railway-auth-retire-local
```

Type `RETIRE` when asked. Leave the local Docker bot stopped from now on. If a
future recovery is needed, follow the maintenance procedure below before
authenticating locally again.

## Recommended production settings

After the smoke test:

1. Open the `agent` service → **Backups** and enable a daily backup.
2. Enable MFA on both Railway and GitHub.
3. Keep Railway workspace membership restricted. Volume backups contain the
   Codex login as well as the agent's memories.
4. Configure a Railway spending alert/limit that suits you.
5. Do not create a staging or PR copy with the same Telegram token or Codex
   login.

GitHub pushes to `main` will automatically deploy a new image. The volume stays
attached, so the database, login, memories, skills, access policy, reminders,
and the agent's own persona edits survive each deploy. A service with a volume
can have a short interruption during redeploy; that is expected.

The persistent copies deliberately win over image seeds. Therefore, a later
Git commit that changes an existing persona, skill, memory, access file,
reminder, or plugin does not overwrite production. Make those changes through
the agent or a controlled volume edit; seed changes apply only to a new empty
volume. Never wipe the production volume just to apply a seed change.

## Troubleshooting

For stale Codex versions, the `_pending_turn_notifications` error, or a model
request that requires a newer CLI, use [the runtime upgrade guide](railway-runtime-upgrade.md).
It includes image provenance, dependency checks, and a ChatGPT-authenticated
`gpt-5.6-sol` smoke turn on the existing volume.

### `railway: command not found`

Start a fresh Terminal, or run:

```bash
export PATH="$HOME/.railway/bin:$PATH"
railway --version
```

### `volume files` is not a Railway command

Upgrade the CLI:

```bash
railway upgrade
```

### Docker says permission denied

Confirm the current login sees the Docker group:

```bash
groups
```

If `docker` is listed but the error remains, log out of Ubuntu and sign back
in. Do not use `chmod 666 /var/run/docker.sock` and do not run `sudo make`.

### Upload says `auth.json.next` already exists

The earlier upload may still be finishing. Wait 10 seconds and check logs for
`STAGED_CODEX_AUTH_READY`. If the staged file is invalid and the logs keep
rejecting it, remove only that staging file and retry:

```bash
railway volume files --volume agent-data delete \
  /codex/auth.json.next --yes
```

### Logs keep showing `WAITING_FOR_CODEX_AUTH`

Check that the volume mount path is exactly `/data`, then confirm only the
filename (not its contents):

```bash
railway volume files --volume agent-data list /codex
```

You should see `auth.json`. If it is absent, rerun `make railway-auth-upload`.

### Telegram reports another poller or conflict

The local bot is probably still running. Stop it:

```bash
make down
```

Then restart the Railway service. Keep exactly one production replica.

### Codex says the refresh token was revoked

Do this only when reauthentication is actually required:

1. In Railway, open `agent` → **Variables**, add this value, and deploy the
   staged change:

   ```text
   HAMROH_MAINTENANCE=true
   ```

2. Wait until the active deployment logs show:

   ```text
   MAINTENANCE_READY
   ```

   Maintenance keeps the deployment available for Railway volume transfer but
   does not start Telegram or Codex. The upload command checks a private
   readiness marker created at this point, so it safely refuses if you try too
   early.

3. Keep the local Telegram worker stopped. Run `make auth` and complete the
   normal browser-URL login. Do not choose device-code login.

4. Run the same safe transfer command:

   ```bash
   make railway-auth-upload
   ```

5. Wait for `STAGED_CODEX_AUTH_READY` in Railway logs. Then delete only the
   `HAMROH_MAINTENANCE` variable and deploy that staged change.

6. Test Telegram again. When the agent answers, run
   `make railway-auth-retire-local` and type `RETIRE`.

This sequence is important: Railway volume commands need an active deployment,
while maintenance prevents the old and new Codex sessions from refreshing the
same login at once.

## What the production files do

- `Dockerfile.railway` builds the Hamroh revision in `framework-revision.txt` without
  depending on the laptop-only `hamroh-base` image or a checked-out submodule.
- The final build and bootstrap verify both Codex distributions, the bundled
  executable, the worker import, and the fetched framework revision.
- `railway.json` selects that image and prevents overlapping Telegram workers.
- `scripts/railway_bootstrap.py` seeds missing volume files once, preserves
  every later edit, validates and atomically promotes staged credentials,
  supports safe maintenance, and starts the configured agent.
- `make railway-auth-upload` transfers the existing URL-authenticated Codex
  login without printing or committing it.

Official reference links:

- [Railway CLI](https://docs.railway.com/cli)
- [Railway variables and sealed secrets](https://docs.railway.com/variables)
- [Railway volumes](https://docs.railway.com/volumes)
- [Railway volume limits](https://docs.railway.com/volumes/reference)
- [Railway plans and resource limits](https://docs.railway.com/pricing/plans)
- [Railway CLI volume file transfer](https://railway.com/changelog/2026-05-29-cli-volumes)
- [OpenAI authentication](https://learn.chatgpt.com/docs/auth.md)
- [ChatGPT-managed authentication for trusted automation](https://learn.chatgpt.com/docs/auth/ci-cd-auth)
