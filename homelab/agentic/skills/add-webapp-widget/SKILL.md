---
name: add-webapp-widget
description: Add a widget to the homelab dashboard's board (the card grid at webapp.rpi.lan) — a tile showing live data, status, or a small feed. Use when the user asks for something to appear on the dashboard/board/home screen as a card, or to add/change a dashboard widget.
---

# Add a widget to the rpi dashboard board

The v2 webapp (Fastify + React/Vite) is a Homarr-style **board of widgets**. Widgets are the
extension point: adding one is a registry entry plus a component, not a new page. For a
full page or a plain API route instead, see [`add-to-rpi-webapp`](../add-to-rpi-webapp/SKILL.md).

| | |
|---|---|
| **Source** | `homelab/hosts/rpi/webapp/` — edit here, this is authoritative |
| **Deploy** | push to `main`; `.github/workflows/rpi-deploy.yml` builds the frontend and syncs |
| **Never** | edit `/srv/docker/compose/webapp/` on rpi — the next CI run reverts it |

The frontend is a **Vite build**, so widget changes are *not* live-on-copy the way legacy
static files are. They ship when CI builds. Peter commits and pushes; you don't.

## 1. Where the data comes from

Pick one, cheapest first:

- **An endpoint that already exists** — check `backend/routes/` and the hooks in
  `frontend/src/lib/queries.ts`. Reuse beats adding.
- **A service the webapp already proxies** — add one line to that route file's `ROUTES`
  table (e.g. `backend/routes/hltv.js`) and it's done; the generic proxy loop handles it.
- **Something new** — `backend/routes/<name>.js` + register it in `backend/app.js`.
  Use `proxyJson` from `backend/lib/upstream.js` for internal containers.

Whatever you add, cache it at the source if a widget will poll it. A widget on an open
dashboard polls all day — that must not translate into load on the thing behind it.

## 2. The component

Components live in `frontend/src/widgets/{system,services,integrations}.tsx` — pick the file
that matches the domain. Build on the shared kit (`widgets/kit.tsx`): `WidgetFrame`
(`title`, `meta`, `scroll`, `href`), `WidgetError`, `WidgetLoading`, `Sparkline`, `Pill`,
`Meter`, `Vital`. Styling classes that already exist: `.kv-rows`/`.kv-row` for label→value
lists, `.feed` for event lists, `.dim-strip` for stat chips, `.t-dim` for secondary text.

Copy the fetch pattern from `StreamsWidget` (`widgets/integrations.tsx`):

```tsx
const q = useQuery({
  queryKey: ['thing-status'],
  queryFn: () => get<Thing>('/api/thing/status', 12_000),
  refetchInterval: 60_000,
  retry: 0,          // bot/service proxies legitimately 502 when the container is down
});
if (q.isError) return <WidgetFrame title="Thing"><WidgetError message="thing unreachable" /></WidgetFrame>;
```

Rules that keep the board coherent:

- `retry: 0` on anything proxied to a container, and always render an error state — a widget
  must degrade to a message, never a blank card or a crash.
- TanStack Query dedupes by `queryKey`, so N copies of a widget cost one request per interval.
  Reuse the existing key if you're reading an endpoint some hook already polls.
- The toolbar Refresh button invalidates every non-board query, so `useQuery` gets manual
  refresh for free.
- Show data age (`relTime` from `lib/format`) when the payload carries a timestamp, and label
  stale/degraded data instead of hiding it.
- Accept `options?: Record<string, unknown>` and read your settings from it with defaults.

## 3. The registry entry

`frontend/src/widgets/registry.ts` — import the component and add one entry:

```ts
{
  type: 'cs2-matches',              // stable id, stored in the board document
  label: 'CS2 matches',
  description: "Today's HLTV slate — live scores, upcoming, results.",  // shown in the catalog
  component: Cs2MatchesWidget,
  defaults: { w: 4, h: 5 },
  min: { w: 3, h: 3 },
  options: [                         // drives the settings modal; no per-widget form code
    { key: 'limit', label: 'Matches per section', type: 'number', min: 3, max: 20 },
    { key: 'sections', label: 'Show', type: 'select', choices: [/* … */] },
  ],
}
```

That's the whole wiring: the Add-widget catalog, the settings modal, grid sizing and
persistence all read from this entry. **No backend change is needed to store it** — board
documents don't enumerate widget types (`backend/routes/ui.js` validates only
`{id, type, options}`). Unknown types degrade to a placeholder card rather than crashing.

Don't add the widget to `backend/lib/board-presets.js` unless the user wants it pre-placed on
the protected `home`/`dashboard` boards; otherwise they add it via Edit board → Add widget.

## 4. Smoke contract

If you added a backend route, add it to `webapp/scripts/smoke-api.mjs`
(`expect: [200, 502]` for anything proxied to a container) and update
`webapp/scripts/smoke-baseline.json` with the response's top-level keys. The deploy runs this
inside the container and **a route whose key set shrank turns the deploy red** — which is the
point, but it means baseline and code must change in the same commit.

## 5. Verify before pushing

The Pi has no node, and tux may not either. The app is built to run off-box (see
`backend/lib/paths.js` — every directory has an env override), so verify on noblenumbat:

```bash
rsync -a --exclude node_modules --exclude dist homelab/hosts/rpi/webapp/ noblenumbat:/tmp/wa/
```

1. **Typecheck + build** (this is what CI does; catching it here saves a red deploy):
   `docker run --rm -v /tmp/wa/frontend:/app -w /app node:24-alpine sh -c "npm ci && npm run build"`
2. **Run the app** against scratch dirs, with the upstream service stubbed if it isn't
   reachable: `docker run -d --network host -v /tmp/wa:/app -w /app/backend -e ARCH_DATA_DIR=/app/archdata -e <SERVICE>_URL=http://127.0.0.1:8899 node:24-alpine sh -c "npm install --omit=dev && node server.js"`
   (entrypoint is `server.js`; `app.js` only builds the instance. Copy the frontend build to
   `frontend/dist` so the static plugin serves v2.)
3. **Put the widget on a board** with the same API the UI uses — PUT `/api/ui/boards/home`
   with your widget in `widgets` and an entry in `layouts.lg`/`layouts.sm` — then load the page
   and read the rendered card to confirm real values, links, and the loading/error/stale states.

Clean up the containers and `/tmp` dirs on noblenumbat when you're done.
