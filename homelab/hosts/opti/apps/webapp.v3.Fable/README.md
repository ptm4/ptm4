# Pert's Pocket — v3.Fable

The third generation of the homelab dashboard, built side by side with the live v2 app.

| Folder (`homelab/hosts/opti/apps/`) | What it is |
|---|---|
| `webapp.v2.legacy/` | **The live site.** CI (`rpi-deploy.yml`) builds and deploys this to `/srv/docker/compose/webapp/` on rpi. Read-only reference for v3 work. |
| `webapp.v3.Astra/` | A parallel v3 built by another agent. Not ours — never edit it. |
| `webapp.v3.Fable/` | **This folder.** Not wired into CI until go-live is approved. |

Cross-agent coordination (claims, ports, issues) lives in `AgentComms.md` at the repo root.

## What changed from v2

- **Frontend rewritten in Svelte 5 + SvelteKit** (static-adapter SPA). The React/Vite app is
  gone from this folder; its reference copy is `webapp.v2.legacy/frontend/`.
- **Board engine is gridstack.js** (framework-agnostic, touch-first). Saved board documents
  from `/api/ui/boards/*` load unchanged — the client adapter maps the persisted
  `{i,x,y,w,h}` layouts onto gridstack nodes.
- **Design: "Fable synthesis" in gruvbox** — precision-dark structure (near-black, hairline
  borders, one hot accent), a live topology map as the hero, an ops-feed timeline. See
  `design/mockups/fable-synthesis.html` for the reference implementation of the palette.
- **Backend kept** (Fastify 5, CommonJS) with additive routes only: `/api/events` (SSE),
  `/api/incidents`, `/api/hosts`. Every pre-existing route keeps its exact response shape.
- **New sections**: `/topology`, `/feed`, `/incidents`, `/host/:name`, plus a new Home.
- **Streams as a product** (`/streams`): hls.js player with multiview + theater, the four station
  slots as pills, and a **guide** — HLTV's day feed joined with the Valve top-20 and the channel
  directory so every match carries an S/A/B tier and a one-tap "Watch" that picks a free slot
  (`GET /api/streams/guide`, `POST /api/streams/watch`). The directory comes from stream-station's
  `presets.json` (expanded to BLAST / ESL / PGL / HLTV organizers + popular CS2 streamers) merged
  with a built-in fallback (`backend/lib/stream-catalog.js`). The v1 player lives at `/legacy/streams/`.
- **Launchpad** (`/launchpad`): every web UI in the homelab (`backend/lib/services.js`, 31 entries)
  joined with the server-side link probes and container states → live health dots, search,
  favourites (persisted in `/api/ui/settings`), restart-from-tile for container-backed services.
- **Alert rules** (`backend/lib/rules.js`, `/api/rules`, Settings → Alert rules): thresholds on disk,
  pool, CPU, memory, temperature, load, host-down, container-down, pending updates, reboot-required
  and stalled stream slots, with a sustain window; evaluated every poller tick; hits become findings
  (source `rule:<id>`) so they reach the bell, `/incidents` and `/feed`.
- **Mobile**: bottom navigation (Home · Streams · Feed · Launch · More) so the phone use case is one tap.

## Layout

```
backend/          Fastify app (see backend/app.js for the ground rules)
frontend/         SvelteKit app → builds to frontend/dist (what backend/plugins/static.js serves)
frontend-legacy/  v1 vanilla app, served verbatim at /legacy/ + standalone pages
design/mockups/   the 17 v3 design candidates + fable-synthesis.html (chosen direction)
scripts/          post-deploy API smoke suite + baseline (deploy gate — grows at go-live)
```

## Local development (Windows dev PC, Node 25)

```
cd frontend
npm install
npm run dev          # http://localhost:5173 — /api proxied to the live rpi backend
npm run build        # svelte-check + vite build → dist/
```

The live rpi backend is v2 until go-live, so the v3-only routes (`/api/events` SSE,
`/api/incidents`, `/api/hosts`) 404 through that proxy and the UI degrades (polling pip,
"incidents unavailable", static host table). To exercise them, run the v3 backend locally
against seeded fixtures and point the proxy at it:

```
cd backend
npm install
node dev/seed-fixtures.js ../.dev-data          # writes agent-logs/, reports/, arch-data/
$env:AGENT_LOGS_DIR="$PWD\..\.dev-data\agent-logs"; $env:REPORTS_DIR="$PWD\..\.dev-data\reports"
$env:ARCH_DATA_DIR="$PWD\..\.dev-data\arch-data"; $env:WORKSPACE_DIR="E:\REPO\ptm4"
node server.js                                   # :3000 — vitals still come from the real agents
```

then write `http://127.0.0.1:3000` into `frontend/.proxy-target` (git-ignored; or set
`VITE_PROXY_TARGET`) and restart `npm run dev`. Delete the file to go back to the live rpi.

Backend tests: `cd backend && npm test` (the v2 parity suite plus `test/v3.test.js`).

## Process

Peter commits and pushes his own work. Nothing in this folder deploys until the go-live
step flips `rpi-deploy.yml` / `checks.yml` from `webapp.v2.legacy/` to here.
