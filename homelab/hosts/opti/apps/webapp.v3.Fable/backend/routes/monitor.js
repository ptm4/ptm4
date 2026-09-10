// Monitor's live API.  Existing /api/vitals remains deliberately untouched at 30s;
// this route owns the bounded two-second detail stream used only by /monitor.
const { AGENT_HOSTS } = require('../lib/hosts');

const VALID_INTERVALS = new Set([2, 5, 10]);
const parseHosts = (value) => {
  const requested = String(value || '').split(',').filter(Boolean);
  const hosts = requested.length ? requested : Object.keys(AGENT_HOSTS);
  return [...new Set(hosts)];
};

function validateHosts(hosts, reply) {
  const unknown = hosts.filter((host) => !AGENT_HOSTS[host]);
  if (unknown.length) { reply.code(400).send({ error: `unknown monitor host(s): ${unknown.join(', ')}` }); return false; }
  return true;
}

function requireSameOrigin(req, reply) {
  const origin = req.headers.origin;
  if (!origin) return true; // same-origin navigation and Fastify inject omit Origin.
  const expected = `${req.protocol}://${req.headers.host}`;
  if (origin === expected) return true;
  reply.code(403).send({ error: 'cross-origin monitor actions are not allowed' });
  return false;
}

module.exports = async function monitorRoutes(app) {
  app.get('/status', async () => app.monitor.rollup());

  app.get('/snapshot', async (req, reply) => {
    const hosts = parseHosts(req.query?.hosts);
    if (!validateHosts(hosts, reply)) return;
    const interval = Number(req.query?.interval || 2);
    if (!VALID_INTERVALS.has(interval)) return reply.code(400).send({ error: 'interval must be 2, 5, or 10 seconds' });
    hosts.forEach((host) => app.monitor.ensure(host, interval * 1000));
    return app.monitor.rollup(hosts);
  });

  app.get('/:host/capabilities', async (req, reply) => {
    const host = req.params.host;
    if (!AGENT_HOSTS[host]) return reply.code(404).send({ error: `unknown monitor host '${host}'` });
    try { return await app.monitor.capabilities(host); }
    catch (err) { return reply.code(503).send({ error: err.message || String(err) }); }
  });

  app.get('/:host/history', async (req, reply) => {
    const host = req.params.host;
    const st = app.monitor.state[host];
    if (!st) return reply.code(404).send({ error: `unknown monitor host '${host}'` });
    const interval = Number(req.query?.interval || 2);
    if (!VALID_INTERVALS.has(interval)) return reply.code(400).send({ error: 'interval must be 2, 5, or 10 seconds' });
    app.monitor.ensure(host, interval * 1000);
    return { host, interval_s: app.monitor.intervalMs / 1000, maximum_s: app.monitor.maxSamples * app.monitor.intervalMs / 1000,
      available_s: Math.max(0, (st.samples.length - 1) * app.monitor.intervalMs / 1000), samples: st.samples };
  });

  app.get('/:host/process/:pid', async (req, reply) => {
    const host = req.params.host;
    if (!AGENT_HOSTS[host]) return reply.code(404).send({ error: `unknown monitor host '${host}'` });
    const pid = Number(req.params.pid);
    if (!Number.isInteger(pid) || pid < 1) return reply.code(400).send({ error: 'PID must be a positive integer' });
    const st = app.monitor.state[host];
    const latest = st.samples.at(-1);
    const row = latest?.processes?.find((process) => process.pid === pid);
    if (!row) return reply.code(404).send({ error: 'process is absent from the current Monitor snapshot' });
    return { host, boot_id: latest.boot_id, process: row };
  });

  app.post('/:host/process/:pid/signal', async (req, reply) => {
    if (!requireSameOrigin(req, reply)) return;
    const host = req.params.host;
    if (!AGENT_HOSTS[host]) return reply.code(404).send({ error: `unknown monitor host '${host}'` });
    const pid = Number(req.params.pid);
    const body = req.body || {};
    if (!Number.isInteger(pid) || pid < 2 || typeof body.boot_id !== 'string' || !Number.isInteger(body.start_ticks) || typeof body.signal_name !== 'string') {
      return reply.code(400).send({ error: 'pid, boot_id, start_ticks, and signal_name are required' });
    }
    if (!body.request_id || typeof body.request_id !== 'string') return reply.code(400).send({ error: 'request_id is required' });
    try {
      const { job, result } = await app.jobs.run({
        kind: 'process-signal', title: `${body.signal_name} PID ${pid} on ${host}`, host, target: `pid:${pid}`, danger: true,
        steps: [
          { key: 'validate', label: 'Validate the selected process identity' },
          { key: 'signal', label: `Send ${body.signal_name}` },
          { key: 'observe', label: 'Observe the expected process state' },
        ],
      }, async (job) => {
        app.monitor.ensure(host);
        await app.monitor.tick(host, true);
        const before = await job.step('validate', async (note) => {
          const latest = app.monitor.state[host].samples.at(-1);
          const row = latest?.processes?.find((p) => p.pid === pid && p.start_ticks === body.start_ticks && latest.boot_id === body.boot_id);
          if (!row) throw new Error('process identity is stale; refresh the list');
          note(`${row.program} (${row.user}) matches selected identity`);
          return row;
        });
        const sent = await job.step('signal', async (note) => {
          const output = await app.monitor.request(host, `/monitor/process/${pid}/signal`, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
          note(`${output.signal_name} delivered through a process handle`);
          return output;
        });
        await job.step('observe', async (note) => {
          await new Promise((resolve) => setTimeout(resolve, 450));
          await app.monitor.tick(host, true);
          const after = app.monitor.state[host].samples.at(-1)?.processes?.find((p) => p.pid === pid && p.start_ticks === body.start_ticks);
          if (body.signal_name === 'SIGSTOP' && after?.state === 'T') note('process is stopped');
          else if (body.signal_name === 'SIGCONT' && after && after.state !== 'T') note('process continued');
          else if ((body.signal_name === 'SIGTERM' || body.signal_name === 'SIGKILL') && !after) note('process exited');
          else note('signal delivered; expected state was not yet observed');
          return { before, after };
        });
        return sent;
      });
      return { host, ...result, job };
    } catch (err) {
      return reply.code(409).send({ host, ok: false, job: err.job || null, error: err.message || String(err) });
    }
  });

  app.get('/events', (req, reply) => {
    const hosts = parseHosts(req.query?.hosts);
    if (!validateHosts(hosts, reply)) return;
    const interval = Number(req.query?.interval || 2);
    if (!VALID_INTERVALS.has(interval)) return reply.code(400).send({ error: 'interval must be 2, 5, or 10 seconds' });
    hosts.forEach((host) => app.monitor.ensure(host, interval * 1000));
    reply.hijack();
    const res = reply.raw;
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
    const send = (event, payload) => { if (!res.writableEnded && !res.destroyed) res.write(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`); };
    send('snapshot', app.monitor.rollup(hosts));
    const listeners = hosts.map((host) => {
      const listener = () => send('snapshot', app.monitor.rollup(hosts));
      app.monitorEvents.on(host, listener);
      return [host, listener];
    });
    const heartbeat = setInterval(() => { if (!res.writableEnded && !res.destroyed) res.write(`: ping ${Date.now()}\n\n`); }, 25_000);
    heartbeat.unref();
    const cleanup = () => { clearInterval(heartbeat); listeners.forEach(([host, listener]) => app.monitorEvents.off(host, listener)); if (!res.writableEnded) res.end(); };
    req.raw.on('close', cleanup); req.raw.on('error', cleanup);
  });
};
