// buildApp() — Pertal as a factory, so tests can fastify.inject() it without a port.
//
// Data flow, one direction only:
//   sources ──poll──▶ snapshot cache ──change──▶ resource model ──▶ /api/* + SSE
//                                         └──────▶ activity feed
//   buttons ──▶ POST /api/actions/:kind ──▶ job ──steps──▶ SSE "job" + audit trail
//
// No route awaits an upstream. Everything a GET returns is already in memory.
'use strict';
const { EventEmitter } = require('events');
const fastify = require('fastify');
const { createSnapshots } = require('./lib/snapshots');
const { buildResources } = require('./lib/resources');
const { actionsFor } = require('./lib/actions');
const { createJobs } = require('./lib/jobs');
const { createActivity } = require('./lib/activity');
const { registerAgentSources } = require('./sources/agents');
const { registerHldbSource } = require('./sources/hldb');
const { registerProbeSources } = require('./sources/probe');
const { registerLinkSources } = require('./sources/links');
const { registerExtrasSources } = require('./sources/extras');
const { registerStreamSources } = require('./sources/streams');
const { createHistory } = require('./lib/history');

const VERSION = require('./package.json').version;

async function buildApp(opts = {}) {
  const app = fastify({
    logger: opts.logger ?? { level: 'warn' },
    bodyLimit: 5 * 1024 * 1024, // architecture fragments run 30-60 KB; headroom for growth
  });

  // Event bus: the seam between background work and the SSE stream.
  const bus = new EventEmitter();
  bus.setMaxListeners(500);
  app.decorate('events', {
    emit: (name, payload) => bus.emit('*', name, payload),
    on: (fn) => bus.on('*', fn),
    off: (fn) => bus.off('*', fn),
  });

  // Derived state, rebuilt (debounced) whenever any snapshot changes.
  const state = { resources: [], summary: null, built_at: null };
  let rebuildTimer = null;
  const rebuild = () => {
    rebuildTimer = null;
    const { resources, summary } = buildResources(app.snapshots);
    for (const r of resources) r.actions = actionsFor(r, app.snapshots);
    state.resources = resources;
    state.summary = summary;
    state.built_at = new Date().toISOString();
    app.events.emit('resources', { resources, summary, built_at: state.built_at });
  };
  const scheduleRebuild = () => { if (!rebuildTimer) rebuildTimer = setTimeout(rebuild, 150); };

  const activity = createActivity({
    emit: (entry) => app.events.emit('activity', entry),
    log: app.log,
    persist: opts.persist ?? true,
  });
  app.decorate('activity', activity);

  const history = createHistory();
  app.decorate('history', history);

  const snapshots = opts.snapshots ?? createSnapshots({
    onChange: (key, snap) => {
      activity.observe(key, snap);
      if (key.startsWith('vitals:') && snap.meta.ok) history.observe(key.slice(7), snap.data);
      app.events.emit('snapshot', snap.meta);
      scheduleRebuild();
    },
  });
  app.decorate('snapshots', snapshots);
  if (!opts.snapshots) {
    registerAgentSources(snapshots);
    registerProbeSources(snapshots);
    registerLinkSources(snapshots);
    registerExtrasSources(snapshots);
    registerStreamSources(snapshots);
    if (!registerHldbSource(snapshots)) app.log.warn('HOMELAB_DB_URL not set — no collector findings');
  }

  app.decorate('jobs', createJobs(app));
  app.decorate('pertal', {
    version: VERSION,
    state,
    rebuild,
    resource: (id) => state.resources.find((r) => r.id === id) || null,
  });

  await app.register(require('./routes/api'), { prefix: '/api' });
  await app.register(require('./routes/views'), { prefix: '/api' });
  await app.register(require('./routes/streams'), { prefix: '/api/streams' });
  await app.register(require('./routes/events'), { prefix: '/api/events' });
  await app.register(require('./routes/ingest'), { prefix: '/api/architecture' });
  await app.register(require('./plugins/static'));

  app.addHook('onReady', async () => {
    rebuild();
    if (process.env.PERTAL_SOURCES !== 'off' && opts.startSources !== false) snapshots.start();
  });
  app.addHook('onClose', async () => {
    snapshots.stop();
    if (rebuildTimer) clearTimeout(rebuildTimer);
  });

  return app;
}

module.exports = buildApp;
