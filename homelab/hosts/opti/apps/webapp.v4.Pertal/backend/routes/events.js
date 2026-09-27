// GET /api/events — Server-Sent Events. A new client gets the full state first, then
// every change: resources, snapshot metas, jobs, activity. nginx must not buffer this
// location (X-Accel-Buffering: no is set here as well).
'use strict';

module.exports = async function eventRoutes(app) {
  app.get('/', (req, reply) => {
    reply.hijack();
    const res = reply.raw;
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    const send = (name, payload) => {
      res.write(`event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`);
    };
    res.write('retry: 3000\n\n');
    send('hello', {
      version: app.pertal.version,
      resources: app.pertal.state.resources,
      summary: app.pertal.state.summary,
      snapshots: app.snapshots.metas(),
      jobs: app.jobs.list({ limit: 20 }),
      built_at: app.pertal.state.built_at,
    });

    const listener = (name, payload) => {
      try { send(name, payload); } catch (_) { /* socket already gone */ }
    };
    app.events.on(listener);
    const keepalive = setInterval(() => res.write(': keepalive\n\n'), 20_000);
    const close = () => {
      clearInterval(keepalive);
      app.events.off(listener);
    };
    req.raw.on('close', close);
    res.on('error', close);
  });
};
