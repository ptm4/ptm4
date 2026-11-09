# Discord bot fleet (on opti)

## Overview
A fleet of Discord bots runs as Docker containers on **opti** (moved off rpi with the rest of
the app tier on 2026-09-10). They all clone the original **weather bot** pattern.

- Defined in `homelab/hosts/opti/docker-compose.apps.yml` (the "Discord bot fleet" block);
  source for each bot in `homelab/hosts/opti/apps/<bot>/`.
- Deployed to `/srv/docker/compose/` on opti by `.github/workflows/opti-apps-deploy.yml`.
  Secrets come from `/srv/docker/compose/.env` on opti — not in git, never touched by CI.

## Bots / containers
- **discord-weather** — posts a daily 7AM ET weather report.
- **discord-healthdigest** — homelab health digest (reads `/srv/red/fs/ptm/agent-logs`).
  NOTE: the container is **`discord-healthdigest`**, NOT `discord-health`.
- **discord-jellyfin** — Jellyfin/media notifications.
- **discord-sports** — sports updates.
- **discord-hltv** — CS2/HLTV updates. NOTE: the container is named **`discord-hltv`**, NOT
  `discord-cs2`.
- **hltv-api** — not a bot: the HLTV scraper `discord-hltv` depends on. Its build context
  ships inside the bot's folder (`apps/discord-hltv/hltv-api`), so it deploys with it.

## Management
- Manage bots via the **webapp** (e.g. the #weather tab), **NOT** by editing files directly
  on opti — `/srv/docker/compose/` is a deploy target and the next CI run reverts it.
- The deploy workflow's **"Copy discord bots" step is load-bearing** — it must precede
  "Bring stack up", because compose references these build contexts. "Build and restart
  discord bots" then builds `hltv-api` first (discord-hltv depends on it).
- Peter declined rotating the Jellyfin token (leave it as-is).

## Gotchas
- Adding a new bot = clone the weather pattern, then wire it in **four** places in the repo:
  the service in `docker-compose.apps.yml`, its folder in `opti-apps-deploy.yml`'s `paths:`
  trigger, and the bot lists in both the "Copy discord bots" and "Build and restart discord
  bots" steps. Miss the `paths:` entry and edits to that bot never trigger a deploy.
