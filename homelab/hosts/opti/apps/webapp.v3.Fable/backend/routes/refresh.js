// POST /api/refresh — re-collect the fleet's data on demand, as a stepped job.
//
// WHY THIS EXISTS. Almost everything on this dashboard is derived from collector
// reports written on a schedule (the doctor every 30 min, the rest daily). That is
// fine for watching, and wrong for acting: Peter upgraded rpi's packages by hand,
// the tile kept saying "14 pkg · 14 sec" because the number came from a report
// written before the upgrade, and there was no button anywhere that meant "go and
// look again". "Force Sync" did not do it either — that asks a host's agent to push
// its container/arch fragments, which is a different and much smaller thing.
//
// So this is the missing verb. It triggers the real collectors through the opti
// dispatcher, waits for each one's report to actually advance, and then re-ingests
// into homelab-db so the Docs/Database views agree with the tiles.
//
// WHAT IT IS NOT: it does not make the dashboard "live" in the streaming sense.
// Vitals already stream over SSE; container state already refreshes on its own poll.
// This is for the derived, expensive, SSH-fan-out data that genuinely cannot be
// recomputed on every page load — the honest fix for that is a fast way to ask for
// it, plus a timestamp saying how old it is, not a pretence that it is instant.
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('../lib/paths');
const { dispatch } = require('../lib/controls');

// agent name (dispatcher key) -> the report file it writes when it finishes.
// Waiting on the FILE rather than on the dispatcher is deliberate: the dispatcher
// answers 202 the moment it forks, so its response says "started", never "done".
// The report's own run_at advancing is the only evidence the work actually landed.
const COLLECTORS = [
  { agent: 'homelab-doctor',    report: 'homelab-doctor-latest', label: 'health across all hosts' },
  { agent: 'software-inventory', report: 'software-latest',       label: 'package + image updates' },
  { agent: 'hardware-report',   report: 'hardware-latest',        label: 'disks, SMART, sensors' },
  { agent: 'network-report',    report: 'network-latest',         label: 'interfaces, ports, DNS' },
];

const WAIT_MS = 180_000;   // an SSH fan-out over four hosts is genuinely slow
const POLL_MS = 3_000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function runAt(report) {
  try {
    const raw = fs.readFileSync(path.join(AGENT_LOGS_DIR, `${report}.json`), 'utf8');
    return JSON.parse(raw).run_at || null;
  } catch (_) {
    return null;   // never collected, or mid-write — both mean "no newer result yet"
  }
}

module.exports = async function refreshRoutes(app) {
  app.post('/', async (req, reply) => {
    // Let a caller refresh one collector instead of all four — the Updates tab only
    // cares about software-inventory, and making it wait on a SMART sweep would be
    // the kind of slowness that stops people using the button at all.
    const only = typeof req.body?.only === 'string' ? req.body.only : null;
    const wanted = only ? COLLECTORS.filter((c) => c.agent === only) : COLLECTORS;
    if (!wanted.length) {
      return reply.code(400).send({ error: `unknown collector '${only}'`,
        known: COLLECTORS.map((c) => c.agent) });
    }

    const job = app.jobs.create({
      kind: 'refresh', title: only ? `Refresh ${only}` : 'Refresh all fleet data',
      host: null, target: only || 'fleet', danger: false,
      steps: [
        ...wanted.map((c) => ({
          key: c.agent,
          label: `Re-collect ${c.label}`,
          detail: 'Runs on opti and fans out over SSH — a minute or two is normal.',
        })),
        { key: 'ingest', label: 'Fold the new reports into homelab-db' },
      ],
    });

    // Detached: the whole point is that the browser stops waiting and watches the
    // steps instead. Same shape as reboot/apt-upgrade.
    (async () => {
      let anyFailed = false;
      for (const c of wanted) {
        const before = runAt(c.report);
        try {
          await job.step(c.agent, async (note) => {
            const r = await dispatch('POST', `/agents/${encodeURIComponent(c.agent)}/run`);
            if (r.status >= 400) {
              throw new Error(r.data?.error || `dispatcher refused: HTTP ${r.status}`);
            }
            note('started; waiting for the report to land');
            const t0 = Date.now();
            while (Date.now() - t0 < WAIT_MS) {
              await sleep(POLL_MS);
              const now = runAt(c.report);
              if (now && now !== before) {
                note(`report updated after ${Math.round((Date.now() - t0) / 1000)}s`);
                return;
              }
            }
            throw new Error(`${c.agent} did not produce a new report within ${WAIT_MS / 1000}s`);
          });
        } catch (_) {
          // One collector failing must not abort the rest — they are independent, and
          // three fresh reports plus one honest failure beats four stale ones.
          anyFailed = true;
        }
      }

      try {
        await job.step('ingest', async (note) => {
          const r = await dispatch('POST', '/agents/homelab-db-ingest/run');
          if (r.status >= 400) {
            // The ingest timer runs every 30 min regardless, so this is a nicety, not
            // a failure worth reddening the job over. Say so rather than throwing.
            note(`could not trigger ingest now (${r.data?.error || `HTTP ${r.status}`}) — `
                 + 'the scheduled ingest will pick these up within 30 minutes');
            return;
          }
          note('homelab-db is re-reading the new reports');
        });
      } catch (_) { /* handled above */ }

      job.finish(anyFailed ? 'failed' : 'ok',
        anyFailed ? new Error('one or more collectors did not refresh — see the steps') : null);
    })();

    return reply.code(202).send({ job: job.snapshot() });
  });
};
