---
name: add-to-webapp
description: Add a page, route, tab, or API endpoint to the homelab dashboard at webapp.lan ("Pert's Pocket", v3.Fable on opti) — dashboards, reports, diagrams, tools. Use when the user asks to add/publish/put something on the web app, the dashboard, webapp.lan, or "the rpi web app" (old name — it runs on opti now), or to change what the dashboard shows.
---

# Add something to the homelab webapp

The dashboard is **webapp.v3.Fable**: a **Fastify 5 (CommonJS) backend** serving a
**Svelte 5 + SvelteKit static SPA** (adapter-static, `ssr = false`), with the v1 vanilla
app still served verbatim at `/legacy/` and a few standalone pages beside it.

| | |
|---|---|
| **URL** | `https://webapp.lan:8443/` (self-signed cert — expect a warning). `webapp.rpi.lan` still resolves but names the wrong host; don't use it in new work. |
| **Repo source** | `homelab/hosts/opti/apps/webapp.v3.Fable/` — edit here, this is authoritative |
| **Runs on** | **opti**, not rpi (app tier moved 2026-09-10; rpi is DNS-only) |
| **Deployed to** | `/srv/docker/compose/webapp/` on opti, bind-mounted into the container at `/app` |
| **Container** | `webapp` (`node:lts-alpine`, working dir `/app/backend`, runs `npm install --omit=dev … && node server.js` on `:3000`) |
| **Reverse proxy / TLS** | container `nginx-webapp` publishes `${OPTI_IP}:8443 → 443`; config is `homelab/hosts/opti/apps/nginx-wg.conf`, certs are `/srv/red/fs/ptm/certs/webapp.rpi.lan{,-key}.pem` on opti |
| **Compose** | `homelab/hosts/opti/docker-compose.apps.yml` (deployed as `/srv/docker/compose/docker-compose.yml`) |
| **Not deployed** | `webapp.v2.legacy/` (the old React/Vite app — rollback target, frozen, don't edit) and `webapp.v3.Astra/` (someone else's rewrite, never edit) |

`homelab/hosts/opti/apps/webapp.v3.Fable/README.md` predates go-live in places (it still
says v2 is live and mentions `rpi-deploy.yml`); the workflow files below are the truth.

**Adding a card/tile/panel is the other skill** — see
[`add-webapp-widget`](../add-webapp-widget/SKILL.md). Use this skill for a page, a
standalone view, or an API route.

## Layout

```
webapp.v3.Fable/
  backend/app.js            buildApp() — every route registered here, with its prefix
  backend/server.js         the only thing that listens (:3000, 0.0.0.0)
  backend/routes/*.js       one Fastify plugin per /api/<prefix>
  backend/plugins/          event-bus (SSE), pollers (vitals, feed, monitor), jobs, static.js
  backend/lib/              paths.js (dir resolution), upstream.js (proxyJson), jobs.js, services.js, …
  backend/test/             node --test suites using fastify.inject() (parity, v3, monitor-stream)
  frontend/src/routes/      SvelteKit file routes (+page.svelte per page)
  frontend/src/lib/         api/ (client + TanStack queries), components/, widgets/, theme/, nav.ts
  frontend-legacy/          v1 app at /legacy/ + standalone pages (architecture/, agents/, agentic/, samba/)
  scripts/smoke-api.mjs     post-deploy API smoke + smoke-baseline.json
```

## 1. Decide the shape

| Shape | Use when | Where |
|---|---|---|
| **SvelteKit route** | The default for anything new — gets the rail, topbar, theme, query client | `frontend/src/routes/<name>/+page.svelte` (+ `_parts/` for page-private components) |
| **Standalone page** | Self-contained doc with its own layout/canvas that should also open without the SPA (diagrams, maps) | `frontend-legacy/<name>/index.html`, plus `<name>` in `LEGACY_DIRS` in `backend/plugins/static.js` |
| **API route only** | Just exposing data (proxying a service, reading a file) | `backend/routes/<name>.js` + register in `backend/app.js` |

