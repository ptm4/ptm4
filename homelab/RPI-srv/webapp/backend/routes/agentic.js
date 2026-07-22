// Serves the agentic workspace manifest (homelab/agentic/workspace.json) so the dashboard
// can display it and any agent can fetch it. Single source of truth: the file lives in the
// ptm4 repo on opti under homelab/agentic/ and is bind-mounted read-only into this container
// at /agentic (see docker-compose.yml). Falls back to the in-repo path for local dev.
const express = require('express');
const fs = require('fs');
const path = require('path');

const router = express.Router();

// /agentic in the container (compose mount) → opti:.../homelab/agentic. Dev fallback walks
// up out of backend/routes to the repo's homelab/agentic.
const AGENTIC_DIR = fs.existsSync('/agentic')
  ? '/agentic'
  : path.join(__dirname, '..', '..', '..', 'agentic');

const MANIFEST = path.join(AGENTIC_DIR, 'workspace.json');

// GET /api/agentic — the parsed manifest, plus where it was read from and its mtime.
router.get('/', (req, res) => {
  try {
    const raw = fs.readFileSync(MANIFEST, 'utf8');
    const data = JSON.parse(raw);
    let mtime = null;
    try { mtime = fs.statSync(MANIFEST).mtime.toISOString(); } catch (_) {}
    res.json({ ok: true, source: MANIFEST, mtime, manifest: data });
  } catch (err) {
    res.status(503).json({
      ok: false,
      source: MANIFEST,
      error: `manifest not readable: ${err.code || err.message}`,
      hint: 'Run: python3 homelab/agentic/gen-workspace.py on opti, and ensure the /agentic mount is present.',
    });
  }
});

module.exports = router;
