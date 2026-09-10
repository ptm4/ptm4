# Pert’s Pocket — independent v3 local preview

This directory contains the redesigned monitoring hub. “Astra” identifies the implementation directory and isolated storage namespace; it is not product branding.

## Run

From PowerShell:

```powershell
Set-Location E:\REPO\ptm4\homelab\hosts\rpi\webapp.v3.Astra
# Dependencies are already installed in this checkout. For a fresh copy:
npm --prefix frontend ci
npm --prefix backend ci
./Start-Preview.ps1
```

- App: **http://127.0.0.1:5174/**
- Streams: **http://127.0.0.1:5174/streams**
- API / built app: **http://127.0.0.1:3003/** (run the frontend build first)
- Standalone HTML: `design/astra-preview.html`, or `/astra-preview.html` on either server.
- Stop your preview: `./Stop-Preview.ps1`. It checks process command lines before stopping anything.

Read `E:\REPO\ptm4\AgentComms.md` before claiming ports. The startup script refuses occupied ports; choose an unused pair with `-FrontendPort 5184 -BackendPort 3013` only after checking other agents’ reservations. It records ports and process IDs in the shared log and `.runtime/processes.json`. Servers bind to loopback. Phone-sized layouts can be previewed in desktop device emulation; LAN/mobile deployment is a separate step.

## What is implemented

- Dense fleet monitor: six operational counters, four host panels with history, findings, schedules, favorites, storage, network, VPN, downloads and database health.
- Dedicated host controls, container inventory, DNS/Pi-hole, history, updates, collectors/backups, security, and log pages.
- Launchpad: homelab and general links, category/search/favorites filters, grid/list views, custom links and local overrides for built-in destinations.
- Streams: mobile navigation, four slot selectors, native Safari HLS or bundled hls.js, quality/buffer settings, theater/fullscreen/PiP, channel search, favorites, recent channels and custom URLs. Twenty-one directory channels include BLAST Premier, ESL CS, PGL and CS2 streamers.
- Match guide: the existing HLTV day feed joined to its Valve Regional Standings. Top-20 eligibility, match stream links, live/upcoming/results filters, maps, freshness and explicit source coverage. “Premier series” is a name-based discovery label, not a claim of S-tier classification. HLTV stars never imply S-tier.
- Boards retain all 26 widget types, responsive layouts, wallpaper/settings, touch/keyboard move/height controls, serialized saves, revision conflicts and browser draft recovery.
- Bots, Leetify, local LLM, query/schema and data-pipeline views remain accessible as dedicated pages.
- Gruvbox dark/light, compact/comfortable density, reduced motion, global search and full-screen phone dialogs.

## Data and permissions

**Demo is the startup default.** It never calls homelab monitoring sources or loads stream video. Samples are explicitly fictional. Host/container/collector/Pi-hole/stream actions and bot config/send calls run against an in-memory simulation; no commands or messages leave the preview. Simulation state resets with the backend. Settings, links, boards and acknowledgements persist independently.

Settings → Data mode can select **live read-only monitoring**. The backend forwards reviewed GET routes to `ASTRA_UPSTREAM` (default `https://192.168.1.10:8443`). It deduplicates/caches polling and imposes request timeouts. Existing station slots can be played through an allowlisted HLS path. Start/stop/keepalive remain blocked in live mode; use the labeled live station link for those actions. Live bot sends, ingestion, collector triggers, LLM commands, Samba changes and arbitrary queries are blocked server-side.

If the Pi uses a self-signed certificate, start the backend with `ASTRA_ALLOW_SELF_SIGNED=1` only for that known local upstream. The exception is scoped to its requests, not global Node TLS. No credentials were copied. Live integration testing requires your VPN/LAN; this build has not been deployed.

**Storage:** `.runtime/astra-preferences.json`, `.runtime/ui/boards/`, `.runtime/ui/settings.json`, `.runtime/ui/wallpapers/`. Browser keys begin `astra-`, including streams, link layout, trends, widget range, and recovery drafts. Do not share these runtime directories with v2 or Fable.

## Validate

```powershell
npm --prefix frontend run build
Push-Location backend
node --test --test-isolation=none test/parity.test.js
node --test --test-isolation=none test/astra.test.js
Pop-Location
node scripts/smoke-api.mjs --compare scripts/astra-smoke-baseline.json
node scripts/make-preview.mjs
```

The retained `scripts/smoke-legacy-api.mjs` is the original contract manifest; the default smoke script checks the preview’s different permission boundary. See `VALIDATION.md` and `MIGRATION.md` for evidence and remaining integration limits.
