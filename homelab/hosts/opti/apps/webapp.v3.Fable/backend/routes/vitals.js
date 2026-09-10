// Read side of the vitals ring buffer. The poller itself is a lifecycle plugin
// (plugins/vitals-poller.js) that decorates the app with `vitals` — this module
// only serves whatever state that plugin holds.
module.exports = async function vitalsRoutes(app) {
  // GET /api/vitals — rollup: latest sample + buffer depth per host
  app.get('/', async () => {
    const { state, POLL_MS } = app.vitals;
    const hosts = {};
    for (const [host, st] of Object.entries(state)) {
      hosts[host] = {
        count: st.samples.length,
        latest: st.samples[st.samples.length - 1] || null,
        agent_version: st.agent_version || null,
        error: st.lastError,
      };
    }
    return { hosts, interval_s: POLL_MS / 1000, generated_at: new Date().toISOString() };
  });

  // GET /api/vitals/:host?range=1h|3h|6h|9h|24h|48h  (or legacy ?points=240)
  // Ranges up to 6h come from the 30s ring; longer ones from the 5-minute buckets
  // (interval_s in the response says which resolution you got).
  const RANGES = {
    '1h':  { src: 'samples', n: 120 },
    '3h':  { src: 'samples', n: 360 },
    '6h':  { src: 'samples', n: 720 },
    '9h':  { src: 'long', n: 108 },
    '24h': { src: 'long', n: 288 },
    '48h': { src: 'long', n: 576 },
  };

  app.get('/:host', async (req, reply) => {
    const { state, POLL_MS, MAX_SAMPLES, LONG_BUCKET_S } = app.vitals;
    const st = state[req.params.host];
    if (!st) return reply.code(404).send({ error: `unknown host '${req.params.host}'` });

    let samples, intervalS, range = null;
    if (req.query.range != null) {
      const r = RANGES[req.query.range];
      if (!r) {
        return reply.code(400).send({ error: `bad range — use one of ${Object.keys(RANGES).join(', ')}` });
      }
      range = req.query.range;
      const ring = r.src === 'long' ? (st.long ?? []) : st.samples;
      samples = ring.slice(-r.n);
      intervalS = r.src === 'long' ? LONG_BUCKET_S : POLL_MS / 1000;
    } else {
      const points = Math.min(parseInt(req.query.points, 10) || 240, MAX_SAMPLES);
      samples = st.samples.slice(-points);
      intervalS = POLL_MS / 1000;
    }

    return {
      host: req.params.host,
      interval_s: intervalS,
      range,
      cores: st.cores || null,
      agent_version: st.agent_version || null,
      error: st.lastError,
      samples,
      latest: st.samples[st.samples.length - 1] || null,
    };
  });
};
