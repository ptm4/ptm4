// Launchpad reachability: one HTTP request per distinct origin every 2 minutes. Any HTTP
// answer (even 401/403) means "up"; only no answer means down. Self-signed LAN certs are
// expected, so TLS is not verified for these probes (and only these).
'use strict';
const http = require('http');
const https = require('https');
const { LINK_GROUPS } = require('../lib/links');

function probe(origin, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    let url;
    try { url = new URL(origin); } catch (_) { return resolve({ up: false, error: 'bad url' }); }
    const lib = url.protocol === 'https:' ? https : http;
    const req = lib.request(url, { method: 'GET', timeout: timeoutMs, rejectUnauthorized: false }, (res) => {
      res.resume();
      resolve({ up: true, status: res.statusCode, ms: Date.now() - t0 });
    });
    req.on('timeout', () => { req.destroy(); resolve({ up: false, error: `no answer in ${timeoutMs} ms` }); });
    req.on('error', (e) => resolve({ up: false, error: e.code || e.message }));
    req.end();
  });
}

function registerLinkSources(snapshots) {
  const origins = [...new Set(LINK_GROUPS.flatMap((g) => g.links.map((l) => l.check).filter(Boolean)))];
  snapshots.register({
    key: 'links', group: 'links', label: 'launchpad reachability',
    intervalMs: 2 * 60_000, timeoutMs: 8000, staleAfterMs: 10 * 60_000,
    fetch: async () => {
      const results = await Promise.all(origins.map((o) => probe(o)));
      return Object.fromEntries(origins.map((o, i) => [o, results[i]]));
    },
  });
}

module.exports = { registerLinkSources, probe };
