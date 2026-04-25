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



// ─────────────────────────────────────────────────────────────────────────────

app.listen(PORT, () => console.log(`webapp listening on :${PORT}`));
