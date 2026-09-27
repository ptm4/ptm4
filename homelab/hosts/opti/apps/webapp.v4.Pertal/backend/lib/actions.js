// The action pipeline — every button in Pertal (and anything an agent or script wants to
// do) goes through POST /api/actions/:kind and becomes a job with declared steps.
//
// Why one pipeline: the v3 audit trail held 19 jobs, all "ok", while buttons were
// failing — the failures never reached the job system at all. Here there is no other
// path, so a failure is always a failed job with a reason, visible in Activity.
//
// Contract:
//   - The HTTP request only validates and starts; it answers 202 {job} immediately.
//     Progress arrives over SSE (event "job") and GET /api/jobs/:id.
//   - Risky kinds refuse with 428 unless the body carries confirm: true — the UI sends
//     that only after the confirm tap.
//   - PERTAL_ACTIONS=dry makes every mutating agent call a no-op that reports what it
//     would have sent (reads, like preflight, stay real). Used for dev and tests.
'use strict';
const { AGENT_HOSTS } = require('./hosts');
const { agentFetch } = require('./agent-client');

const DRY = process.env.PERTAL_ACTIONS === 'dry';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function createActionContext(app) {
  return {
    dry: DRY,
    snapshots: app.snapshots,
    async agent(host, path, opts = {}) {
      const cfg = AGENT_HOSTS[host];
      if (!cfg) throw new Error(`no agent on ${host}`);
      if (DRY && opts.method === 'POST') {
        await sleep(600);
        return { ok: true, status: 200, data: { ok: true, detail: `dry run: would POST ${path} to ${host}` } };
      }
      return agentFetch(`${cfg.agent}${path}`, opts);
    },
  };
}

async function preflight(ctx, host, note) {
  const r = await ctx.agent(host, '/status', { timeoutMs: 4000 });
  if (!r.ok) throw new Error(`agent on ${host} answered HTTP ${r.status}`);
  note(`agent v${r.data?.agent_version ?? '?'} on ${host} is answering`);
}

async function mustPost(ctx, host, path, body, timeoutMs, note, what) {
  let r;
  try {
    r = await ctx.agent(host, path, { method: 'POST', body, timeoutMs });
  } catch (err) {
    throw new Error(`no answer from the agent on ${host} (${err.message}) — ${what} may still be running`);
  }
  if (!r.ok) throw new Error(r.data?.error || `agent refused: HTTP ${r.status}`);
  note(r.data?.detail || r.data?.message || `agent accepted (HTTP ${r.status})`);
  return r.data;
}

async function waitForContainer(ctx, host, name, note, timeoutMs = 60_000) {
  if (ctx.dry) { note('dry run: skipped waiting for the container'); return; }
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const snap = await ctx.snapshots.refresh(`containers:${host}`);
    const c = snap?.data?.containers?.find((x) => x.name === name);
    if (c && c.state === 'running' && c.health !== 'starting' && c.health !== 'unhealthy') {
      note(`${name}: ${c.status}`);
      return;
    }
    await sleep(3000);
  }
  throw new Error(`${name} was not running and healthy within ${timeoutMs / 1000}s — check its Logs tab`);
}

async function waitForAgent(ctx, host, want, timeoutMs, note) {
  if (ctx.dry) { note(`dry run: skipped waiting for ${host} to ${want ? 'return' : 'go down'}`); return; }
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    let alive = false;
    try { alive = (await ctx.agent(host, '/status', { timeoutMs: 3000 })).ok; } catch (_) { alive = false; }
    if (alive === want) {
      note(`${host} ${want ? 'answered again' : 'stopped answering'} after ${Math.round((Date.now() - t0) / 1000)}s`);
      return;
    }
    await sleep(want ? 5000 : 3000);
  }
  throw new Error(want
    ? `${host} did not come back within ${timeoutMs / 60_000} minutes`
    : `${host} was still answering ${timeoutMs / 1000}s after accepting the reboot`);
}

