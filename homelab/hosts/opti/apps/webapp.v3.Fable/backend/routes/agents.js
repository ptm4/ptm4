// /api/agents: per-host architecture agents (hl-arch-agent.py), installed and running
// on opti/rpi/noblenumbat (lib/hosts.js is the host list's single source of truth).
//
// This route is a thin proxy: it asks each host's agent directly for /status, and
// POSTs to its /sync for Force Sync, rather than routing through the opti dispatcher
// (that's a different control plane — see agent-dispatcher.py — for a different kind
// of thing, the runners). A stale or unreachable agent is reported as exactly that,
// never silently treated as healthy.
//
// AUTH POSTURE (deliberate, reviewed 2026-07-26 — see webapp/BUGS.md B3): every write
// on this dashboard trusts the LAN. The agent-side bearer token protects the AGENTS
// from arbitrary LAN callers; the webapp is the intended caller. If the dashboard ever
// becomes reachable beyond the LAN, gate the POST routes at nginx first.
const { AGENT_HOSTS } = require('../lib/hosts');
const { buildMergedData } = require('../lib/arch-data');
const { agentFetch } = require('../lib/agent-client');

const STATUS_TIMEOUT_MS = 4000;
const SYNC_TIMEOUT_MS = 20000;   // a real collection + push, not just a status read

function driftCountsByHost() {
  try {
    const merged = buildMergedData();
    const counts = {};
    for (const d of merged.live_merge?.drift?.undescribed || []) {
      counts[d.host] = (counts[d.host] || 0) + 1;
    }
    for (const d of merged.live_merge?.drift?.missing || []) {
      counts[d.host] = (counts[d.host] || 0) + 1;
    }
    return counts;
  } catch (_) {
    return {};
  }
}

// ── Stepped actions ──────────────────────────────────────────────────────────
// Every destructive action below runs as a JOB (lib/jobs.js): the steps are declared
// before anything happens, each one reports as it starts and finishes, and the whole
// thing is appended to a permanent audit file when it ends.
//
// The steps are not decoration. They exist because "it failed" was never the useful
// sentence — "the agent answered, accepted the request, and then the host never came
// back" is. Each step below is a distinct thing that can go wrong on its own, and
// naming them is what turns one opaque failure into a diagnosis.
//
// Shape of every handler: reply with the job snapshot alongside the normal payload,
// so existing callers keep working and new ones can follow along.

// Ask an agent for /status. Used as the preflight step: it proves the box is up, the
// agent is running, and the token is accepted, BEFORE anything irreversible is sent.
async function preflight(cfg, host, note) {
  const r = await agentFetch(`${cfg.base}/status`, { timeoutMs: STATUS_TIMEOUT_MS });
  if (!r.ok) throw new Error(`agent on ${host} answered HTTP ${r.status} — not safe to proceed`);
  const v = r.data?.version ? ` v${r.data.version}` : '';
  note(`agent on ${host}${v} reachable at ${cfg.base}`);
  return r.data;
}

