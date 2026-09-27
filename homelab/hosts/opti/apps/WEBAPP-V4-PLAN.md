# Pertal — webapp v4 plan

Status: **discovery done 2026-09-27** (two rounds with Peter, mockups in that session).
Rollout: **big-bang rebuild** into a new `webapp.v4.Pertal/`, v3.Fable stays live until cutover.
Goal in Peter's words: *simple and effective like v1, with a better design — strong and reliable.*

## Decisions

| Topic | Decision |
|---|---|
| Name | **Pertal** (Pert + portal) |
| Audience | Peter at desk, on phone, remote over WireGuard; AI agents building on it |
| Primary device | **Phone first**; desktop gets the dense version of the same pages |
| Look | Dense ops console. Borrow Azure-portal *ideas* (resources, blades, command bar, breadcrumbs, Ctrl K) — not its looks |
| Palette | **Pure gruvbox** (dark + light) by default; Fable's GitHub Dark/Light kept as a switchable alternate (Settings → Appearance). Rule kept: *healthy is quiet, colour means something wants you* |
| Navigation | Side drawer on phone (Azure-style), left rail on desktop, Ctrl K everywhere |
| Control | **Full control**; confirm tap for risky actions only (reboot, stop, update, delete) |
| Auth | None — LAN + WireGuard only. Every action still lands in the audit trail |
| opti down | Installed PWA caches its shell; if opti stops answering it reads Uptime Kuma on noblenumbat directly and says so. No extra server; rpi stays DNS-only |
| Stack | Fastify + SvelteKit (Fable's), shipped as a **baked image** — no `npm install` at start |
| Claude assistant | **Out of v4 scope.** Peter plans a local-model host; revisit when it exists (see "Local model" below) |
| Downloads | Drop a `.torrent` / magnet → qBittorrent (via gluetun) → **one drop folder on opti** |
| Requests | **Deploy Jellyseerr** (opti app tier — it has a DB) and show its queue in Pertal |
| Status extras | Weather, Google Calendar, Google Home devices, package tracking, CS2 matches today, NBA scores |
| Show-off | Screenshot-worthy is enough — no public page |
| Discord bots | **Consolidated as part of v4**: shared `bot_common.py`, real health, each bot is a resource |
| Old versions | Harvest from Astra (`backend/astra/snapshot.js`, fixture/demo mode, `guide.js`), then `git tag` and **delete both `webapp.v3.Astra/` and `webapp.v2.legacy/`** |

## Pain → design answer

| v3 pain | v4 answer |
|---|---|
| Goes down after deploys | Baked image + container healthcheck; deploy starts the new container and swaps only when healthy; PWA keeps showing the last snapshot during any restart |
| Stale or wrong data | Pages read **only** from a server-side snapshot cache. Every snapshot carries its age; past its refresh window it greys out instead of pretending |
| Buttons don't work | The 2026-09-27 audit trail had 19 jobs, all ok — failing buttons never became jobs. v4: **every** button goes through one action pipeline (queued → running → ok/failed + reason), failures included, visible in Activity. A route smoke test clicks every action against fixtures |
| Not as reliable as it should be | Global request timeout; no page ever awaits an upstream; one source dying greys one card |

## Information architecture

Drawer / rail, top to bottom:

1. **Status** — the landing page: hosts up/down, open issues, then the home strip (weather,
   calendar, CS2, NBA, packages, Google Home).
2. **Resources** — hosts, containers, bots, timers, streams. Every resource gets the same page:
   header + status, **command bar**, tabs *Overview · Activity · Logs · Metrics · Settings*.
3. **Topology** — live map; click a node → its resource page.
4. **Activity** — one feed: actions, alerts, deploys, container changes, failures.
5. **Logs** — global view (per-resource logs live in the Logs tab).
6. **Downloads** — drop zone, queue, VPN/port state.
7. **Requests** — Jellyseerr queue.
8. **Asset Library** — `E:\Assets` on the workstation, browsed live: folder tree, thumbnails,
   search, models in the library's own 3D inspector (`homelab/hosts/ptm/asset-server`).
9. **Streams**, **Launchpad**, **Reports**, **Settings** (maintenance holds, jobs).

Gone as pages: Home, Monitor, Control center (→ Status + command bar), Metrics (→ tab),
Docs/Database (→ Ctrl K search over homelab-db), Discord bots (→ resources), Local LLM.

## Architecture

- **Snapshot cache** — one poller per source (hl-arch-agent ×3, homelab-db, Kuma, Pi-hole,
  qBittorrent, Jellyfin/Jellyseerr, bots, weather/calendar/etc.), each with its own interval +
  timeout, each stored as `{data, fetched_at, ok, error}`. SSE pushes "snapshot X changed".
- **Action pipeline** — single `POST /api/actions/:kind` → job with steps, audit, SSE progress.
  Risky kinds require a `confirm: true` the UI only sends after the confirm tap.
- **Resource model** — one registry (id, type, host, links, actions, snapshot keys) drives the
  drawer, search, topology and resource pages; adding a resource is data, not a new page.
- **PWA fallback** — service worker caches the shell; on API failure it probes Kuma's status API
  on noblenumbat (CORS / small proxy to confirm) and renders an "opti unreachable" screen.
- **Deploy** — `opti-apps-deploy.yml` builds the image, runs lint + svelte-check + smoke, starts
  the new container, waits for healthy, then swaps nginx upstream.

## Integration notes / research needed

- **Downloads drop folder**: qBittorrent category `pertal-drop` with its own save path; decide
  whether it lands via the existing `media-import` timer into `//opti/red/ptm/…` or a direct CIFS
  path. Upload through qBittorrent's API from Pertal (qbt creds → host-side secret, not repo).
- **Google Calendar**: simplest is the calendar's private ICS URL (read-only, no OAuth).
- **Google Home devices**: no official local API — needs research (Home Assistant bridge?).
- **Package tracking**: needs a tracking API (e.g. 17TRACK/AfterShip) or mail parsing — research.
- **CS2 / NBA / weather**: reuse the bots' sources (hltv-api, ESPN, Open-Meteo) via `bot_common`.

## Local model (for a later assistant)

Peter is considering turning **rpi** into a local-AI box, possibly dropping Pi-hole. Runbook 10's
four-part test rejects an LLM on the DNS box (user-facing app, far over 500 MB / a fraction of a
core, and an OOM there is a LAN-wide DNS outage). Options when this comes up: keep rpi as DNS and
put the model on a separate box (opti has 31 GB RAM but an Ivy Bridge CPU; the gaming PC's 4070 Ti
is fastest but not always on; the S10 already runs llama.cpp); or move DNS off rpi first —
dropping Pi-hole entirely also drops the `*.lan` records (webapp.lan, jellyfin.lan, …) the router
cannot serve. Decide before building an assistant.

## Build order (big-bang, but in this sequence)

Progress 2026-09-27: steps 0–4 and 6 built; live side by side at https://webapp.lan:8444.
Code: `webapp.v4.Pertal/` — backend 12/12 tests, svelte-check 0/0, CI (`checks.yml`) builds and
tests it on every push. The `add-to-webapp` skill now documents Pertal (v3 = fixes only).

0. ✅ Skeleton, Dockerfile (baked image + healthcheck), CI checks. ⬜ prettier/eslint.
1. ✅ Resource registry + snapshot cache + Status page. Needed **hl-arch-agent v0.7.0**
   (`GET /containers`, live `docker ps`) — installed on opti/rpi/noblenumbat 2026-09-27
   (backups at `/usr/local/bin/hl-arch-agent.py.bak-0.6.0`). Before it, container state came
   only from the agents' *daily* fragment push — up to 24h stale, a root cause of v3's
   "stale or wrong data".
2. ✅ Resource pages + action pipeline + Activity + Ctrl K search + job tray + confirm dialog.
   v3's job audit is read from the shared `arch_data` volume, so it carries over.
3. ✅ Logs (tab + page; **hl-arch-agent v0.8.0** `GET /logs`, token-gated, installed on all 3
   hosts 2026-09-27), Metrics tab (last hour from Pertal, 24h–90d from homelab-db), Topology,
   Reports, Launchpad (live reachability), Settings. ✅ Streams (v3's guide rules ported
   unchanged — VRS ranks, no organizer fallback, stale feed can't claim live; hls.js player,
   multiview, keep-alive).
   ✅ **Side-by-side deploy wired**: compose service `pertal` (profile, built on opti),
   nginx-webapp serves it at **https://webapp.lan:8444**, deployed LAST by
   `opti-apps-deploy.yml` so a failed Pertal build can't block v3. Image trial-built and
   health-checked on opti.
   **Live since 2026-09-27 at https://webapp.lan:8444** (first deploy green).
4. ✅ Status extras: weather (Open-Meteo, location from the discord-weather config), NBA
   (ESPN, teams from the discord-sports config), CS2 today (hltv-api), Google Calendar via
   `PERTAL_CALENDAR_ICS` (secret iCal URL; own small ICS parser with recurrence). ⬜ Google
   Home devices and package tracking — need research (no official local API / a paid API).
   ✅ Downloads page: drop .torrent files / magnets → qBittorrent (category `pertal`, VPN'd),
   queue with pause/resume/remove, gluetun VPN card. qBittorrent needs no creds from Pertal
   (its WebUI whitelists the LAN — call `192.168.1.6:8081`). Finished `pertal` torrents are
   moved by `noblenumbat/media-import.sh` into **opti `/srv/red/fs/ptm/Downloads`**
   (`\\opti\red\ptm\Downloads`), mounted on noblenumbat at `/mnt/opti-downloads` (fstab CIFS
   automount, added 2026-09-27).
   ✅ Seerr (Jellyseerr's successor, `seerr/seerr:v3.4.1`) in compose at `opti.lan:5055` +
   Requests page (approve/decline as jobs). ⬜ Peter: run Seerr's setup wizard, then
   `SEERR_API_KEY` in `/srv/docker/compose/.env`.
   ✅ Topology is a flowing diagram (`TopologyDiagram.svelte` + `topology-layout.ts`): hosts
   as lanes, services as cards, typed edges (network/DNS/storage/media/VPN/apps/monitor),
   broken edges go red. ✅ Launchpad moved from the rail to a top-bar Apps button.
5. ⬜ Bot consolidation (`bot_common.py`, real `/health`, bots as resources).
6. ✅ Offline shell: service worker caches the app shell only; with opti gone the installed
   app opens and says "Can't reach opti" with a Kuma link. SSE self-heals: reconnects after a
   502 (deploys) and a 15s ping + 45s watchdog catches a proxy holding a dead stream open.
7. Cutover: CI path filter → v4, nginx → v4; tag `webapp-v3-fable-final`; delete Fable after two
   quiet weeks. Harvest Astra first, then tag + delete Astra and v2.legacy. The skills already
   describe Pertal (2026-09-27) — at cutover just change `:8444` → `:8443` there and drop the
   v3 section / fold `add-webapp-widget` into `add-to-webapp`.
   Cutover gotchas already known:
   - v3 ran as root, so `arch_data` files are root-owned; Pertal runs as `node` (uid 1000).
     `chown -R 1000:1000` the volume's `_data` once, or appends to the audit trail fail.
   - Pertal env: `HL_ARCH_INGEST_TOKEN` (agent actions + ingest), `HOMELAB_DB_URL`,
     `HL_DB_TOKEN`; do NOT set `PERTAL_ACTIONS=dry` in prod.
   - nginx: `/api/events` needs `proxy_buffering off` + long read timeout (it's SSE).
   - The agents' ingest URL stays `https://webapp.lan:8443/api/architecture/ingest` —
     Pertal serves the same route.

## Open questions

- ~~Palette~~ — answered: gruvbox default, GitHub Dark kept as the switchable alternate.
- Where does the local model live (see above) — only matters once an assistant is back in scope.
