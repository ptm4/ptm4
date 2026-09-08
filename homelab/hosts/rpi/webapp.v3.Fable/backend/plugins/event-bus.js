// In-process event bus — the seam between the pollers (which already know when
// something changed) and the SSE route (which tells browsers). Nothing else about
// the backend changes: every route still answers the same JSON it always did; the
// bus only lets a browser learn about a change without asking.
//
// Events (name → payload):
//   vitals         the /api/vitals rollup, after every poll cycle (~30s)
//   containers     the /api/containers document, when any container's up/update state changed
//   activity       { events: [...] } — only the activity rows that are new since the last diff
//   notifications  { unacked, total } when either count changed
//   incidents      { open, muted } when the incident rollup changed (Phase 7)
const { EventEmitter } = require('events');
const fp = require('fastify-plugin');

module.exports = fp(async function eventBus(app) {
  const bus = new EventEmitter();
  bus.setMaxListeners(200);   // one listener set per open SSE client
  const last = {};            // event name → { at: ISO, seq }
  let seq = 0;

  function emit(name, payload) {
    seq += 1;
    last[name] = { at: new Date().toISOString(), seq };
    bus.emit(name, payload, seq);
    bus.emit('*', name, payload, seq);
  }

  app.decorate('events', {
    emit,
    on: (name, fn) => bus.on(name, fn),
    off: (name, fn) => bus.off(name, fn),
    last: () => ({ ...last }),
    seq: () => seq,
  });
}, { name: 'event-bus' });