Existing standalone pages: `architecture/` (data from `homelab/tools/architecture/build-arch-data.py`),
`agents/`, `agentic/`, `samba/` (editor for opti's `[red]` share — proxies the dispatcher's
`/samba/*`). Notes is a separate container at `/notes/`. The v1 streams player is `/legacy/streams/`.

`/dashboard` is 308-redirected to `/monitor` by the backend; don't reuse that path.

## 2. Build it

### SvelteKit page

1. Create `frontend/src/routes/<name>/+page.svelte`. Svelte 5 runes (`$props`, `$state`,
   `$derived`). Small, current examples: `routes/docs/+page.svelte`, `routes/logs/+page.svelte`;
   tabbed pages keep tab state in `?tab=` (see `routes/cockpit/+page.svelte`).
2. Data: reuse a hook from `frontend/src/lib/api/queries.ts` (or `fleet.ts`, `incidents.ts`,
   `rules.ts`, `services.ts`, `streams.ts`) before writing a new one. New fetches use
   `get`/`post` from `$lib/api/client` inside TanStack `createQuery(() => ({ … }))`; types go in
   `lib/api/types.ts`. Always render a loading and an error state.
3. Navigation lives in **`frontend/src/lib/nav.ts`** — one source for the rail, command
   palette (CmdK), topbar title and mobile menu. Its rule: a rail entry is "a place you go,
   not a view of somewhere you already are". Otherwise add a tab to an existing page, or
   put it in `LEGACY_PAGES` (reachable from Settings + CmdK). Add a `TITLES`/`SUBTITLES`
   entry if the topbar needs a better name.
4. Actions that change a host (restart, reboot, update) go through the jobs system
   (`backend/lib/jobs.js`, `/api/jobs`), which gives stepped progress and an audit trail —
   don't fire a bare POST and a toast.

**Theme.** `+layout.svelte` imports `$lib/theme/tokens.css`, `app.css`, `board.css`,
`pages.css` — a route inherits all of it; never re-declare palette hexes. Tokens:
`--bg --bg-inset --surface --surface-2 --surface-3 --border --border-2 --ink --ink-2 --ink-3
--accent --brand --ok --warn --severe --crit` (+ variants), `--sans`/`--mono`. The rule
that drives the palette: **nothing that is fine gets a colour** (`--ok` is deliberately
grey). Theme is `data-theme` on `<html>`, localStorage key `arch-theme`
(`lib/stores/theme.svelte.ts`).

### Standalone page

Keep CSS/JS inline, link `<link rel="stylesheet" href="/tokens.css" />` (served from
`frontend-legacy/tokens.css`), include a way back (`<a href="/">`), and put facts in a
sibling `data.json` rather than markup. **Caveat:** `frontend-legacy/tokens.css` is a
*separate, older palette* (GitHub Dark Dimmed, green = good) from the SPA's
`frontend/src/lib/theme/tokens.css` — they are not synced. Another reason to prefer a
SvelteKit route.

`build-arch-data.py`'s `DEFAULT_OUT` still points at `webapp.v2.legacy/…/architecture/data.json`;
the deployed copy is `webapp.v3.Fable/frontend-legacy/architecture/data.json`, so pass
`--out` to that path when regenerating.

If you produce a chart or diagram, load the **`dataviz` skill** first and run its palette
validator (`--pairs all` for a diagram).

### Backend route

A route is a Fastify plugin; paths are relative to the prefix it's registered under:

```js
// backend/routes/thing.js
module.exports = async function thingRoutes(app) {
  app.get('/status', async () => ({ ok: true }));
};
```

```js
// backend/app.js, beside the others (before the bare-/api dashboard routes)
await app.register(require('./routes/thing'), { prefix: '/api/thing' });
```

Ground rules (from the header of `backend/app.js` — read it):

- Proxy other services with `proxyJson` from `backend/lib/upstream.js`; `routes/hldb.js` is
  the short example, including degrading to a **503 with a reason** when the upstream is
  down or unconfigured. Upstream URLs/tokens come from env vars set in the compose file.
