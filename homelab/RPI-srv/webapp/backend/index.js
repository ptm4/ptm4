const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = 3000;

app.use(cors());
app.use(express.json());
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

const agentsRouter = require('./routes/agents');
app.use('/api/agents', agentsRouter);

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

// architecture page's Sync button — live per-host status from the latest agent reports
const architectureRouter = require('./routes/architecture');
app.use('/api/architecture', architectureRouter);

// agentic workspace manifest — portable skills/rules/runbooks description, read live from
// opti's homelab/agentic/workspace.json (bind-mounted at /agentic)
const agenticRouter = require('./routes/agentic');
app.use('/api/agentic', agenticRouter);

// ─────────────────────────────────────────────────────────────────────────────

app.listen(PORT, () => console.log(`webapp listening on :${PORT}`));
