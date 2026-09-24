---
name: add-webapp-widget
description: Add a widget, card, tile or panel to the homelab dashboard at webapp.lan (v3.Fable on opti) — something showing live data, status, or a small feed on Home, the Monitor, the Control center, a host page, or the Launchpad. Use when the user asks for something to appear on the dashboard/board/home screen as a card or tile, or to add/change a dashboard widget.
---

# Add a widget to the dashboard

**Read this first: v3.Fable has no user-editable widget board.** The v2 app's Homarr-style
board (a widget registry, "Edit board → Add widget", gridstack layouts) was deleted in the
2026-09-10 consolidation (see the header of `frontend/src/lib/nav.ts`). The
`/api/ui/boards` API and `backend/lib/board-presets.js` still exist so old documents load,
but no page renders a board. So "add a widget" means **placing a component on a specific
page**, and the first job is picking the right page.

| | |
|---|---|
| **Source** | `homelab/hosts/opti/apps/webapp.v3.Fable/` (Svelte 5 + SvelteKit SPA, Fastify backend) — edit here |
| **Deploy** | push to `main`; `.github/workflows/opti-apps-deploy.yml` builds the frontend and syncs to opti |
| **Never** | edit `/srv/docker/compose/webapp/` on opti — the next run's `rsync --delete` reverts it |
| **Not deployed** | `webapp.v2.legacy/` (the old React board app) and `webapp.v3.Astra/` — don't port widgets *into* them |

For a whole new page or an API route, see [`add-to-webapp`](../add-to-webapp/SKILL.md) — it
also covers deploy, smoke contract, mounts and nginx in full. Peter commits and pushes; you don't.

## 1. Pick where it lives

| Surface | File(s) | Put it here when |
|---|---|---|
| **Home** (`/`) — the couch/phone view | `frontend/src/routes/+page.svelte` | It answers *"is anything wrong?"* or *"what do I want to open?"*. Rules in the file header are subtractive: healthy renders as **absence**, no live counters, big touch targets. Most requests do **not** belong here — push back. The couch tiles are `COUCH_LABELS`, matched against `ALL_LINKS` in `frontend/src/lib/links.ts`. |
| **Monitor** (`/monitor`) — btop-style TUI | `frontend/src/routes/monitor/+page.svelte`, `frontend/src/lib/features/tui/Panel.svelte` + `glyphs.ts` | A live metric you want to *watch*. Panels are text/glyph graphs, one panel per metric, hosts as rows. |
| **Control center** (`/cockpit`) | `frontend/src/routes/cockpit/_parts/OverviewPanel.svelte`, `HostCard.svelte`, or a new tab in `routes/cockpit/+page.svelte` (`?tab=`) | An operational status/action card. |
| **Host page** (`/host/:name`) | `frontend/src/routes/host/[name]/+page.svelte` | Per-host detail. Already composes the reusable widgets `HostVitals`, `hldb/Changes`, `hldb/LongTrends`. |
| **Launchpad** (`/launchpad`) | `backend/lib/services.js` (catalog, served by `/api/services`) + icon in `frontend/static/icons/apps/` | A link to a web UI, with live health dot. Also mirror it in `frontend/src/lib/links.ts` (static fallback + Home/CmdK). |
| **Metrics** (`/trends`) | `frontend/src/routes/trends/` | A long-range chart. |

## 2. Where the data comes from

Cheapest first:

- **A hook that already exists** — `frontend/src/lib/api/queries.ts` (`useVitals`,
  `useVitalsRange`, `useContainers`, `useTimers`, `useActivity`, …), `fleet.ts` (`useHosts`,
  `useArchLive`, `useUpdates`), `incidents.ts`, `rules.ts`, `services.ts`, `streams.ts`.
  TanStack Query dedupes by `queryKey`, so reusing a hook costs no extra requests.
- **An existing endpoint** — `backend/routes/`; for anything historical, **prefer homelab.db
  via `/api/hldb/*`** (`metrics`, `changes`, `search`, …) over new file parsing.
- **A service the webapp already proxies** — e.g. add to the route table in
  `backend/routes/hltv.js` rather than a new route.
