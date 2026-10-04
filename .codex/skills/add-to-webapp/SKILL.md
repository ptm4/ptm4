---
name: add-to-webapp
description: Add or change anything on the homelab dashboard — Pertal (webapp v4, https://webapp.lan:8444, becomes :8443 at cutover) — a page, tab, data source, button/action, Status card, resource or topology node, or API route. Use when the user asks to add/publish/show something on the web app, the dashboard, Pertal, webapp.lan, "Pert's Pocket" (the v3 name) or "the rpi web app" (old name — it runs on opti), or to change what the dashboard shows or does.
---

# Add something to Pertal (webapp v4)

**New work goes into Pertal.** v3.Fable still serves `https://webapp.lan:8443` until
cutover and only gets fixes (see the last section). The plan, decisions and build status
are in `homelab/hosts/opti/apps/WEBAPP-V4-PLAN.md`; the folder README has the architecture.

| | |
|---|---|
| **Source** | `homelab/hosts/opti/apps/webapp.v4.Pertal/` — `backend/` (Fastify 5, CommonJS) + `frontend/` (SvelteKit static SPA, Svelte 5 runes, TypeScript) |
| **Live** | `https://webapp.lan:8444` (side by side with v3) — container `pertal` on **opti**, compose profile `pertal` |
| **Image** | `Dockerfile` in the folder: deps + frontend build baked in; healthcheck on `/api/health`. No `npm install` at start, no bind mount |
| **Proxy** | `nginx-webapp` `server { listen 8444 }` in `homelab/hosts/opti/apps/nginx-wg.conf` (lazy `resolver 127.0.0.11` + `set $pertal`, so a missing container never stops nginx) |
| **Data volume** | `arch_data` → `/arch-data`, shared with v3 (job audit, fragments, `pertal/activity/`) |
| **Deploy** | `.github/workflows/opti-apps-deploy.yml`, **last** steps (sync → `--profile pertal build/up` → wait for healthy → build/start `--profile cockpit` gateways) |

## The two rules — every change must keep them

1. **No request waits on an upstream.** Data is polled in the background into the snapshot
   cache (`backend/lib/snapshots.js`); routes and pages read memory. Each snapshot carries its
   age and the UI shows it (`Age` component). The only on-demand upstream reads are logs and
   long-range metrics — hard timeout, plain error body.
2. **Every button is a job.** Anything that changes something goes through a job with
   declared steps (`backend/lib/jobs.js`): live progress over SSE, the tray, the audit trail,
   failures included. Risky kinds require `confirm: true` (428 otherwise) and the UI asks first. **Approved exception:** embedded Cockpit Console runs full root
   operations outside Pertal jobs/audit/holds; do not wrap or claim them as Pertal jobs.
   See `apps/cockpit-gw/README.md` for the trust boundary and rollback.

Also: **healthy is quiet** — `--ok` is grey; colour only for things that want attention.
Both theme families (gruvbox default, github alt) define the same tokens in
`frontend/src/lib/theme/tokens.css`; never hardcode a hex in a component. The logo is the
raspberry pie slice carried over from v3 (`frontend/static/favicon.svg` — tab icon, top bar,
Pertal's topology card). Peter loves it: don't replace it with a generic icon.

## Recipes

### A new data source
`backend/sources/<thing>.js` exporting `register<Thing>Sources(snapshots)`:

```js
snapshots.register({
  key: 'thing:status', group: 'thing', label: 'Thing',
  intervalMs: 60_000, timeoutMs: 8000, staleAfterMs: 5 * 60_000,
  fetch: async ({ signal }) => { /* fetch with `signal`, return plain JSON */ },
});
```
Register it in `backend/app.js` beside the others (skip registration when its env/token is
unset — see Seerr). A failing source becomes a "Needs attention" issue unless its key matches
the `quiet` regex in `backend/lib/resources.js` — add it there when its own card already says so.
Settings come from env vars on the `pertal` service in `homelab/hosts/opti/docker-compose.apps.yml`;
**secrets live in `/srv/docker/compose/.env` on opti and Peter adds them** (never write that file).

### A new page
`frontend/src/routes/<name>/+page.svelte`, then an entry in `frontend/src/lib/nav.ts`
(`NAV` for the rail, `EXTRA_PAGES` for search-only). Pattern every page uses — refetch when the
snapshot behind it changes, instead of polling:

```ts
const stamp = $derived(live.snapshots['thing:status']?.fetched_at);
$effect(() => { void stamp; void load(); });
```
Global state (resources, summary, jobs, activity, snapshot metas) is `live` from
`$lib/live.svelte.ts` (SSE-fed). API helpers in `$lib/api.ts`. Always render loading, error and
empty states. Phone first: check 375px (`resize_window` preset mobile); dense on desktop.
Icons: `@lucide/svelte`. Charts: `LineChart.svelte` (no chart library).

### A new button
- **On a resource** (host/container): add an entry to `ACTIONS` in `backend/lib/actions.js`
  (`label`, `icon`, `risky`, `applies(resource, snapshots)`, `plan(resource)` → `[{ key, label }]`,
  `run(ctx, job, resource, params)` doing `await job.step(key, async (note) => …)` per planned
  step). It appears in that resource's command bar automatically. Agent calls go through
  `ctx.agent()` and waits check `ctx.dry`, so dry-run mode works.
- **Page-specific** (Downloads, Requests): the route's `runJob(app, spec, body)` helper
  (`app.jobs.create` + detached body) answers `202 { job }` at once; the page calls
  `actions.track(job)`. Risky ones: route returns 428 without `confirm`, page asks first with
  `actions.ask({ title, body, label, run })`. Copy `routes/downloads.js`.

### A new resource kind or topology node
Resources: `backend/lib/resources.js` (status vocabulary ok/warn/crit/unknown/offline; `online`
is reachability, separate from findings). Topology: `SERVICES` / `EDGES` in
`backend/lib/topology.js`; the diagram layout is `frontend/src/lib/topology-layout.ts`
(hosts are lanes; add icon in `TopologyDiagram.svelte` `ICON`). An edge is broken only when an
end is **down**, never because of findings. Add reasons through `addReason()` in
`buildResources` so **acknowledgements** (`lib/acks.js`, `/api/acks`, the bell buttons) apply: an
acked reason stays listed but stops raising status and counts until it gets more severe.

### A Status-page card
`frontend/src/lib/components/TodayStrip.svelte` (weather / calendar / CS2 / NBA) — each card
reads its own snapshot via `/api/extras` and fails alone.

## Check before handing off

```powershell
cd E:\REPO\ptm4\homelab\hosts\opti\apps\webapp.v4.Pertal
npm --prefix backend test                 # offline fake-snapshot suite (backend/test/pertal.test.js)
npm --prefix frontend run check           # svelte-check: must be 0 errors, 0 warnings
npm --prefix frontend run build
```
Add a test for any non-trivial route or model rule. CI (`checks.yml`) runs all three.

**Run it:** preview configs `pertal-api` (backend :3100, `backend/dev.env`: live homelab reads,
**`PERTAL_ACTIONS=dry`** so no action touches anything) and `pertal` (Vite :5174, proxies `/api`
and `/hls`). Verify in the browser pane, including the console. In dev there is no agent token
and no compose network: logs, stream control and anything at `http://<container>:port` show
their "not available here" error — that is expected, test those after deploy.
Stop the backend **by port** (`Get-NetTCPConnection -LocalPort 3100`), not by process name —
`node --watch` leaves its child running as plain `node server.js`.

**Deploy changes to compose/nginx/Dockerfile:** validate on opti before Peter pushes —
`docker compose --env-file /srv/docker/compose/.env --profile pertal --profile cockpit config --quiet` on a temp
copy, `nginx -t` inside the running `nginx-webapp` with the new conf, and a trial
`docker build` of the folder (remove the image after).

## Deploy and verify

**Never commit or push — Peter does.** List what changed. After his push:

```bash
gh run list --workflow opti-apps-deploy.yml -L 1
ssh opti 'sudo docker inspect -f "{{.State.Health.Status}}" pertal'
curl -sk https://192.168.1.11:8444/api/health
```
Then check the feature for real on :8444 (the container has the tokens dev lacks).

## Gotchas learned building it

- **Container → opti's own LAN ports is blocked** by opti's ufw. Reach opti-hosted services by
  compose name on the `internal` network (`http://dozzle:8080`, `http://hltv-api:8080`,
  `http://seerr:5055`, `http://discord-*:8080`); other hosts by LAN IP.
- **hl-arch-agent (≥ v0.8.0)** on every host: `GET /containers` (open, live `docker ps`),
  `GET /logs` (token), mutators need the token. It is **not** CI-deployed — install by hand to
  `/usr/local/bin/hl-arch-agent.py` with LF line endings, back up the old one, restart the unit.
  Fragments (`POST /api/architecture/ingest`) arrive only daily — never use them for live state.
- **qBittorrent** whitelists the LAN subnet: call it at `192.168.1.6:8081`, not `localhost`
  (from noblenumbat itself, localhost comes from the Docker bridge → 403).
- **hltv-api:** always `/day?max_age=900` (non-blocking); `max_age=0` waits for a full scrape.
- **SSE:** browsers never retry an EventSource after a non-200 (nginx 502 during deploys);
  `live.svelte.ts` reconnects itself and the server pings every 15s — keep both.
- **Bot configs** are read from each bot's `GET /config` on the internal network; change them
  through the dashboard, never by editing files on opti.
- **Asset Library** (`/assets`) reads `E:\Assets` live from the workstation (ptm `:8767`,
  `homelab/hosts/ptm/asset-server`): folders and search via `/api/assets/*`, file bytes via
  nginx `/asset-files/` + `/asset-thumbs/` straight to ptm. ptm off/in Linux is normal — the
  `assets:server` source records it as data (`online: false`), never as a failing source.
- Working copy is CRLF (`core.autocrlf=true`): strip `\r` before copying scripts to hosts.

## v3.Fable (until cutover) — fixes only

`homelab/hosts/opti/apps/webapp.v3.Fable/`, served at `:8443` by container `webapp`
(`node:lts-alpine`, bind-mounted, `npm install` at start). Same deploy workflow (earlier
steps; its API smoke must pass). Only fix bugs there — anything new goes into Pertal. Its
detailed conventions are in this file's git history (before 2026-09-27).

## Console changes

Only `opti`, `rpi`, `noblenumbat`; internal `/console/<host>/<validated relative path>`
links use SvelteKit navigation, never external-window links. Ignore user URL query/hash;
internal deep-link hashes use navigation state only. Disabled/loading/failed/stale
snapshots render no iframe. Keep authenticated `https://<host>.lan:9090/` fallback,
age/recovery information, host cautions and the full-height mobile layout.
`cockpit:<host>` polls manifests at 60s/5s timeout/5min stale; `/api/console` reads only
memory and registration requires `PERTAL_COCKPIT=1`. Keep every `/cp-` request outside
the service worker. Cockpit actions have no Pertal audit/precheck; host reboot is no
longer a Pertal action. Keep maintenance holds, history and Docker jobs.

Host page packages must be patched before enabling the restricted SSH root bridge.
Gateway network is `172.30.90.0/24`, no published ports, no nginx gateway dependency.
Never relax LAN/WireGuard access to accommodate translated addresses or trust supplied
forwarding headers. Preserve exact Origin/cross-site guards and port-bearing Host.
Sync gateway context, validate both profiles, syntax-test a staged nginx candidate,
then publish/recreate. Build/start gateways after Pertal; an offline host is not a CI
failure, but bad configuration/build/start is. Stop on a failed loopback root/recovery
spike. Read `homelab/hosts/opti/apps/cockpit-gw/README.md` before changing this boundary.
