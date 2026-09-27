# Pertal — webapp v4

The homelab portal that replaces v3.Fable. Plan, decisions and build status:
[`../WEBAPP-V4-PLAN.md`](../WEBAPP-V4-PLAN.md). **Not deployed yet** — v3.Fable is still what
`webapp.lan` serves.

## The two rules

1. **No request waits on an upstream.** Every data source is polled in the background into
   the snapshot cache (`backend/lib/snapshots.js`); routes and pages only read that. Each
   snapshot carries its age, and the UI shows it.
2. **Every button is a job.** `POST /api/actions/:kind` → declared steps → live progress over
   SSE → audit trail. Risky kinds need `confirm: true` (428 without it). There is no other
   path that changes anything, so nothing can fail silently.

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
