// Notification center — turns findings that already exist in the reports into an
// inbox with acknowledge state. The collector and the ack store live in
// lib/findings.js (shared with routes/incidents.js); the response shapes here are
// the v2 contract, byte for byte.
const { collect, readAcks, writeAcks } = require('../lib/findings');

module.exports = async function notificationRoutes(app) {
  // GET /api/notifications — every actionable finding, with its ack state.
  app.get('/', async (req) => {
    const acks = readAcks();
    const all = collect().map((n) => ({ ...n, acked: !!acks[n.id], acked_at: acks[n.id]?.at || null }));
    const includeAcked = req.query.all === '1';
    const items = includeAcked ? all : all.filter((n) => !n.acked);
    return {
      items,
      unacked: all.filter((n) => !n.acked).length,
      total: all.length,
      generated_at: new Date().toISOString(),
    };
  });

  // POST /api/notifications/:id/ack — acknowledge (or un-acknowledge) one finding.
  app.post('/:id/ack', {
    schema: {
      params: { type: 'object', properties: { id: { type: 'string', pattern: '^[a-f0-9]{16}$' } } },
      body: { type: 'object', properties: { acked: { type: 'boolean' } } },
    },
  }, async (req) => {
    const acks = readAcks();
    const acked = req.body?.acked !== false;
    if (acked) acks[req.params.id] = { at: new Date().toISOString() };
    else delete acks[req.params.id];
    writeAcks(acks);
    if (app.events) app.events.emit('notifications', { unacked: collect().filter((n) => !acks[n.id]).length, total: collect().length });
    return { ok: true, id: req.params.id, acked };
  });

  // POST /api/notifications/ack-all — acknowledge everything currently open.
  app.post('/ack-all', async () => {
    const acks = readAcks();
    const at = new Date().toISOString();
    let n = 0;
    for (const item of collect()) {
      if (!acks[item.id]) { acks[item.id] = { at }; n++; }
    }
    writeAcks(acks);
    if (app.events) app.events.emit('notifications', { unacked: 0, total: collect().length });
    return { ok: true, acked: n };
  });
};