- Each route owns its upstream timeout and it must fit under nginx's caps: **60s default**,
  240s on `/api/agents` and `/api/llama`, 1h on `/api/events` (SSE). A new slow route needs
  its own `location` block in `nginx-wg.conf`.
- No response schemas on routes that had a legacy client (serializers strip undeclared
  keys). New routes may use full schemas.
- **`/api/health` is taken** (the webapp's own healthcheck) — hence `/api/healthdigest`.
- Keep a response's top-level key set **constant** (use `null`, not an absent key) — the
  smoke gate compares keys.

**Directories** resolve through `backend/lib/paths.js` (env override → container mount →
repo dev path). Container mounts on opti (`docker-compose.apps.yml`):

| Container path | Host source (opti) | |
|---|---|---|
| `/app` | `/srv/docker/compose/webapp` | the deployed app (rw) |
| `/agent-logs` | `/srv/red/fs/ptm/agent-logs` | `:ro` — collector JSON (`homelab-doctor-latest.json`, `hardware-latest.json`, `agents-state.json`, …) |
| `/reports` | `/srv/red/fs/ptm/security-reports` | `:ro` — security agent reports |
| `/workspace` | `/srv/red/fs/ptm/repo/ptm4` | `:ro` — **not a git checkout**: a `homelab/` snapshot rsynced by `.github/workflows/opti-deploy.yml` on push |
| `/arch-data` | named volume `arch_data` | **the only writable data mount** — fragments, vitals, `ui/` state, `audit/` |

These are local pool paths now (they were CIFS mounts when the app ran on rpi). The pool
is a single disk; if a read fails, render "unavailable", not a blank page.

**Check existing read-models before writing a new one:**

| Endpoint | Gives you |
|---|---|
| `/api/containers`, `/api/timers`, `/api/activity`, `/api/trends`, `/api/linkcheck` | fleet containers (state, image, `update_available`), systemd timers, unified activity feed, daily pool/disk series, link probes |
| `/api/vitals`, `/api/vitals/:host` | live rollup + ~30s-resolution CPU/mem/temp/net series (`?range=1h…48h`) |
| `/api/hosts`, `/api/incidents`, `/api/services` | fleet model, open incidents, the Launchpad service catalog joined with health |
| `/api/monitor/*` | per-host btop-style snapshot/history/processes |
| `/api/events` | SSE push (vitals, containers, jobs) — `lib/api/sse.svelte.ts` |
| `/api/pihole/*` | Pi-hole on rpi (`PIHOLE_URL` = `http://192.168.1.10`) |
| `/api/hldb/*` | **anything historical** — homelab.db on opti: `metrics`, `changes`, `search`, `status`, `dataplane`, `host/:host`, `schema`, `docs`, `POST query` |

The file-backed read-models only know *now* (the files are overwritten). For history,
cross-collector correlation or search, **prefer homelab.db via `/api/hldb`** — see
`homelab/tools/homelab-db/README.md`. Collector cadence: doctor and network every 30 min,
hardware and software once a day — use `/api/vitals` for live numbers.

## 3. Checks and smoke contract

**Every new route goes into `scripts/smoke-api.mjs`'s `MANIFEST` in the same change**,
with every status that is legitimate in some environment (`[200, 503]` for an upstream that
may be absent off-box; mutating routes probed only with deliberately invalid bodies so a
4xx proves the route exists). Update `scripts/smoke-baseline.json` with its top-level keys
(regenerate with `--capture`). The deploy runs the smoke inside the container with
`--compare`, and fails if a status isn't allowed or a 200 response lost keys vs baseline.

`.github/workflows/checks.yml` (GitHub-hosted, on push touching `homelab/hosts/**` etc.)
runs for v3.Fable: `node --check` over every backend `.js` + the smoke script,
`npm test` in `backend/`, and `npx svelte-check --threshold warning` + `npm run build` in
`frontend/`. Add a `fastify.inject()` test in `backend/test/` for non-trivial routes.

## 4. Verify locally before handing off

**This Windows workstation has Node** (v25; `node_modules` already installed in both
`backend/` and `frontend/`). tux has none; opti has none on the host (only inside the
`webapp` container, v24); noblenumbat has v24 if you need Linux.

```powershell
cd E:\REPO\ptm4\homelab\hosts\opti\apps\webapp.v3.Fable
cd backend;  npm test                                   # parity + v3 + monitor suites
cd ..\frontend; npm run check; npm run build            # svelte-check + vite build → dist/
```

Run against fixtures (no LAN needed), then smoke it:

```powershell
cd backend
node dev/seed-fixtures.js ..\.dev-data
$env:AGENT_LOGS_DIR="$PWD\..\.dev-data\agent-logs"; $env:REPORTS_DIR="$PWD\..\.dev-data\reports"
$env:ARCH_DATA_DIR="$PWD\..\.dev-data\arch-data"; $env:WORKSPACE_DIR="E:\REPO\ptm4"
node server.js                                          # :3000 (serves frontend/dist if built)
node ..\scripts\smoke-api.mjs --base http://127.0.0.1:3000 --compare ..\scripts\smoke-baseline.json
```

For UI work, `npm run dev` in `frontend/` (http://localhost:5173) proxies `/api` and the
standalone paths to the target in `frontend/.proxy-target` / `VITE_PROXY_TARGET` — default
is the live opti backend (`https://192.168.1.11:8443`); `http://127.0.0.1:3000` for the local
one. Load the page and check the browser console — a JS error is invisible to `curl`.

## 5. Deploy

**Don't commit or push — Peter commits his own work.** Say what needs committing.

A push to `main` touching `homelab/hosts/opti/apps/webapp.v3.Fable/**` (or the compose file,
`nginx-wg.conf`, the bot/notes dirs, or the workflow itself) triggers
**`.github/workflows/opti-apps-deploy.yml`**:

1. `build-frontend` on `ubuntu-latest` (Node 24): `npm ci && npm run build`, uploads `dist`.
2. `deploy` on the self-hosted runner labelled **`[self-hosted, opti]`**: copies the compose
   file, `rsync -a --delete --exclude node_modules` of `webapp.v3.Fable/` into
   `/srv/docker/compose/webapp/`, copies `nginx-wg.conf`, rebuilds bots, `docker compose up -d`,
   restarts `webapp`, runs the smoke `--compare` inside the container, restarts `nginx-webapp`.

Gotchas: the **`paths:` filter** means a change elsewhere (e.g. a generator under
`homelab/tools/`) does not deploy on its own; `workflow_dispatch` exists for a manual run.
`/srv/docker/compose/webapp/` is a deploy target — never edit it as the fix; the next run's
`--delete` rsync reverts it. There is no live-on-copy path for SvelteKit pages (they need
the CI build); a hot copy to opti is only for emergencies and must still be pushed.

## 6. Verify after deploy

From this workstation (no `~/.ssh/config` on Windows — pass the key; from tux, `ssh opti` works):

```powershell
curl.exe -sk https://webapp.lan:8443/api/thing/status
curl.exe -sk https://webapp.lan:8443/thing | Select-Object -First 5     # SPA shell for any HTML route
ssh -i $HOME\.ssh\optiplex_omv ptm@192.168.1.11 'cd /srv/docker/compose && docker compose logs --tail=50 webapp'
```

Also check the Actions run for the smoke step's output (`FAIL` lines name the route).

## Caveats

- **opti is a single point of failure** for the dashboard, bots and vault together; the
  data mounts are local now, but homelab-db or a bot can still be down while the page is up
  — degrade with a message.
- **Bot control APIs are internal-only** (`discord-*` expose `:8080` on the `internal`
  network). Manage bots through the webapp, never by editing files on the host.
- **Pi-hole stays on rpi**, addressed by IP so the dashboard survives a DNS outage.
- Host access goes through the `homelab-ssh` skill.