const agentOn = (r) => !!AGENT_HOSTS[r.host];
const autoupdateMode = (r, snaps) => snaps.data(`agent:${r.host}`)?.autoupdate?.mode ?? null;

// kind → definition. `plan` declares the steps up front so the UI shows the whole job
// before it runs; `run` executes them in order.
const ACTIONS = {
  'resource.refresh': {
    label: 'Refresh', icon: 'refresh-cw', risky: false, audit: false,
    applies: (r) => r.sources.length > 0,
    plan: (r) => [{ key: 'refresh', label: `Re-read ${r.sources.length} data source(s) for ${r.name}` }],
    run: async (ctx, job, r) => {
      await job.step('refresh', async (note) => {
        const results = await Promise.all(r.sources.map((k) => ctx.snapshots.refresh(k)));
        const bad = results.filter((x) => x && x.meta.ok === false);
        for (const x of results) note(`${x.meta.label}: ${x.meta.ok ? `ok in ${x.meta.took_ms} ms` : x.meta.error}`);
        if (bad.length) throw new Error(`${bad.length} of ${results.length} source(s) failed`);
      });
    },
  },

  'container.restart': {
    label: 'Restart', icon: 'rotate-ccw', risky: false,
    applies: (r) => r.type === 'container' && agentOn(r),
    plan: (r) => [
      { key: 'preflight', label: `Check the agent on ${r.host} is answering` },
      { key: 'restart', label: `Restart ${r.name}` },
      { key: 'verify', label: `Wait until ${r.name} is running and healthy` },
    ],
    run: async (ctx, job, r) => {
      await job.step('preflight', (note) => preflight(ctx, r.host, note));
      await job.step('restart', (note) => mustPost(ctx, r.host, '/restart', { container: r.name }, 60_000, note, 'the restart'));
      await job.step('verify', (note) => waitForContainer(ctx, r.host, r.name, note));
    },
  },

  'container.update': {
    label: 'Update image', icon: 'download', risky: true,
    applies: (r) => r.type === 'container' && agentOn(r),
    plan: (r) => [
      { key: 'preflight', label: `Check the agent on ${r.host} is answering` },
      { key: 'pull', label: `Pull the newest image and recreate ${r.name}`, detail: 'A cold registry pull can take minutes.' },
      { key: 'verify', label: `Wait until ${r.name} is running and healthy` },
    ],
    run: async (ctx, job, r) => {
      await job.step('preflight', (note) => preflight(ctx, r.host, note));
      await job.step('pull', async (note) => {
        const d = await mustPost(ctx, r.host, '/update', { container: r.name }, 220_000, note, 'the update');
        if (d?.image) note(`image now ${d.image}`);
        if (d?.pulled === false) note('image was already current');
      });
      await job.step('verify', (note) => waitForContainer(ctx, r.host, r.name, note, 120_000));
    },
  },

  'host.sync': {
    label: 'Sync inventory', icon: 'folder-sync', risky: false,
    applies: (r) => r.type === 'host' && agentOn(r),
    plan: (r) => [{ key: 'sync', label: `Ask ${r.name} to re-report its full inventory` }],
    run: async (ctx, job, r) => {
      await job.step('sync', (note) => mustPost(ctx, r.host, '/sync', {}, 60_000, note, 'the sync'));
    },
  },

  'host.updates-hold': {
    label: 'Hold updates', icon: 'pause', risky: false,
    applies: (r, snaps) => r.type === 'host' && agentOn(r) && autoupdateMode(r, snaps) && autoupdateMode(r, snaps) !== 'disabled',
    plan: (r) => [{ key: 'hold', label: `Hold nightly apt updates on ${r.name}` }, { key: 'verify', label: 'Re-read the hold state' }],
    run: async (ctx, job, r, params) => {
      await job.step('hold', (note) => mustPost(ctx, r.host, '/autoupdate',
        { enabled: false, by: 'pertal', reason: params?.reason || null }, 15_000, note, 'the hold'));
      await job.step('verify', async (note) => {
        const s = await ctx.snapshots.refresh(`agent:${r.host}`);
        note(`auto-updates now: ${s?.data?.autoupdate?.mode ?? 'unknown'}`);
      });
    },
  },

  'host.updates-resume': {
    label: 'Resume updates', icon: 'play', risky: false,
    applies: (r, snaps) => r.type === 'host' && agentOn(r) && autoupdateMode(r, snaps) === 'disabled',
    plan: (r) => [{ key: 'resume', label: `Resume nightly apt updates on ${r.name}` }, { key: 'verify', label: 'Re-read the hold state' }],
    run: async (ctx, job, r) => {
      await job.step('resume', (note) => mustPost(ctx, r.host, '/autoupdate', { enabled: true, by: 'pertal' }, 15_000, note, 'the resume'));
      await job.step('verify', async (note) => {
        const s = await ctx.snapshots.refresh(`agent:${r.host}`);
        note(`auto-updates now: ${s?.data?.autoupdate?.mode ?? 'unknown'}`);
      });
    },
  },

  'host.reboot': {
    label: 'Reboot', icon: 'power', risky: true,
    applies: (r) => r.type === 'host' && agentOn(r),
    plan: (r) => [
      { key: 'preflight', label: `Check the agent on ${r.name} is answering` },
      { key: 'send', label: 'Send the reboot request', detail: 'The agent replies before rebooting: accepted, not finished.' },
      { key: 'gone', label: `Wait for ${r.name} to stop answering` },
      { key: 'back', label: `Wait for ${r.name} to answer again` },
      { key: 'verify', label: 'Re-read everything about the host' },
    ],
    run: async (ctx, job, r) => {
      await job.step('preflight', (note) => preflight(ctx, r.host, note));
      await job.step('send', (note) => mustPost(ctx, r.host, '/reboot', { host: r.host }, 15_000, note, 'the reboot'));
      await job.step('gone', (note) => waitForAgent(ctx, r.host, false, 90_000, note));
      await job.step('back', (note) => waitForAgent(ctx, r.host, true, 10 * 60_000, note));
      await job.step('verify', async (note) => {
        await ctx.snapshots.refreshGroup(r.host);
        note('host data re-read');
      });
    },
  },
};

