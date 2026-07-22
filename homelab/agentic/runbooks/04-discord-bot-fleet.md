# Discord bot fleet (on rpi)

## Overview
A fleet of Discord bots runs as Docker containers on **rpi**. They all clone the original
**weather bot** pattern.

## Bots / containers
- **discord-weather** — posts a daily 7AM ET weather report.
- **discord-health** — homelab health notifications.
- **discord-jellyfin** — Jellyfin/media notifications.
- **discord-sports** — sports updates.
- **discord-hltv** — CS2/HLTV updates. NOTE: the container is named **`discord-hltv`**, NOT
  `discord-cs2`.

## Management
- Manage bots via the **webapp** (e.g. the #weather tab), **NOT** by editing files directly.
- The deploy-workflow **bot-copy step is load-bearing** — don't bypass it when adding a bot.
- Peter declined rotating the Jellyfin token (leave it as-is).

## Gotchas
- Adding a new bot = clone the weather pattern via the deploy workflow.
