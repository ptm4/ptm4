const crypto = require('node:crypto');
const HOSTS = { rpi: ['DNS & web', '192.168.1.10'], opti: ['Storage & control', '192.168.1.11'], noblenumbat: ['Media & downloads', '192.168.1.6'], android: ['Local intelligence', '192.168.1.54'] };
function timestamp(t) { if (!t) return null; const n = typeof t === 'number' ? (t < 1e12 ? t * 1000 : t) : Date.parse(t); return Number.isFinite(n) ? new Date(n).toISOString() : null; }
function numeric(v) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }
async function liveSnapshot(read, previous = null) {
  const routes = ['/api/vitals','/api/containers','/api/activity','/api/timers','/api/pihole/summary','/api/notifications?all=1'];
  const results = await Promise.allSettled(routes.map(route => read(route)));
  const values = results.map(r => r.status === 'fulfilled' ? r.value : null);
  const [vitals, containers, activity, timers, dns, notifications] = values;
  const errors = results.flatMap((r,i) => r.status === 'rejected' ? [{ source: routes[i], message: r.reason.message || 'Unavailable' }] : []);
  let hosts = Object.entries(HOSTS).map(([id,[role,address]]) => {
    const v = vitals?.hosts?.[id]; const latest = v?.latest; const observedAt = timestamp(latest?.t);
    return { id, role, address, os: 'Live collector', cpu: numeric(latest?.cpu_pct), memory: numeric(latest?.mem_pct), temperature: numeric(latest?.temp_c), uptime: numeric(latest?.uptime_s), observedAt, status: !latest ? 'unavailable' : v?.error || !observedAt || Date.now()-Date.parse(observedAt)>90000 ? 'stale' : 'healthy', error: v?.error || (!latest ? 'No current observation' : null), storage: 'See hardware report' };
  });
  let services = (containers?.hosts || []).flatMap(h => (h.containers || []).map(c => ({ id: `${h.host}:${c.name}`, name: c.name, host: h.host, group: c.compose_project || 'Services', url: null, icon: 'generic.svg', status: !timestamp(h.fragment_at || h.doctor_at) || Date.now()-Date.parse(h.fragment_at || h.doctor_at)>3600000 ? 'stale' : c.up === true ? 'healthy' : c.up === false ? 'unavailable' : 'unknown', image: c.image || null, observedAt: timestamp(h.fragment_at || h.doctor_at) })));
  const all = [...(notifications?.items || []), ...(activity?.events || [])];
  const seen = new Set();
  const findings = all.map(f => ({ id: f.id || crypto.createHash('sha256').update(`${f.source}|${f.host}|${f.message}`).digest('hex').slice(0,20), source: f.source || 'report', host: f.host || null, severity: f.severity || 'info', message: f.message || 'Finding', detail: f.detail || '', ts: timestamp(f.ts) })).filter(f => !seen.has(f.id) && seen.add(f.id)).sort((a,b) => (Date.parse(b.ts)||0)-(Date.parse(a.ts)||0));
  if (!vitals && previous) hosts=previous.hosts.map(h=>({...h,status:'stale',error:'Latest read failed; showing last observation'}));
  if (!containers && previous) services=previous.services.map(s=>({...s,status:'stale'}));
  return { mode: 'live-readonly', observedAt: new Date().toISOString(), hosts, services, findings:!activity&&!notifications&&previous?previous.findings:findings, schedules: !timers&&previous?previous.schedules:(timers?.hosts || []).flatMap(h => (h.timers || []).map(t => ({ ...t, host: h.host }))), dns, errors, sources: routes.map((route,i) => ({ route, available: results[i].status === 'fulfilled' })) };
}
module.exports = { liveSnapshot, timestamp };
