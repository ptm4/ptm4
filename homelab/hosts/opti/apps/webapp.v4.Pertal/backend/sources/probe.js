// Reachability probes for hosts with no agent (android): a TCP connect to one port.
// "Unreachable" is data, not a failed snapshot — the probe itself worked.
'use strict';
const net = require('net');
const { HOSTS } = require('../lib/hosts');

function tcpProbe(ip, port, timeoutMs) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const sock = net.connect({ host: ip, port });
    const done = (reachable, error) => {
      sock.destroy();
      resolve({ reachable, rtt_ms: reachable ? Date.now() - t0 : null, error: error ?? null });
    };
    sock.setTimeout(timeoutMs, () => done(false, `no answer on :${port} within ${timeoutMs} ms`));
    sock.once('connect', () => done(true));
    sock.once('error', (e) => done(false, e.code || e.message));
  });
}

function registerProbeSources(snapshots) {
  for (const host of HOSTS.filter((h) => h.probe)) {
    snapshots.register({
      key: `probe:${host.id}`, group: host.id, label: `${host.label} reachability`,
      intervalMs: 60_000, timeoutMs: 4000,
      fetch: () => tcpProbe(host.ip, host.probe.port, 2500),
    });
  }
}

module.exports = { registerProbeSources, tcpProbe };
