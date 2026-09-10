// Feed poller — turns the file-backed read models into push events. Every 60s it
// asks the app's OWN routes (via inject, so there is exactly one implementation of
// each read model) for containers, activity and notifications, diffs against the
// previous answer, and emits on the event bus only when something changed.
//
// Cost model: these routes read files under /agent-logs, /reports and the arch
// fragments — no SSH, no upstream HTTP — so polling them here adds nothing to any
// other host's load. That is the rule for anything added to this loop.
const fp = require('fastify-plugin');
const rules = require('../lib/rules');

const POLL_MS = 60_000;

const containerKey = (h) => (h.containers || []).map((c) => `${h.host}/${c.name}:${c.up ? 1 : 0}:${c.update_available ? 1 : 0}`).join(',');
const activityKey = (e) => `${e.ts}|${e.source}|${e.host}|${e.message}`;

module.exports = fp(async function feedPoller(app) {
  let prev = { containers: null, activity: new Set(), notifications: null };
  let timer = null;
  let running = false;

  async function fetchJson(url) {
    const r = await app.inject({ method: 'GET', url });
    if (r.statusCode !== 200) return null;
    try { return r.json(); } catch (_) { return null; }
  }

  async function tick() {
    if (running) return;
    running = true;
    try {
      const containers = await fetchJson('/api/containers');
      if (containers) {
        const key = (containers.hosts || []).map(containerKey).join(';');
        if (prev.containers !== null && key !== prev.containers) app.events.emit('containers', containers);
        prev.containers = key;
      }

      const activity = await fetchJson('/api/activity?limit=50');
      if (activity) {
        const seen = new Set((activity.events || []).map(activityKey));
        if (prev.activity.size) {
          const fresh = (activity.events || []).filter((e) => !prev.activity.has(activityKey(e)));
          if (fresh.length) app.events.emit('activity', { events: fresh, generated_at: activity.generated_at || null });
        }
        prev.activity = seen;
      }

      // Alert rules first, so their hits are already on disk when notifications are read.
      try {
        const out = await rules.run(app);
        if (out.changed) app.events.emit('incidents', { source: 'rules', hits: out.hits.length });
      } catch (_) { /* a failed evaluation is a missed tick */ }

      const notif = await fetchJson('/api/notifications');
      if (notif) {
        const key = `${notif.unacked}/${notif.total}`;
        if (prev.notifications !== null && key !== prev.notifications) {
          app.events.emit('notifications', { unacked: notif.unacked, total: notif.total });
        }
        prev.notifications = key;
      }
    } catch (_) {
      /* a failed tick is a missed diff, never an error — the next one catches up */
    } finally {
      running = false;
    }
  }

  app.decorate('feedPoller', { POLL_MS, tick });

  app.addHook('onReady', async () => {
    if (process.env.FEED_DISABLED === '1' || process.env.VITALS_DISABLED === '1') return;
    // Prime the diff baseline once the app can answer itself.
    setTimeout(() => { tick(); }, 2000).unref();
    timer = setInterval(tick, POLL_MS);
    timer.unref();
  });

  app.addHook('onClose', async () => { if (timer) clearInterval(timer); });
}, { name: 'feed-poller', dependencies: ['event-bus'] });
