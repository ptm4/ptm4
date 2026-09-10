// /api/services — the service catalog joined with what the fleet already knows:
// the server-side link probes and the container states. One request gives the
// Launchpad every tile with a live health dot; no new probing is added here.
const { SERVICES } = require('../lib/services');
const { cachedInject } = require('../lib/hldb-cache');

module.exports = async function serviceRoutes(app) {
  app.get('/', async () => {
    const [lc, ct] = await Promise.all([
      cachedInject(app, '/api/linkcheck', 30_000),
      cachedInject(app, '/api/containers', 30_000),
    ]);
    const origins = lc.status === 200 ? (lc.data?.origins || {}) : {};
    const byContainer = {};
    for (const h of (ct.status === 200 ? ct.data?.hosts || [] : [])) {
      for (const c of h.containers || []) byContainer[`${h.host}/${c.name}`] = c;
    }
    const services = SERVICES.map((s) => {
      const probe = s.probe ? origins[s.probe] : null;
      const c = s.container && s.host ? byContainer[`${s.host}/${s.container}`] : null;
      let state = 'unknown';
      // probe.up is three-valued: true, false, or null for an origin this tier
      // structurally cannot reach (see PROBE_ORIGINS in dashboard.js). null must fall
      // through to the container evidence, or land on 'unknown' — it must never
      // become 'down', because "I cannot see it from here" is not "it is down", and
      // a Launchpad that cries wolf about OMV every day stops being read.
      if (probe && probe.up === true) state = 'up';
      else if (probe && probe.up === false) state = 'down';
      else if (c) state = c.up ? 'up' : 'down';
      else if (s.internal) state = 'up';
      return {
        ...s,
        state,
        probe_status: probe?.status ?? null,
        probe_error: probe?.error ?? null,
        container_state: c ? (c.up ? 'running' : (c.state || 'down')) : null,
        update_available: !!c?.update_available,
      };
    });
    return {
      services,
      categories: [...new Set(SERVICES.map((s) => s.category))],
      checked_at: lc.data?.checked_at || null,
      generated_at: new Date().toISOString(),
    };
  });
};
