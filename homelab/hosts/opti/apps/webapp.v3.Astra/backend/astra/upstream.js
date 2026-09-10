const http = require('node:http');
const https = require('node:https');

// Fixed routes only. A GET is not sufficient proof that an endpoint is read-only.
const EXACT = new Set(['/api/vitals', '/api/containers', '/api/activity', '/api/timers', '/api/pihole/summary', '/api/agents', '/api/runners', '/api/uptime', '/api/linkcheck', '/api/notifications', '/api/trends', '/api/reports', '/api/hldb/status', '/api/hldb/health', '/api/hldb/changes', '/api/hldb/metrics', '/api/hldb/search', '/api/hldb/schema', '/api/hldb/dataplane', '/api/pricewatch']);
function allowed(pathname) {
  if (['/api/updates','/api/streams/presets','/api/hltv/vrs','/api/pihole/blocking','/api/llama/status','/api/llama/models','/api/llama/runbooks','/api/samba/status','/api/samba/config','/api/samba/backups','/api/architecture/data','/api/agentic'].includes(pathname)) return true;
  if (/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/config$/.test(pathname)) return true;
  if (/^\/api\/agents\/(rpi|opti|noblenumbat)\/apt-status$/.test(pathname)) return true;
  if (/^\/api\/reports\/[a-z0-9-]+(?:\.json)?$/.test(pathname)) return true;
  if (/^\/api\/runners\/[a-z0-9-]+(?:\/(?:history|log|report\/\d{4}-\d{2}-\d{2}))?$/.test(pathname)) return true;
  if (['/api/weather/preview','/api/streams/status','/api/hltv/day','/api/pihole/top','/api/runners/leetify-latest','/api/runners/leetify-latest/history'].includes(pathname)) return true;
  if (/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/status$/.test(pathname)) return true;
  if (/^\/api\/runners\/leetify-latest\/report\/\d{4}-\d{2}-\d{2}$/.test(pathname)) return true;
  return EXACT.has(pathname) || /^\/api\/vitals\/(rpi|opti|noblenumbat|android)$/.test(pathname) || /^\/api\/hldb\/host\/(rpi|opti|noblenumbat|android)$/.test(pathname) || /^\/api\/runners\/(homelab-doctor-latest|hardware-latest|software-latest|network-latest|coldcopy-latest)$/.test(pathname);
}
function safePath(raw) {
  const u = new URL(raw, 'http://astra.local');
  if (!allowed(u.pathname)) return null;
  const params = new URLSearchParams();
  for (const [key, value] of u.searchParams) if (['q','k','days','limit','host','metric','range','points','since','source','count','all','lines'].includes(key)) params.set(key, value.slice(0, 300));
  return u.pathname + (params.size ? '?' + params : '');
}
function createReader({ base = process.env.ASTRA_UPSTREAM || 'https://192.168.1.10:8443', timeout = 8000 } = {}) {
  const origin = new URL(base);
  if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== '/') throw new Error('ASTRA_UPSTREAM must be an HTTP(S) origin without credentials or a path');
  const cache = new Map();
  return async function read(raw) {
    const route = safePath(raw);
    if (!route) throw new Error('Monitoring route is not allowlisted');
    const ttl = /streams\/status|apt-status|\/log/.test(route) ? 5000 : route.includes('vitals') || route.includes('linkcheck') ? 30000 : /activity|timers|runners|hldb|trends/.test(route) ? 300000 : 60000;
    const previous = cache.get(route);
    if (previous && Date.now() - previous.at < ttl) return previous.promise;
    const promise = new Promise((resolve, reject) => {
      const url = new URL(route, origin);
      const transport = url.protocol === 'https:' ? https : http;
      // Local self-signed Pi certificate exception is scoped to this one request.
      const req = transport.get(url, { headers: { accept: 'application/json' }, rejectUnauthorized: process.env.ASTRA_ALLOW_SELF_SIGNED !== '1' }, res => {
        if (res.statusCode !== 200) { res.resume(); reject(new Error(`Upstream returned ${res.statusCode}`)); return; }
        let raw = ''; let bytes = 0;
        res.on('data', chunk => { bytes += chunk.length; if (bytes > 5 * 1024 * 1024) req.destroy(new Error('Upstream response exceeds 5 MB')); else raw += chunk; });
        res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { reject(new Error('Upstream returned non-JSON data')); } });
        res.on('error', reject);
      });
      const deadline = setTimeout(() => req.destroy(new Error('Upstream timed out')), timeout);
      req.on('close', () => clearTimeout(deadline));
      req.on('error', reject);
    });
    cache.set(route, { at: Date.now(), promise });
    try { return await promise; } catch (error) { cache.delete(route); throw error; }
  };
}
module.exports = { allowed, safePath, createReader };
