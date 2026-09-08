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
const { dispatch } = require('../lib/controls');

const MAX_BYTES = 64 * 1024;

module.exports = async function sambaRoutes(app) {
  const proxy = (reply, promise) => promise
    .then((r) => reply.code(r.status).send(r.data))
    .catch((e) => reply.code(e.statusCode || 502).send({ error: e.message }));

  // Current config + validity + whether it has drifted from the repo copy
  app.get('/config', (req, reply) => proxy(reply, dispatch('GET', '/samba/config')));

  app.get('/backups', (req, reply) => proxy(reply, dispatch('GET', '/samba/backups')));

  app.get('/status', (req, reply) => proxy(reply, dispatch('GET', '/samba/status')));

  // Dry run: validate without writing anything
  app.post('/validate', (req, reply) => {
    const content = req.body?.content;
    if (typeof content !== 'string') return reply.code(400).send({ error: 'content must be a string' });
    if (Buffer.byteLength(content) > MAX_BYTES) return reply.code(413).send({ error: 'config too large' });
    return proxy(reply, dispatch('POST', '/samba/validate', { content }));
  });

  app.post('/config', (req, reply) => {
    const content = req.body?.content;
    if (typeof content !== 'string') return reply.code(400).send({ error: 'content must be a string' });
    if (!content.trim()) return reply.code(400).send({ error: 'refusing to write an empty config' });
    if (Buffer.byteLength(content) > MAX_BYTES) return reply.code(413).send({ error: 'config too large' });
    return proxy(reply, dispatch('POST', '/samba/config', { content }));
  });

  app.post('/rollback', (req, reply) => {
    const stamp = req.body?.stamp;
    if (!/^\d{8}-\d{6}$/.test(stamp || '')) return reply.code(400).send({ error: 'invalid backup id' });
    return proxy(reply, dispatch('POST', '/samba/rollback', { stamp }));
  });
};