- **Something new** — `backend/routes/<name>.js`, registered in `backend/app.js`, using
  `proxyJson` from `backend/lib/upstream.js`. Cache at the source if the widget polls: an open
  tab polls all day.

`vitals`, `containers`, `activity`, `incidents`, `notifications` and jobs are also pushed over
SSE (`frontend/src/lib/api/sse.svelte.ts`), so hooks on those keys refresh without tighter polling.

## 3. The component

Card-style widgets build on the kit in `frontend/src/lib/widgets/kit/` (`index.ts` exports
`WidgetFrame`, `WidgetError`, `WidgetLoading`, `Meter`, `Pill`, `Vital`, `Sparkline`) and the
prop contract in `frontend/src/lib/widgets/sdk.ts` (`WidgetProps { options? }`, `opt()` for
option defaults, `getWidgetContext()` which returns `null` outside a board — handle that).
`WidgetFrame` takes `title`, `meta`, `scroll`, `href`, `bare`, and `staleAt` + `staleAfterMin`
(renders a data-age pill and flags it stale). Put new ones under `frontend/src/lib/widgets/<domain>/`.

Copy the pattern from `frontend/src/lib/widgets/hldb/Changes.svelte`:

```svelte
<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { opt, type WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';

  let { options = {} }: WidgetProps = $props();
  let limit = $derived(Number(opt(options, 'limit', 10)));

  const q = createQuery(() => ({
    queryKey: ['thing-status', limit],
    queryFn: () => get<ThingResp>(`/api/thing/status?limit=${limit}`, 12_000),
    refetchInterval: 60_000,
    retry: 0,            // proxied services legitimately 502/503 when down
  }));
</script>

{#if q.isError}
  <WidgetFrame title="Thing"><WidgetError message="thing unavailable" /></WidgetFrame>
{:else}
  <WidgetFrame title="Thing" staleAt={q.data?.checked_at} staleAfterMin={10} scroll>
    {#if q.isLoading}<WidgetLoading />{/if}
    …
  </WidgetFrame>
{/if}
```

Rules that keep the app coherent:

- `retry: 0` on anything proxied to a container, and always render an error state — degrade
  to a message, never a blank card or a crash.
- Show data age when the payload has a timestamp; label stale data instead of hiding it.
- **Healthy is quiet**: `--ok` is grey on purpose. Colour (`--warn`, `--severe`, `--crit`) only
  for things that want attention. Tokens come from `frontend/src/lib/theme/tokens.css`; shared
  classes: `.kv-rows`/`.kv-row`, `.feed`, `.t-dim` (`board.css`), `.dim-strip` (`pages.css`).
  Never hardcode hexes.
- TUI panels on the Monitor use `Panel` (`title`, `meta`, `tone`) and the glyph helpers, not
  the card kit — match the surface you're on.

## 4. Smoke contract

If you added a backend route, add it to `scripts/smoke-api.mjs`'s `MANIFEST`
(`expect: [200, 502]` / `[200, 503]` for anything upstream-dependent) and its top-level keys to
`scripts/smoke-baseline.json` in the same change. The deploy runs it inside the container with
`--compare`; a 200 whose key set shrank turns the deploy red.

## 5. Verify before handing off

This Windows workstation has Node and installed `node_modules` (tux has none; opti only has
Node inside the `webapp` container; noblenumbat has Node 24 if you need Linux):

```powershell
cd E:\REPO\ptm4\homelab\hosts\opti\apps\webapp.v3.Fable\frontend
npm run check          # svelte-check — CI runs it with --threshold warning
npm run build
npm run dev            # http://localhost:5173, /api proxied to live opti by default
```

To see new backend data or loading/error states, run the backend against fixtures
(`node dev/seed-fixtures.js ..\.dev-data` + the env vars in `add-to-webapp` §4), put
`http://127.0.0.1:3000` in `frontend/.proxy-target`, and restart `npm run dev`. Load the page,
read the rendered widget for real values, links and the stale/error states, and check the
console. Then tell Peter what to commit; after the deploy, check
`ssh -i $HOME\.ssh\optiplex_omv ptm@192.168.1.11 'cd /srv/docker/compose && docker compose logs --tail=50 webapp'`.
