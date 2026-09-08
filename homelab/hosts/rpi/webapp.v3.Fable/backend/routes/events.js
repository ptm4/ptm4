// /api/events — server-sent events. One long-lived GET per browser tab; the
// pollers emit on the bus, this fans out. Works through the existing nginx config
// without a dedicated location block: `X-Accel-Buffering: no` turns proxy buffering
// off per-response, and the 25s heartbeat keeps the default 60s proxy_read_timeout
// from ever firing. (A dedicated block is still added at go-live as belt-and-braces.)
//
// Wire format: standard SSE. `event:` is the bus event name, `data:` the JSON
// payload, `id:` the bus sequence number. A `hello` event opens every stream with
// the server time and which events exist, so a client can tell "connected but quiet"
// from "nothing is being emitted".
//
// GET /api/events/status is plain JSON for the smoke suite and the topbar pip.
const EVENT_NAMES = ['vitals', 'containers', 'activity', 'notifications', 'incidents', 'streams'];
const HEARTBEAT_MS = 25_000;

module.exports = async function eventRoutes(app) {
  let clients = 0;

  app.get('/status', async () => ({
    enabled: true,
    clients,
    events: EVENT_NAMES,
    last: app.events.last(),
    seq: app.events.seq(),
    heartbeat_ms: HEARTBEAT_MS,
    generated_at: new Date().toISOString(),
  }));

  app.get('/', (req, reply) => {
    reply.hijack();
    const res = reply.raw;
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
      'Access-Control-Allow-Origin': '*',
    });
    res.write('retry: 5000\n\n');
    clients += 1;

    const send = (name, payload, seq) => {
      if (res.writableEnded || res.destroyed) return;
      const body = JSON.stringify(payload ?? null);
      res.write(`event: ${name}\nid: ${seq ?? 0}\ndata: ${body}\n\n`);
    };

    send('hello', { server_time: new Date().toISOString(), events: EVENT_NAMES, last: app.events.last() }, app.events.seq());

    // The bus's wildcard channel: (name, payload, seq).
    const onAny = (name, payload, seq) => { if (EVENT_NAMES.includes(name)) send(name, payload, seq); };
    app.events.on('*', onAny);

    const beat = setInterval(() => {
      if (res.writableEnded || res.destroyed) return;
      res.write(`: ping ${Date.now()}\n\n`);
    }, HEARTBEAT_MS);
    beat.unref();

    const cleanup = () => {
      clearInterval(beat);
      app.events.off('*', onAny);
      clients = Math.max(0, clients - 1);
      if (!res.writableEnded) { try { res.end(); } catch (_) { /* already gone */ } }
    };
    req.raw.on('close', cleanup);
    req.raw.on('error', cleanup);
  });
};
