// Samba control — view and edit the hand-managed [red] share config on opti.
//
// Thin proxy to the opti dispatcher's /samba/* endpoints (see hosts/opti/samba_config.py).
// All the safety lives there, on the host that owns the file: validate-composed -> backup ->
// atomic write -> reload -> verify, with automatic rollback if the share stops resolving.
// This file deliberately adds no logic of its own beyond shape-checking the request.
//
// Why the config is not in /etc/samba: OpenMediaVault regenerates smb.conf from its own DB
// and has no ZFS backend, so it cannot model this share. The share lives in
// /etc/homelab/samba-red.conf and OMV is pointed at it with an `include =` stored in OMV's
// own "Extra options" field — so OMV maintains the link and never overwrites our file.
const express = require('express');
const { dispatch } = require('./controls');

const router = express.Router();

const MAX_BYTES = 64 * 1024;

function proxy(res, promise) {
  promise
    .then((r) => res.status(r.status).json(r.data))
    .catch((e) => res.status(e.statusCode || 502).json({ error: e.message }));
}

// Current config + validity + whether it has drifted from the repo copy
router.get('/config', (req, res) => proxy(res, dispatch('GET', '/samba/config')));

router.get('/backups', (req, res) => proxy(res, dispatch('GET', '/samba/backups')));

router.get('/status', (req, res) => proxy(res, dispatch('GET', '/samba/status')));

// Dry run: validate without writing anything
router.post('/validate', (req, res) => {
  const content = req.body?.content;
  if (typeof content !== 'string') return res.status(400).json({ error: 'content must be a string' });
  if (Buffer.byteLength(content) > MAX_BYTES) return res.status(413).json({ error: 'config too large' });
  proxy(res, dispatch('POST', '/samba/validate', { content }));
});

router.post('/config', (req, res) => {
  const content = req.body?.content;
  if (typeof content !== 'string') return res.status(400).json({ error: 'content must be a string' });
  if (!content.trim()) return res.status(400).json({ error: 'refusing to write an empty config' });
  if (Buffer.byteLength(content) > MAX_BYTES) return res.status(413).json({ error: 'config too large' });
  proxy(res, dispatch('POST', '/samba/config', { content }));
});

router.post('/rollback', (req, res) => {
  const stamp = req.body?.stamp;
  if (!/^\d{8}-\d{6}$/.test(stamp || '')) return res.status(400).json({ error: 'invalid backup id' });
  proxy(res, dispatch('POST', '/samba/rollback', { stamp }));
});

module.exports = router;
