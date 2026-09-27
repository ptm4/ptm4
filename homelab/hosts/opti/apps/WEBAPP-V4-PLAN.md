# Webapp v4 — consolidation plan

Status: **draft slate, 2026-09-27.** Written during the homelab audit as the brief for a future
redesign session. Goal in Peter's words: *simplify, and make the webapp strong & reliable again
like v1* — then finalize as v4.

## Where we are

| Version | Path | State | Size (tracked, excl. lockfiles/JSON) |
|---|---|---|---|
| v1 | git history only — `homelab/RPI-srv/webapp/` (last at `1918d97`) | gone | Express 4 + vanilla JS, no build step |
| v2.legacy | `webapp.v2.legacy/` | frozen, documented rollback target | ~28k lines |
| v3.Astra | `webapp.v3.Astra/` | undeployed fork of v2 (React/Radix/Zustand) | ~29k lines |
| **v3.Fable** | `webapp.v3.Fable/` | **live since 2026-09-10** (Fastify 5 + SvelteKit static) | ~36k lines |

~94k lines for one dashboard, two thirds of it undeployed. `frontend-legacy/` (the v1 static
pages) is vendored **three times**, as are the 78 KB `architecture/data.json`/`index.html` and a
543 KB `hls.js`. Astra's README and `ASTRA_UPSTREAM` still point at the pre-migration rpi
endpoint. No version has prettier or eslint.

### What makes Fable fragile today
1. **`npm install` on every container start** (`docker-compose.apps.yml` webapp `command:`),
   against a bind-mounted source tree. Every restart depends on npm cache health before serving.
2. **No container healthcheck** on `webapp` (every other app-tier service has one), so Docker
   never notices a wedged process; nginx just shows the holding page.
3. **No global request timeout** — each route must remember its own upstream timeout.
4. **Six+ live upstreams** for one page set: hl-arch-agent :8787 ×3 hosts, homelab-db :9100,
   dispatcher :9099, llama on android (often offline), Kuma, Pi-hole, stream-station.
5. `/api/agents` and `/api/llama` pass raw upstream status codes through, and the frontend keys
   retry logic off them — tight coupling.
6. Dead surface: `lib/board-presets.js` + `/api/ui/boards` (board UI deleted 2026-09-10).
7. 18 frontend routes (`/`, bots, cockpit, dashboard→monitor, data, docs, feed, host/[name],
   launchpad, links, llm, logs, monitor, reports, settings, settings/maintenance, streams,
   topology, trends) — more pages than the homelab has distinct questions.

### What v1 got right
One process, one static folder, no build step, each card fetched its own data and failed on
its own. Nothing could take the whole page down except the server itself.

## Phase 0 — cleanup now (no redesign yet)

Small, independently shippable, each keeps Fable live:

- [ ] **Bake the image**: multi-stage `Dockerfile` for the webapp (deps installed at build),
      compose uses `build:`/image instead of `npm install && node server.js`. Keep the bind
      mount only for `frontend/dist` if CI still rsyncs it.
- [ ] **Add a healthcheck** on `webapp` hitting a cheap `/api/health` that does *no* upstream I/O.
- [ ] **Global `requestTimeout`** on Fastify (e.g. 15s) with explicit longer overrides only on
      the SSE, llama and agents routes that already have long nginx timeouts.
- [ ] **Delete `board-presets.js` / `/api/ui/boards`** (confirm no saved docs in `arch_data`).
- [ ] **Prettier + eslint** at `webapp.v3.Fable/` root (one config), one mechanical format commit,
      then enforce in `opti-apps-deploy.yml`.
- [ ] **Harvest from Astra, then retire it**: worth porting — `backend/astra/snapshot.js`
      (one-call live aggregation), the demo/fixture mode for offline dev, `guide.js` (VRS match
      guide). Then `git tag webapp-v3-astra-final` and remove `webapp.v3.Astra/`.
- [ ] **Retire v2.legacy** the same way (`git tag webapp-v2-final`) once Fable has run a few weeks
      with the Phase 0 changes — rollback becomes `git checkout <tag>` instead of a live folder.
- [ ] Fix Fable's stale README (says v2 is live, references `rpi-deploy.yml`) — or delete it and
      point at the `add-to-webapp` skill, which is already accurate.

## Phase 1 — v4 redesign session (Opus 5.5)

Start a fresh `webapp.v4/` from Fable's backend, not from scratch. Design brief:

**Information architecture — ~6 pages, each answering one question:**
1. **Home** — is anything wrong right now? (one status strip per host + open findings + ntfy feed)
2. **Hosts** — one page per host (replaces cockpit / monitor / trends / host/[name])
3. **Media** — Jellyfin/*arr/streams/VPN state (replaces streams + parts of launchpad)
4. **Bots** — the five Discord bots, their last post and failures
5. **Docs** — homelab-db search + incidents (replaces docs / data / topology / reports)
6. **Settings** — maintenance holds, jobs audit trail

Launchpad/links collapse into Home; LLM page only if android is ever reliably online.

**Data contract — the v1 lesson, made explicit:**
- One server-side **snapshot cache** per source (arch-agent per host, homelab-db, Kuma, Pi-hole,
  jellyfin, bots), each refreshed on its own interval with its own timeout, each carrying
  `{ok, stale_since, error}`.
- The UI reads cached snapshots only — **a request never waits on an upstream**. A dead source
  greys out its own card; nothing else notices.
- SSE stays, but only pushes "snapshot X changed".
- Writes (restart container, hold updates) stay as audited jobs.

**Visual:** keep the GitHub-pastel palette and couch-friendly Home from Fable; one design-token
file; no component library.

## Phase 2 — hardening & cutover

- Route smoke test (`scripts/smoke-api.mjs`) grows a "every page renders with all upstreams
  down" test using the fixture mode.
- `opti-apps-deploy.yml` builds the image, runs lint + svelte-check + smoke, then swaps.
- Cutover: CI path filter moves to `webapp.v4/**`; Fable tagged `webapp-v3-fable-final` and
  removed after two quiet weeks. `add-to-webapp` / `add-webapp-widget` skills updated in the
  same change.

## Open decisions for Peter
- Keep SvelteKit (smallest dep footprint, only version with a type-check gate) — or go back to
  v1-style no-build vanilla JS for maximum boringness?
- Which of the 18 current routes do you actually open weekly? Anything not on that list is cut.
- Retire v2.legacy now, or keep it as the rollback until v4 ships?
