# Pertal — webapp v4

The homelab portal that replaces v3.Fable. Plan, decisions and build status:
[`../WEBAPP-V4-PLAN.md`](../WEBAPP-V4-PLAN.md). v3.Fable serves `:8443` while Pertal
runs beside it on `:8444`; source changes deploy after Peter commits and pushes.

## The two rules

1. **No request waits on an upstream.** Every data source is polled in the background into
   the snapshot cache (`backend/lib/snapshots.js`); routes and pages only read that. Each
   snapshot carries its age, and the UI shows it.
2. **Every button is a job.** `POST /api/actions/:kind` → declared steps → live progress over
   SSE → audit trail. Risky kinds need `confirm: true` (428 without it). Console is the approved exception described below.

## Layout

```
backend/   Fastify. sources/ (what is polled) → lib/snapshots → lib/resources (the model)
           lib/actions (the pipeline, on lib/jobs) · routes/api, events (SSE), ingest
frontend/  SvelteKit static SPA. lib/live.svelte.ts is the one store (SSE-fed);
           lib/theme/tokens.css holds both theme families (gruvbox default, github alt)
Dockerfile one baked image, healthcheck on /api/health
```

Adding a data source = register it in `backend/sources/`. Adding a button = one entry in
`ACTIONS` (`backend/lib/actions.js`). Adding a kind of resource = `backend/lib/resources.js`.

The **Asset Library** page is the one part that lives off opti: it reads `E:\Assets` on the
workstation through `homelab/hosts/ptm/asset-server` (its README has the whole path).

## Develop

Two launch configs in `.claude/launch.json`: `pertal-api` (backend on :3100, reads the live
homelab, **actions in dry-run mode** via `backend/dev.env`) and `pertal` (Vite on :5174,
proxies `/api`). Or by hand:

```bash
npm --prefix backend run dev
npm --prefix frontend run dev
```

Tests: `npm --prefix backend test` (offline, fake sources) and `npm --prefix frontend run check`.
Needs hl-arch-agent **v0.7.0+** on each host for live container state (`GET /containers`).

## Console architecture (approved exception)

`/console/<opti|rpi|noblenumbat>/<page>` embeds a same-origin `/cp-<host>` Cockpit
gateway on a private compose network. Trusted LAN/WireGuard users get full root
access without signing in. Host-served pages and gateway are patched first.
[`../cockpit-gw/README.md`](../cockpit-gw/README.md) is the setup/deployment/rollback
runbook. `GET /api/console` only reads background manifest snapshots (60s polls,
5s timeout, 5min stale). Dev stays disabled unless `PERTAL_COCKPIT=1`.

Cockpit mutations run outside Pertal's job/audit/confirmation/maintenance-hold pipeline.
Pertal removes its host reboot action and the ZFS reboot precheck; Console retains
host cautions. Maintenance holds, historical metrics and Docker operations remain.
The host authenticated `:9090` endpoints remain fallback links. Service-worker handling
never intercepts `/cp-` paths; Console mirrors validated iframe paths with SvelteKit
navigation APIs and synchronizes Cockpit's theme through `shell:style`.

The restricted SSH command uses `/usr/local/libexec/pertal-cockpit-bridge`, a root-owned
launcher that fixes failed default-bus caching in Cockpit 337/362 without changing
package files. Rollout checks include repeated missing session-bus requests followed
by working system/internal D-Bus calls, live metrics and gateway recovery.