const describe = (kind) => {
  const a = ACTIONS[kind];
  return { kind, label: a.label, icon: a.icon, risky: a.risky };
};

function actionsFor(resource, snapshots) {
  return Object.keys(ACTIONS).filter((k) => ACTIONS[k].applies(resource, snapshots)).map(describe);
}

class ActionError extends Error {
  constructor(statusCode, message) { super(message); this.statusCode = statusCode; }
}

// Validate and start. Returns the job snapshot; the job keeps running after this returns.
function startAction(app, kind, resource, { confirm = false, params = null, actor = 'pertal' } = {}) {
  const def = ACTIONS[kind];
  if (!def) throw new ActionError(404, `unknown action '${kind}'`);
  if (!resource) throw new ActionError(404, 'unknown resource');
  if (!def.applies(resource, app.snapshots)) throw new ActionError(400, `'${def.label}' does not apply to ${resource.name}`);
  if (def.risky && confirm !== true) throw new ActionError(428, `'${def.label}' on ${resource.name} needs confirmation`);

  const job = app.jobs.create({
    kind, title: `${def.label} ${resource.name}`, host: resource.host, target: resource.name,
    resource: resource.id, actor, danger: def.risky, audit: def.audit !== false, steps: def.plan(resource),
  });
  const ctx = createActionContext(app);
  (async () => {
    try {
      await def.run(ctx, job, resource, params);
      job.finish('ok');
    } catch (err) {
      job.finish('failed', err);
    }
  })();
  return job.snapshot();
}

module.exports = { ACTIONS, actionsFor, startAction, ActionError, describe };
