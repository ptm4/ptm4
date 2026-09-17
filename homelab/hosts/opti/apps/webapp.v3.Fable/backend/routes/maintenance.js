// /api/maintenance — host-level on/off switches that back Settings → Maintenance.
//
// First switch: nightly unattended apt (homelab-autoupdate). Added 2026-09-17 after a
// 02:03 docker-ce upgrade restarted dockerd on opti and took the whole app tier down
// with it — the "random webapp.lan blips". Holding updates per host is the lever.
//
// The source of truth is ON THE HOST, not here: the agent's hold flag
// (/etc/homelab/autoupdate.disabled) plus the timer state, re-read on every GET. This
// route keeps no desired-state copy that could disagree with reality. Every change is
// a job, so it is stepped, streamed over SSE, and appended to the permanent audit
// trail — and its last step re-reads the host independently, so "disabled" in the
// audit log means the host was *observed* disabled, not that a request returned 200.
const { AGENT_HOSTS } = require('../lib/hosts');
const { agentFetch } = require('../lib/agent-client');

const READ_TIMEOUT_MS = 6000;
const APPLY_TIMEOUT_MS = 45000;   // systemctl enable/disable --now, well under nginx's 60s

// Constant shape whether or not the agent answered — the smoke gate compares keys.
function row(host, state, error) {
  return {
    host,
    reachable: !error,
    error: error || null,
    supported: !error && !!state && typeof state.mode === 'string',
    mode: state?.mode ?? null,
    guaranteed: state?.guaranteed ?? null,
    will_run_unattended: state?.will_run_unattended ?? null,
    installed: state?.installed ?? null,
    script_honors_flag: state?.script_honors_flag ?? null,
    flag: state?.flag ?? null,
    timer: state?.timer ?? null,
    last_run: state?.last_run ?? null,
    problems: state?.problems ?? [],
    checked_at: state?.checked_at ?? new Date().toISOString(),
  };
}

async function readHost(host) {
  const cfg = AGENT_HOSTS[host];
  try {
    const r = await agentFetch(`${cfg.base}/autoupdate`, { timeoutMs: READ_TIMEOUT_MS });
    if (r.status === 404) {
      return row(host, null, `agent on ${host} predates auto-update control (needs hl-arch-agent v0.6.0)`);
    }
    if (!r.ok) return row(host, null, `agent on ${host} answered HTTP ${r.status}`);
    return row(host, r.data, null);
  } catch (e) {
    return row(host, null, `agent on ${host} unreachable: ${e.message}`);
  }
}

module.exports = async function maintenanceRoutes(app) {
  // GET /api/maintenance/autoupdate — live state for every agent host.
  app.get('/autoupdate', async () => {
    const hosts = await Promise.all(Object.keys(AGENT_HOSTS).map(readHost));
    return {
      hosts,
      summary: {
        total: hosts.length,
        enabled: hosts.filter((h) => h.mode === 'enabled').length,
        disabled: hosts.filter((h) => h.mode === 'disabled').length,
        unknown: hosts.filter((h) => !h.supported).length,
      },
      checked_at: new Date().toISOString(),
    };
  });

  // POST /api/maintenance/autoupdate/:host  { enabled: boolean, reason?: string }
  app.post('/autoupdate/:host', async (req, reply) => {
    const host = req.params.host;
    const cfg = AGENT_HOSTS[host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${host}'` });
    const enabled = req.body?.enabled;
    if (typeof enabled !== 'boolean') {
      return reply.code(400).send({ error: 'body.enabled must be true or false' });
    }
    const reason = typeof req.body?.reason === 'string' ? req.body.reason.trim().slice(0, 300) : '';
    const verb = enabled ? 'Enable' : 'Disable';
    const want = enabled ? 'enabled' : 'disabled';

    try {
      const { job, result } = await app.jobs.run({
        kind: 'autoupdate',
        title: `${verb} auto-updates on ${host}`,
        host, target: want, danger: false,
        steps: [
          { key: 'preflight', label: `Check the agent on ${host} supports auto-update control` },
          { key: 'apply', label: enabled
              ? 'Remove the hold flag and re-enable the 02:00 timer'
              : 'Write the hold flag and disable the 02:00 timer',
            detail: enabled ? null : 'The flag is what holds: the script skips itself even if a deploy re-enables the timer.' },
          { key: 'verify', label: `Re-read ${host} and confirm updates are ${want}`,
            detail: 'An independent read after the change. This step failing means the audit line is not trustworthy as "done".' },
        ],
      }, async (job) => {
        await job.step('preflight', async (note) => {
          const r = await readHost(host);
          if (!r.supported) throw new Error(r.error || `agent on ${host} did not report auto-update state`);
          note(`currently ${r.mode}${r.guaranteed ? ' (guaranteed)' : ''}${r.flag?.by ? ` · held by ${r.flag.by}` : ''}`);
          if (!enabled && !r.script_honors_flag) {
            throw new Error(`homelab-autoupdate.sh on ${host} predates the hold check — deploy it before disabling, or the hold would not hold`);
          }
        });
        const applied = await job.step('apply', async (note) => {
          const r = await agentFetch(`${cfg.base}/autoupdate`, {
            method: 'POST', timeoutMs: APPLY_TIMEOUT_MS,
            body: { enabled, by: 'webapp · settings', reason: reason || null },
          });
          if (!r.ok) throw new Error(r.data?.error || `agent refused: HTTP ${r.status}`);
          if (r.data?.note) note(r.data.note);
          if (reason) note(`reason: ${reason}`);
          note(`agent applied the change (timer now ${r.data?.state?.timer?.unit_file_state ?? '?'})`);
          return r.data;
        });
        const verified = await job.step('verify', async (note) => {
          const r = await readHost(host);
          if (!r.supported) throw new Error(`could not re-read ${host}: ${r.error}`);
          if (r.mode !== want) {
            throw new Error(`${host} reports auto-updates ${r.mode} after the change — expected ${want}`);
          }
          if (!enabled && !r.guaranteed) {
            throw new Error(`${host} is off but NOT guaranteed: ${r.problems.join('; ') || 'hold flag not honored'}`);
          }
          for (const p of r.problems) note(`note: ${p}`);
          note(enabled
            ? `verified: ${host} will run unattended updates (next ${r.timer?.next_run || 'unknown'})`
            : `verified: ${host} will not auto-update — hold flag present and honored by the script`);
          return r;
        });
        return { applied: applied?.ok ?? true, state: verified };
      });
      reply.send({ host, ok: true, ...result, job });
    } catch (e) {
      reply.code(e.statusCode || 502).send({ host, ok: false, job: e.job ?? null, error: e.message });
    }
  });
};
