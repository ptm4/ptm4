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
    // A real event, not an SSE comment: comments are invisible to the browser's
    // EventSource API, and the client needs a heartbeat it can SEE to notice a stream
    // that a proxy is holding open after Pertal went away (it declares it dead at 45s).
    const keepalive = setInterval(() => send('ping', { t: Date.now() }), 15_000);
    const close = () => {
      clearInterval(keepalive);
      app.events.off(listener);
    };
    req.raw.on('close', close);
    res.on('error', close);
  });
};
