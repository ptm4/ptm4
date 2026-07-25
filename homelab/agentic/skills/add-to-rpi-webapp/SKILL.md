---
name: add-to-rpi-webapp
description: Add a page, tab, or API route to the homelab dashboard at webapp.rpi.lan (dashboards, reports, diagrams, tools). Use when the user asks to add/publish/put something on the rpi web app, or to change what the dashboard shows.
---

# Add something to the rpi webapp

The homelab dashboard is an Express + vanilla-JS app on the rpi. There is no build
step and no framework — you add files and they are served.

| | |
|---|---|
| **URL** | `https://webapp.rpi.lan:8443/` (self-signed cert — expect a browser warning) |
| **Repo source** | `homelab/RPI-srv/webapp/` — edit here, this is authoritative |
| **Deployed to** | `/srv/docker/compose/webapp/` on rpi, **bind-mounted** into the container at `/app` |
| **Container** | `webapp` (`node:lts-alpine`, runs `npm install --omit=dev && node index.js`) |
| **Reverse proxy** | container `nginx-webapp` terminates TLS on `192.168.1.10:8443` |

Because the source directory is bind-mounted, **static frontend files are live the
instant they land on disk** — no rebuild, no restart. Only backend JS needs a restart.

## 1. Decide the shape

Three kinds of addition. Pick by how much chrome the thing needs:

| Shape | Use when | Where |
|---|---|---|
| **Standalone page** | Self-contained view with its own layout, canvas, or heavy CSS — diagrams, maps, reports | `frontend/<name>/index.html` (+ its own `data.json`, assets) |
| **SPA tab** | Fits the dashboard's existing sidebar + card idiom | a route in `frontend/app.js`, rendered into `#view` |
| **API route only** | Just exposing data (proxying a service, reading a file) | `backend/routes/<name>.js` |

Existing standalone pages: `frontend/architecture/`, `frontend/agentic/`, and
`notes-app/web/` (served separately at `/notes/`). Existing SPA tabs: home, security,
agents, the five bots, leetify, llm — all in `app.js`.

**Prefer a standalone page for anything visual.** It keeps a large `<style>`/`<script>`
out of the 2000-line `app.js`, and it can be opened directly.

## 2. Build it

### Standalone page

Create `frontend/<name>/index.html`. Keep it self-contained (inline CSS/JS) — there is
no bundler. Match the dashboard's tokens so it doesn't look foreign:

```css
--bg:#0d0f15; --surface:#1a1d27; --surface-2:#20232f; --border:#2a2d3a;
--ink:#e6e8f0; --ink-2:#a8adc2; --ink-3:#767c93; --accent:#4f8ef7;
--ok:#4caf7d; --warn:#e0b44a; --crit:#e05c5c;
```

Include a way back: `<a href="/">← rpi.lan</a>`.

**Separate data from rendering.** Put facts in a sibling `data.json` and `fetch()` it
rather than hardcoding them in the HTML. `frontend/architecture/` does this, with
`homelab/Tools/architecture/build-arch-data.py` generating the JSON and validating
referential integrity before writing. That pattern pays for itself the moment the
content needs updating — and it means a stale fact is a one-line data edit, not a
hunt through markup.

If you produce a chart or diagram, load the **`dataviz` skill** first and run its
palette validator — for a diagram validate with `--pairs all`, since a map can place
any two colors adjacent. Note the rpi host has no `node`; run the validator on
noblenumbat.

### Backend route

```js
// backend/routes/thing.js
const express = require('express');
const router = express.Router();
router.get('/status', (req, res) => res.json({ ok: true }));
module.exports = router;
```

Register it in `backend/index.js` beside the others:

```js
const thingRouter = require('./routes/thing');
app.use('/api/thing', thingRouter);
```

**`/api/health` is taken** by the webapp's own healthcheck — that is why the health bot
proxy lives at `/api/healthdigest`.

Data already available inside the container (read-only mounts from opti's pool):

| Path | Contents |
|---|---|
| `/agent-logs` | agent JSON reports (`homelab-doctor-latest.json`, `hardware-latest.json`, …) |
| `/reports` | security agent reports |
| `/workspace` | the whole `ptm4` repo, incl. `homelab/agentic/workspace.json` |

Prefer reading those files over new SSH round trips — `routes/architecture.js` reshapes
the newest doctor report and is the cheap-live-status pattern to copy.

### Sidebar link

Add to `frontend/index.html` under `.nav-links`. Standalone pages get a plain path;
SPA tabs get a hash route:

```html
<li><a href="/thing/" class="nav-link">Thing</a></li>
<li><a href="#thing" class="nav-link" data-route="thing">Thing</a></li>
```

## 3. Deploy

Two routes. **Both matter** — the direct copy makes it live, the commit makes it survive.

### Fast iteration (direct copy)

Peter commits his own work, so don't commit or push. To make a change live now:

```bash
# static frontend only — served immediately, no restart
rsync -av homelab/RPI-srv/webapp/frontend/ rpi:/srv/docker/compose/webapp/frontend/

# backend route changes also need the Node process re-exec'd
rsync -av homelab/RPI-srv/webapp/backend/ rpi:/srv/docker/compose/webapp/backend/
ssh rpi 'cd /srv/docker/compose && docker compose restart webapp'
```

### Persistence (CI)

`/srv/docker/compose/webapp/` is **not** the repo — it is a copy. A `git push` to `main`
is what makes the change durable, via `.github/workflows/rpi-deploy.yml`: the rpi's
self-hosted runner copies `homelab/RPI-srv/webapp/.` over and restarts the container.

So always tell the user to commit and push, or the next deploy overwrites the change
back to the committed state. Two gotchas:

- The workflow has a **`paths:` filter**. Files under `homelab/RPI-srv/webapp/**` are
  covered; a new directory elsewhere (e.g. a generator under `homelab/Tools/`) will
  *not* trigger a deploy on its own.
- The job is pinned to `[self-hosted, ARM64]`. A bare `self-hosted` label also matches
  opti's x86 runner, which would deploy to the wrong host.

## 4. Verify — don't assume

A copied file that throws on load looks identical to a working one from the shell.

```bash
curl -sk https://webapp.rpi.lan:8443/thing/ | head -20     # page serves
curl -sk https://webapp.rpi.lan:8443/api/thing/status      # route responds
ssh rpi 'cd /srv/docker/compose && docker compose logs --tail=30 webapp'
```

Then actually load it in a browser and check the console — a JS error in a
self-contained page is invisible to `curl`, which happily returns the bytes. For local
iteration, serve `frontend/` with a stub for any `/api/...` the page calls, so the
live-data path gets exercised rather than silently falling into its error branch.

## Caveats

- **`app.js` and `style.css` are shared.** A standalone page must not depend on them
  (it isn't served them); an SPA tab must not break the other tabs.
- **Bot control APIs are internal-only.** The five `discord-*` containers expose `:8080`
  on the `internal` docker network and are not published to the host — only the webapp
  can reach them. Manage bots through the webapp, never by editing files on the rpi.
- **opti is a hard dependency.** The `/agent-logs`, `/reports` and `/workspace` mounts
  are CIFS to `//opti/fs`. If opti is down those reads hang and the tabs empty out —
  handle fetch failures gracefully rather than rendering a blank page.
- **nginx timeouts.** The default 60s proxy read timeout is raised only for
  `/api/llama/` (cold LLM prompts). A new slow route needs its own `location` block in
  `homelab/RPI-srv/nginx-wg.conf`.
- The techdoc for the wider stack is `homelab/homelab-techdoc.md`; host access is
  covered by the `homelab-ssh` skill.