// Turn a thrown error into the sentence that is actually true.
//
// Three cases, and conflating them is exactly the low-feedback problem this work is
// fixing. A timeout means we do not know what happened. A transport failure means we
// never reached the box. Anything else is the agent having told us something specific
// — "unit not in allowlist", "container not found" — and that message is the most
// valuable one we have, so it is passed through untouched rather than being buried
// under a generic "unreachable".
function actionErr(host, e, timeoutTail) {
  const msg = e?.message || String(e);
  if (/abort|timeout|timed out/i.test(msg)) {
    return `agent on ${host} did not respond in time${timeoutTail ? ` (${timeoutTail})` : ''}`;
  }
  if (/fetch failed|ECONNREFUSED|EHOSTUNREACH|ENOTFOUND|ECONNRESET|network/i.test(msg)) {
    return `agent on ${host} unreachable: ${msg}`;
  }
  return msg;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Force the host's agent to re-collect and push its state to the webapp.
//
// This is the verification step for anything that changes containers or units, and it
// is the ONLY honest one available: the agent exposes /status, /vitals, /apt-status and
// /sync, and none of the first three carry container or unit state (checked against a
// live agent on 2026-09-10). Earlier drafts of this file had a "confirm" step that read
// `status.containers` — a field that does not exist — so it could only ever report
// "could not check", which is worse than not having the step at all.
//
// /sync does two useful things at once: it returns the count the agent can actually see
// right now, and it refreshes what the dashboard will display, so the page you are
// looking at stops lagging the action you just took.
async function resync(cfg, host, note) {
  const r = await agentFetch(`${cfg.base}/sync`, { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
  if (!r.ok || r.data?.ok === false) {
    throw new Error(r.data?.error || `agent on ${host} could not re-report its state (HTTP ${r.status})`);
  }
  const n = r.data?.containers;
  note(typeof n === 'number'
    ? `${host} now reports ${n} container(s); the dashboard is up to date`
    : `${host} re-reported its state; the dashboard is up to date`);
  return r.data;
}

module.exports = async function agentsRoutes(app) {
  // GET /api/agents — one entry per configured host, with a live /status read.
  // Never lets one unreachable agent break the list — an unreachable host is a row
  // that says so, not a 500 for the whole page.
  app.get('/', async () => {
    const drift = driftCountsByHost();
    const hosts = await Promise.all(Object.entries(AGENT_HOSTS).map(async ([id, cfg]) => {
      try {
        const r = await agentFetch(`${cfg.base}/status`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return {
          id, label: cfg.label, reachable: true,
          last_run: r.data.last_run || null,
          next_scheduled: r.data.next_scheduled || null,
          agent_version: r.data.agent_version || null,
          drift_count: drift[id] || 0,
          // v0.4.0 control capabilities; null/[] on an older agent, which is exactly
          // how the cockpit detects "needs v0.4.0" and disables its buttons.
          allowed_units: r.data.allowed_units || null,
          wake_targets: r.data.wake_targets || [],
        };
      } catch (e) {
        return {
          id, label: cfg.label, reachable: false, error: e.message,
          last_run: null, next_scheduled: null, agent_version: null,
          drift_count: drift[id] || 0,
        };
      }
    }));
    return { hosts, checked_at: new Date().toISOString() };
  });

  // POST /api/agents/:host/sync — Force Sync for one host. Blocks until the agent
  // actually finishes (its own /sync is synchronous) and returns the real result.
  app.post('/:host/sync', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });

    try {
      const r = await agentFetch(`${cfg.base}/sync`, { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
      reply.code(r.ok ? 200 : 502).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({ host: req.params.host, ok: false, error: e.message });
    }
  });

  // POST /api/agents/sync-all — same, fanned out to every configured host in parallel.
  // Partial failure is expected and reported per-host, not surfaced as one opaque error.
  app.post('/sync-all', async () => {
    const results = await Promise.all(Object.keys(AGENT_HOSTS).map(async (host) => {
      try {
        const r = await agentFetch(`${AGENT_HOSTS[host].base}/sync`,
          { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
        return { host, ...r.data, ok: r.ok };
      } catch (e) {
        return { host, ok: false, error: e.message };
      }
    }));
    return { results, checked_at: new Date().toISOString() };
  });

  // POST /api/agents/:host/restart-container — restart one container on that host via
  // its agent's /restart (agent v0.2.0+). The agent validates the name against its own
  // `docker ps -a` and requires a bearer token, so this proxy stays thin.
  // Timeout is generous: a real `docker restart` on a heavy container takes ~10-15s and
  // the agent blocks until it finishes, but stays well inside the 240s read timeout the
  // /api/agents location gets in nginx-wg.conf.
  app.post('/:host/restart-container', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const container = req.body?.container;
    if (typeof container !== 'string' || !container.trim()) {
      return reply.code(400).send({ error: 'body.container is required' });
    }

    const host = req.params.host;
    const name = container.trim();
    try {
      const { job, result } = await app.jobs.run({
        kind: 'restart-container', title: `Restart ${name} on ${host}`,
        host, target: name, danger: true,
        steps: [
          { key: 'preflight', label: `Check the agent on ${host} is answering` },
          { key: 'restart', label: `Ask it to restart ${name}` },
          { key: 'resync', label: 'Re-read the fleet so this page reflects it' },
        ],
      }, async (job) => {
        await job.step('preflight', (note) => preflight(cfg, host, note));
        const r = await job.step('restart', async (note) => {
          const res = await agentFetch(`${cfg.base}/restart`, {
            method: 'POST', timeoutMs: 55000, body: { container: name },
          });
          if (!res.ok) throw new Error(res.data?.error || `agent refused: HTTP ${res.status}`);
          note(res.data?.detail || res.data?.message || `agent reported success (HTTP ${res.status})`);
          return res;
        });
        // The agent blocks until `docker restart` returns, so success above already
        // means docker came back clean. What is left is making the dashboard agree.
        await job.step('resync', (note) => resync(cfg, host, note));
        return r.data;
      });
      reply.send({ host, ...result, job });
    } catch (e) {
      // Distinguish "the agent never answered" from "the agent said no" — the frontend
      // maps these to different toasts.
      reply.code(e.statusCode || 502).send({
        host, ok: false, job: e.job ?? null,
        error: actionErr(host, e, 'restart may still be running'),
      });
    }
  });

  // POST /api/agents/:host/update-container — pull the newest image for one container's
  // compose service and recreate just that service, via the agent's /update (v0.3.0+).
  // The timeout is the big difference: a registry pull on the Pi can genuinely run for
  // minutes, so this sits under nginx's 240s /api/agents read timeout and above the
  // agent's own worst case (140s pull + 45s recreate).
  const UPDATE_TIMEOUT_MS = 220000;
  app.post('/:host/update-container', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const container = req.body?.container;
    if (typeof container !== 'string' || !container.trim()) {
      return reply.code(400).send({ error: 'body.container is required' });
    }

    const host = req.params.host;
    const name = container.trim();
    try {
      const { job, result } = await app.jobs.run({
        kind: 'update-container', title: `Update ${name} on ${host}`,
        host, target: name, danger: true,
        steps: [
          { key: 'preflight', label: `Check the agent on ${host} is answering` },
          { key: 'pull', label: `Pull the newest image and recreate ${name}`,
            detail: 'A cold registry pull can genuinely take minutes — this step is the long one.' },
          { key: 'resync', label: 'Re-read the fleet so this page reflects it' },
        ],
      }, async (job) => {
        await job.step('preflight', (note) => preflight(cfg, host, note));
        const r = await job.step('pull', async (note) => {
          const res = await agentFetch(`${cfg.base}/update`, {
            method: 'POST', timeoutMs: UPDATE_TIMEOUT_MS, body: { container: name },
          });
          if (!res.ok) throw new Error(res.data?.error || `agent refused the update: HTTP ${res.status}`);
          if (res.data?.image) note(`image now ${res.data.image}`);
          if (res.data?.pulled === false) note('image was already current — nothing to pull');
          note(res.data?.detail || `agent reported success (HTTP ${res.status})`);
          return res;
        });
        await job.step('resync', (note) => resync(cfg, host, note));
        return r.data;
      });
      reply.send({ host, ...result, job });
    } catch (e) {
      reply.code(e.statusCode || 502).send({
        host, ok: false, job: e.job ?? null,
        error: actionErr(host, e, 'the update may still be running — check the containers panel in a minute'),
      });
    }
  });

  // ── Cockpit host controls (agent v0.4.0) ─────────────────────────────────────

  // POST /api/agents/:host/reboot — reboot the host. The body echoes the host name so
  // the agent can refuse a proxy/route mixup (its own HOST must match). The agent
  // responds BEFORE rebooting (~2s grace), so even an rpi reboot returns a real 200.
  //
  // Reboot is the one action where the HTTP request and the job deliberately have
  // different lifetimes. The request must return in seconds — holding it open for the
  // three minutes a reboot takes would trip every timeout between here and the browser,
  // and if the rebooting host is the one serving this page, the connection is going to
  // drop anyway. So the request covers the part that can still be refused (preflight,
  // send), and the *watching* continues in the background, streaming step transitions
  // over SSE to whoever is looking.
  //
  // This is the case that most needed stepping. "Reboot failed" used to be one toast
  // covering four completely different situations. Now they are four named steps, and
  // the interesting one — the box accepted the reboot and never came back — is
  // impossible to confuse with the box having refused.
  const REBOOT_GONE_MS = 90_000;      // how long we wait for it to actually go down
  const REBOOT_RETURN_MS = 10 * 60_000; // and then to come back
  app.post('/:host/reboot', async (req, reply) => {
    const host = req.params.host;
    const cfg = AGENT_HOSTS[host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${host}'` });

    const job = app.jobs.create({
      kind: 'reboot', title: `Reboot ${host}`, host, target: host, danger: true,
      steps: [
        { key: 'preflight', label: `Check the agent on ${host} is answering` },
        { key: 'send', label: 'Send the reboot request',
          detail: 'The agent replies before it reboots, so a 200 here means accepted, not finished.' },
        { key: 'gone', label: `Wait for ${host} to stop answering`,
          detail: 'Confirms the reboot actually began rather than being silently ignored.' },
        { key: 'back', label: `Wait for ${host} to answer again` },
        { key: 'verify', label: 'Confirm the agent is healthy after boot' },
      ],
    });

    // Phase 1 — synchronous, because it can still fail in a way worth reporting now.
    let accepted;
    try {
      await job.step('preflight', (note) => preflight(cfg, host, note));
      accepted = await job.step('send', async (note) => {
        const r = await agentFetch(`${cfg.base}/reboot`, {
          method: 'POST', timeoutMs: 15000, body: { host },
        });
        if (!r.ok) throw new Error(r.data?.error || `agent refused the reboot: HTTP ${r.status}`);
        note(r.data?.detail || 'agent accepted the reboot and is going down');
        return r.data;
      });
    } catch (e) {
      job.finish('failed', e);
      return reply.code(502).send({
        host, ok: false, job: job.snapshot(), error: actionErr(host, e),
      });
    }

    // Phase 2 — detached. Nothing awaits this; it reports by emitting on the bus and
    // by the audit line it writes when it settles.
    (async () => {
      const alive = async () => {
        try {
          const r = await agentFetch(`${cfg.base}/status`, { timeoutMs: 3000 });
          return r.ok;
        } catch (_) { return false; }
      };
      try {
        await job.step('gone', async (note) => {
          const t0 = Date.now();
          while (Date.now() - t0 < REBOOT_GONE_MS) {
            if (!(await alive())) { note(`stopped answering after ${Math.round((Date.now() - t0) / 1000)}s`); return; }
            await sleep(3000);
          }
          // Not a failure of the reboot as such — but it IS the signal that something
          // is off, and saying so beats quietly moving on.
          throw new Error(`${host} was still answering ${REBOOT_GONE_MS / 1000}s after accepting the reboot`);
        });
        await job.step('back', async (note) => {
          const t0 = Date.now();
          while (Date.now() - t0 < REBOOT_RETURN_MS) {
            await sleep(5000);
            if (await alive()) { note(`back after ${Math.round((Date.now() - t0) / 1000)}s`); return; }
          }
          throw new Error(`${host} did not come back within ${REBOOT_RETURN_MS / 60000} minutes`);
        });
        await job.step('verify', async (note) => {
          await preflight(cfg, host, note);
          await resync(cfg, host, note);
        });
        job.finish('ok');
      } catch (err) {
        job.finish('failed', err);
      }
    })();

    // 202: accepted and in progress, which is the honest status code for this.
    return reply.code(202).send({ host, ...accepted, job: job.snapshot() });
  });

  // POST /api/agents/:host/apt-upgrade — kick the nightly homelab-autoupdate unit now.
  // Fast by design: the agent starts the unit and returns; progress is polled via
  // GET /:host/apt-status below, so no long request is ever held open.
  //
  // Same split as reboot: the unit is *started* synchronously, then followed in the
  // background until systemd says it finished. Previously this returned "started" and
  // that was the last you heard of it — you had to remember to go and poll apt-status
  // yourself, which nobody does. Now the job reports how it ended, and whether the box
  // now wants a reboot.
  const APT_WATCH_MS = 30 * 60_000;
  app.post('/:host/apt-upgrade', async (req, reply) => {
    const host = req.params.host;
    const cfg = AGENT_HOSTS[host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${host}'` });

    const job = app.jobs.create({
      kind: 'apt-upgrade', title: `Package upgrade on ${host}`, host, target: host, danger: true,
      steps: [
        { key: 'preflight', label: `Check the agent on ${host} is answering` },
        { key: 'start', label: 'Start the homelab-autoupdate unit' },
        { key: 'watch', label: 'Follow the upgrade until systemd reports it finished',
          detail: 'Polls the unit state; the log tail is on the Updates tab throughout.' },
        { key: 'reboot-check', label: 'Report whether a reboot is now required' },
      ],
    });

    let started;
    try {
      await job.step('preflight', (note) => preflight(cfg, host, note));
      started = await job.step('start', async (note) => {
        const r = await agentFetch(`${cfg.base}/apt-upgrade`, { method: 'POST', timeoutMs: 10000 });
        if (!r.ok) throw new Error(r.data?.error || `agent refused: HTTP ${r.status}`);
        note(r.data?.detail || 'homelab-autoupdate.service started');
        return r.data;
      });
    } catch (e) {
      job.finish('failed', e);
      return reply.code(502).send({ host, ok: false, job: job.snapshot(), error: actionErr(host, e) });
    }

    (async () => {
      try {
        const final = await job.step('watch', async (note) => {
          const t0 = Date.now();
          let last = '';
          while (Date.now() - t0 < APT_WATCH_MS) {
            await sleep(10_000);
            let st;
            try { st = await agentFetch(`${cfg.base}/apt-status`, { timeoutMs: 8000 }); }
            catch (_) { continue; }   // a blip mid-upgrade is not a verdict
            const state = st.data?.active || st.data?.state || '';
            if (state && state !== last) { note(`unit is ${state}`); last = state; }
            if (state && !/activating|active \(running\)|running/i.test(state)) {
              if (/fail/i.test(state)) throw new Error(`homelab-autoupdate ended ${state}`);
              note(`finished after ${Math.round((Date.now() - t0) / 1000)}s`);
              return st.data;
            }
          }
          throw new Error(`upgrade still running after ${APT_WATCH_MS / 60000} minutes — following stopped, the unit was left alone`);
        });
        await job.step('reboot-check', async (note) => {
          note(final?.reboot_required
            ? `${host} needs a reboot to finish applying these packages`
            : 'no reboot required');
        });
        job.finish('ok');
      } catch (err) {
        job.finish('failed', err);
      }
    })();

    return reply.code(202).send({ host, ...started, job: job.snapshot() });
  });

  // GET /api/agents/:host/apt-status — unit state + log tail + reboot-required flag.
  app.get('/:host/apt-status', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    try {
      const r = await agentFetch(`${cfg.base}/apt-status`, { timeoutMs: 8000 });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // POST /api/agents/:host/restart-service — restart one allowlisted systemd unit.
  // Timeout ladder must nest: agent restart cap 120s < this 160s < nginx 240s (the
  // slow case is docker.service on opti, which restarts every container it runs).
  app.post('/:host/restart-service', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const unit = req.body?.unit;
    if (typeof unit !== 'string' || !unit.trim()) {
      return reply.code(400).send({ error: 'body.unit is required' });
    }
    const host = req.params.host;
    const name = unit.trim();
    try {
      const { job, result } = await app.jobs.run({
        kind: 'restart-service', title: `Restart ${name} on ${host}`,
        host, target: name, danger: true,
        steps: [
          { key: 'preflight', label: `Check the agent on ${host} is answering` },
          { key: 'restart', label: `Ask systemd to restart ${name}`,
            detail: 'The agent enforces its own unit allowlist; a refusal here is that list, not a failure.' },
          { key: 'resync', label: 'Re-read the fleet so this page reflects it' },
        ],
      }, async (job) => {
        await job.step('preflight', (note) => preflight(cfg, host, note));
        const r = await job.step('restart', async (note) => {
          const res = await agentFetch(`${cfg.base}/service-restart`, {
            method: 'POST', timeoutMs: 160000, body: { unit: name },
          });
          if (!res.ok) throw new Error(res.data?.error || `agent refused: HTTP ${res.status}`);
          note(res.data?.detail || res.data?.state || `agent reported success (HTTP ${res.status})`);
          return res;
        });
        await job.step('resync', (note) => resync(cfg, host, note));
        return r.data;
      });
      reply.send({ host, ...result, job });
    } catch (e) {
      reply.code(e.statusCode || 502).send({
        host, ok: false, job: e.job ?? null,
        error: actionErr(host, e, 'the restart may still be running'),
      });
    }
  });

  // POST /api/agents/:host/wake — Wake-on-LAN. The one deliberate exception to the
  // thin-proxy rule: the target host is OFF, so a healthy PEER agent broadcasts the
  // magic packet on its behalf. (The webapp container itself sits behind docker
  // bridge NAT, where a UDP broadcast would not reliably reach the LAN.)
  const WAKE_TARGETS = ['opti']; // hosts with WoL-armed NICs; mirrors the agents' WAKE_MACS
  app.post('/:host/wake', async (req, reply) => {
    const host = req.params.host;
    if (!WAKE_TARGETS.includes(host)) {
      return reply.code(404).send({ error: `'${host}' is not a wake target (no WoL-capable NIC)` });
    }
    const senders = Object.keys(AGENT_HOSTS).filter((h) => h !== host);
    const failures = [];
    for (const sender of senders) {
      try {
        const r = await agentFetch(`${AGENT_HOSTS[sender].base}/wake`, {
          method: 'POST', timeoutMs: 5000, body: { target: host },
        });
        // Spread first: the agent's own `host` field is the SENDER — the response's
        // host must stay the wake TARGET.
        if (r.ok) return { ...r.data, host, sent_by: sender };
        failures.push(`${sender}: HTTP ${r.status}`);
      } catch (e) {
        failures.push(`${sender}: ${e.message}`);
      }
    }
    reply.code(502).send({
      host, ok: false,
      error: `no reachable agent to send the wake packet (${failures.join('; ')})`,
    });
  });
};
