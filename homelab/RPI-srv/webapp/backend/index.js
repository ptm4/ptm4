const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = 3000;

app.use(cors());
// Default 100kb is too small for an architecture-agent fragment (a full docker inspect
// across ~15 containers runs ~30-60kb) — raised here since this is the outermost parser
// and any route-level express.json() would just be a no-op after this one runs.
app.use(express.json({ limit: '5mb' }));
app.use(express.static(path.join(__dirname, '../frontend')));

// ─────────────────────────────────────────────────────────────────────────────
// Framework starter — add your routes below.
//
// Pattern:
//   app.get('/api/example', (req, res) => { res.json({ hello: 'world' }); });
//
// Ideas to build out:
//   - Pi system stats  →  GET /api/system  (parse /proc/meminfo, /proc/loadavg)
//   - Pi-hole summary  →  GET /api/pihole  (proxy http://localhost/api/stats)
//   - Docker status    →  GET /api/containers (docker ps via child_process)
//   - Samba sessions   →  GET /api/samba  (smbstatus via docker exec)
//   - Notes / bookmarks → full CRUD with a JSON file store
//   - Link shortcuts   →  GET /api/links  (serve a static JSON config)
// ─────────────────────────────────────────────────────────────────────────────

// Health check — useful for NGINX upstream checks
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', host: 'webapp.rpi.lan', uptime: process.uptime() });
});

// ── ADD YOUR ROUTES HERE ──────────────────────────────────────────────────────

const reportsRouter = require('./routes/reports');
app.use('/api/reports', reportsRouter);

// The 4 scheduled runners (homelab-doctor, hardware, software, network) — surfaced on
// the Reports tab. Renamed from /api/agents 2026-07-25 to free that mount for real
// per-host agents (see routes/architecture.js's /ingest).
const runnersRouter = require('./routes/runners');
app.use('/api/runners', runnersRouter);

const weatherRouter = require('./routes/weather');
app.use('/api/weather', weatherRouter);

// bot proxies — /api/health is taken by the webapp's own healthcheck, hence /api/healthdigest
const healthdigestRouter = require('./routes/healthdigest');
app.use('/api/healthdigest', healthdigestRouter);

const jellyfinRouter = require('./routes/jellyfin');
app.use('/api/jellyfin', jellyfinRouter);

const sportsRouter = require('./routes/sports');
app.use('/api/sports', sportsRouter);

const hltvRouter = require('./routes/hltv');
app.use('/api/hltv', hltvRouter);

// local LLM (android phone) — status/models/runbooks/chat, see routes/llama.js
const llamaRouter = require('./routes/llama');
app.use('/api/llama', llamaRouter);

// architecture page's Sync button — live per-host status from the latest agent reports,
// plus /ingest and /data for the per-host architecture agents (routes/agents.js talks
// to those same agents directly for status + Force Sync)
const architectureRouter = require('./routes/architecture');
app.use('/api/architecture', architectureRouter);

// per-host architecture agents — status + Force Sync for the Agents config page.
// agents.js requires ./architecture itself (Node caches the module either way) to
// reuse its buildMergedData for drift counts.
const agentsRouter = require('./routes/agents');
app.use('/api/agents', agentsRouter);

// agentic workspace manifest — portable skills/rules/runbooks description, read live from
// opti's homelab/agentic/workspace.json (bind-mounted at /agentic)
const agenticRouter = require('./routes/agentic');
app.use('/api/agentic', agenticRouter);

// samba — view/edit the hand-managed [red] share config on opti (proxied to the dispatcher,
// which owns the validate/backup/write/reload/verify pipeline)
const sambaRouter = require('./routes/samba');
app.use('/api/samba', sambaRouter);

// mission-control Home read-model — /api/containers, /api/timers, /api/activity,
// /api/trends (all read-only reshapes of data already on disk; see routes/dashboard.js)
const dashboardRouter = require('./routes/dashboard');
app.use('/api', dashboardRouter);

// live Pi-hole v6 stats (+ pause/resume) — needs PIHOLE_WEB_PASSWORD in env
const piholeRouter = require('./routes/pihole');
app.use('/api/pihole', piholeRouter);

// live host vitals — polls each arch agent's /vitals every 30s into a ring buffer and
// serves it as the Home sparkline series (the daily hardware report is far too coarse)
const vitalsRouter = require('./routes/vitals');
app.use('/api/vitals', vitalsRouter);

// ─────────────────────────────────────────────────────────────────────────────

app.listen(PORT, () => console.log(`webapp listening on :${PORT}`));
