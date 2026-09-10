// Uptime Kuma read-model for the dashboard's Monitors panel.
//
// Kuma 1.x management lives behind the admin password (socket.io); its uk1_ API key
// unlocks exactly one thing — GET /metrics with Basic auth — which happens to be all
// a status panel needs. This route fetches container-to-container over the compose
// network, parses the Prometheus text into JSON, and never exposes the key to the
// browser. Read-only by construction.
const KUMA_URL = process.env.KUMA_URL || 'http://uptime-kuma:3001';
const KUMA_API_KEY = process.env.KUMA_API_KEY || '';

// monitor_status{monitor_name="rpi: Dozzle",monitor_type="http",...} 1
const LINE_RE = /^(monitor_status|monitor_response_time)\{([^}]*)\}\s+(-?[\d.]+)$/;
const NAME_RE = /monitor_name="((?:[^"\\]|\\.)*)"/;
const TYPE_RE = /monitor_type="((?:[^"\\]|\\.)*)"/;
const STATUS = { 0: 'down', 1: 'up', 2: 'pending', 3: 'maintenance' };

module.exports = async function uptimeRoutes(app) {
  app.get('/', async (req, reply) => {
    if (!KUMA_API_KEY) {
      return reply.code(503).send({ ok: false, error: 'KUMA_API_KEY not configured' });
    }
    try {
      const r = await fetch(`${KUMA_URL}/metrics`, {
        headers: {
          Authorization: `Basic ${Buffer.from(`:${KUMA_API_KEY}`).toString('base64')}`,
        },
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) {
        return reply.code(502).send({ ok: false, error: `Kuma /metrics HTTP ${r.status}` });
      }
      const text = await r.text();
      const monitors = new Map();
      for (const line of text.split('\n')) {
        const m = LINE_RE.exec(line.trim());
        if (!m) continue;
        const name = NAME_RE.exec(m[2])?.[1];
        if (!name) continue;
        const entry = monitors.get(name) || { name, type: TYPE_RE.exec(m[2])?.[1] || null };
        if (m[1] === 'monitor_status') entry.status = STATUS[Number(m[3])] || 'unknown';
        else entry.ms = m[3] === '-1' ? null : Math.round(Number(m[3]));
        monitors.set(name, entry);
      }
      const list = [...monitors.values()].sort((a, b) => a.name.localeCompare(b.name));
      const count = (s) => list.filter((x) => x.status === s).length;
      return {
        ok: true,
        total: list.length,
        up: count('up'),
        down: count('down'),
        pending: count('pending'),
        maintenance: count('maintenance'),
        monitors: list,
        checked_at: new Date().toISOString(),
      };
    } catch (e) {
      return reply.code(502).send({ ok: false, error: `Kuma unreachable: ${e.message}` });
    }
  });
};
