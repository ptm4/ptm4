// Fictional, stable demo observations. Never used as a fallback for live data.
const observedAt = new Date().toISOString();
const ago = minutes => new Date(Date.parse(observedAt) - minutes * 60000).toISOString();
const hosts = [
  { id: 'rpi', role: 'DNS & web', address: '192.168.1.10', os: 'Ubuntu · Raspberry Pi 4', cpu: 12, memory: 48, temperature: 48, uptime: 1048000, status: 'healthy', storage: 'System · 42% used' },
  { id: 'opti', role: 'Storage & control', address: '192.168.1.11', os: 'Debian · Storage server', cpu: 7, memory: 36, temperature: 39, uptime: 2496000, status: 'healthy', storage: 'red · 61% used' },
  { id: 'noblenumbat', role: 'Media & downloads', address: '192.168.1.6', os: 'Ubuntu · Media server', cpu: 23, memory: 62, temperature: 54, uptime: 691200, status: 'healthy', storage: 'System · 34% used' },
  { id: 'android', role: 'Local intelligence', address: '192.168.1.54', os: 'Termux · Galaxy S10', cpu: null, memory: null, temperature: null, uptime: null, status: 'unavailable', storage: 'Not reporting' },
].map(h => ({ ...h, observedAt, error: h.id === 'android' ? 'Intermittent host · asleep in this demo' : null }));
const services = [
  ['pihole', 'Pi-hole', 'rpi', 'Network', 'http://rpi.lan/admin', 'pi-hole.svg'],
  ['webapp', 'Homelab v2', 'rpi', 'Tools', 'https://webapp.rpi.lan:8443/', 'generic.svg'],
  ['vaultwarden', 'Vaultwarden', 'rpi', 'Tools', 'https://bitwarden.rpi.lan/', 'vaultwarden.svg'],
  ['jellyfin', 'Jellyfin', 'noblenumbat', 'Media', 'http://jellyfin.lan:8096/', 'jellyfin.svg'],
  ['kavita', 'Kavita', 'noblenumbat', 'Media', 'http://comics.lan:5000/', 'kavita.svg'],
  ['sonarr', 'Sonarr', 'noblenumbat', 'Media', 'http://noblenumbat.lan:8989/', 'sonarr.svg'],
  ['qbittorrent', 'qBittorrent', 'noblenumbat', 'Downloads', 'http://noblenumbat.lan:8081/', 'qbittorrent.svg'],
  ['gluetun', 'Gluetun VPN', 'noblenumbat', 'Network', null, 'generic.svg'],
  ['homelab-db', 'Homelab database', 'opti', 'Tools', null, 'generic.svg'],
].map(([id, name, host, group, url, icon]) => ({ id, name, host, group, url, icon, status: 'healthy', image: `${id}:demo`, observedAt }));
const findings = [
  { id: 'demo-updates-rpi', host: 'rpi', severity: 'warn', source: 'software', message: '4 packages are ready for review', detail: 'Review the software report and plan a convenient maintenance window. No updates have been installed.', ts: ago(180) },
  { id: 'demo-backup-opti', host: 'opti', severity: 'info', source: 'coldcopy', message: 'Weekly cold copy completed', detail: 'Sample backup report: the most recent copy finished successfully.', ts: ago(120) },
  { id: 'demo-network', host: 'noblenumbat', severity: 'info', source: 'network', message: 'Media VPN and network checks passed', detail: 'Sample report only. Live mode displays the actual collector report.', ts: ago(25) },
];
const schedules = [
  { host: 'rpi', unit: 'homelab-doctor.timer', next: new Date(Date.parse(observedAt) + 20 * 60000).toISOString(), passed: '10 minutes ago' },
  { host: 'opti', unit: 'coldcopy.timer', next: new Date(Date.parse(observedAt) + 3 * 86400000).toISOString(), passed: '2 hours ago' },
  { host: 'noblenumbat', unit: 'vpn-stack-heal.timer', next: new Date(Date.parse(observedAt) + 5 * 60000).toISOString(), passed: '5 minutes ago' },
];
const sample = h => ({ t: Date.parse(observedAt) / 1000, cpu_pct: h.cpu, mem_pct: h.memory, temp_c: h.temperature, uptime_s: h.uptime, load1: .2, rx_bps: 82000, tx_bps: 14000 });
findings.sort((a,b)=>Date.parse(b.ts)-Date.parse(a.ts));
const snapshot = { mode: 'demo', observedAt, hosts, services, findings, schedules, dns: { dns_queries_today: 148920, ads_blocked_today: 36932, ads_percentage_today: 24.8, unique_clients: 18, gravity_domains: 187420, blocking: { enabled: true, timer: null } }, sources: [], errors: [] };
function fixture(pathname, params = new URLSearchParams()) {
  const extended=require('./extra-fixtures')(pathname,params,{hosts,services,findings,observedAt});
  if(extended!==undefined)return extended;
  if (pathname === '/api/weather/preview') return { payload:{embeds:[{title:'Sample forecast',fields:[{name:'☀ BELLEROSE, NY',value:'**76° / 62°**\nSample: partly sunny'},{name:'☁ HOME',value:'**72° / 59°**\nSample: cloudy'}]}]} };
  if (pathname === '/api/streams/status') return { slots:[{slot:1,channel:'Sample stream',platform:'Demo',running:true,title:'Illustrative playback status'}] };
  if (pathname === '/api/hltv/day') return { date:observedAt.slice(0,10),fetched_at:Date.parse(observedAt)/1000,stale:false,matches:[{id:'sample',team1:'Sample team A',team2:'Sample team B',status:'upcoming',start_unix:Date.parse(observedAt)/1000+7200,event:'Demo exhibition',stars:3}] };
  if (/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/status$/.test(pathname)) return { enabled:true,last_status:'Demo: healthy',next_post_at:ago(-60),last_post_at:ago(60) };
  if (pathname === '/api/pihole/top') return { domains:[{domain:'sample-ad.example',count:214},{domain:'sample-tracker.example',count:84}] };
  if (pathname === '/api/runners/leetify-latest/history') return { history:[] };
  if (pathname === '/api/runners/leetify-latest') return { dimensions:{Aim:64,Positioning:71,Utility:58},summary:'Illustrative coaching metrics; no real match data.',run_at:observedAt };
  if (pathname === '/api/pricewatch') return { run_at:observedAt,summary:'Fictional prices for interface preview only',items:[{id:'demo-ssd',label:'Example 2 TB SSD',category:'ssd',retailer:'Demo · not a real offer',price:129,target_price:120}],history:{},below_target:[] };
  if (pathname === '/api/vitals') return { hosts: Object.fromEntries(hosts.map(h => [h.id, { count: h.cpu === null ? 0 : 60, latest: h.cpu === null ? null : sample(h), error: h.error, agent_version: 'demo' }])), interval_s: 30 };
  if (/^\/api\/vitals\//.test(pathname)) { const h = hosts.find(h => h.id === pathname.split('/').pop()); if (!h) return undefined; return { host: h.id, cores: 4, error: h.error, latest: h.cpu===null?null:sample(h), samples: h.cpu === null ? [] : Array.from({ length: 60 }, (_, i) => ({ ...sample(h), t: Date.parse(observedAt) / 1000 - (59-i)*30, cpu_pct: Math.max(1, h.cpu + Math.sin(i * .8) * 5), mem_pct: h.memory + Math.sin(i / 8) * 2 })) }; }
  if (pathname === '/api/containers') return { hosts: hosts.map(h => ({ host: h.id, doctor_at: observedAt, fragment_at: observedAt, containers: services.filter(s => s.host === h.id && s.id !== 'homelab-db').map(s => ({ name: s.id, up: true, state: 'running', status: 'Up 12 days', image: s.image, update_available: false, ports: [] })) })) };
  if (pathname === '/api/activity') return { events: findings.map(f => ({ ...f })) };
  if (pathname === '/api/notifications') return { items: findings.filter(f => f.severity === 'warn'), unacked: 1, total:1 };
  if (pathname === '/api/timers') return { hosts: hosts.map(h => ({ host: h.id, timers: schedules.filter(s => s.host === h.id) })) };
  if (pathname === '/api/pihole/summary') return snapshot.dns;
  if (pathname === '/api/agents') return { hosts: hosts.map(h => ({ id: h.id, label: h.id, reachable: h.status === 'healthy', last_run: observedAt, agent_version: '2026-09-01', drift_count: 0, allowed_units: ['docker.service','ssh.service'], wake_targets:['noblenumbat'] })) };
  if (pathname === '/api/uptime') return { ok: true, total: services.length, up: services.length, down: 0, pending: 0, monitors: services.map(s => ({ name: s.name, status: 'up', ms: 12 })) };
  if (pathname === '/api/runners') return { runners: ['homelab-doctor', 'software', 'network', 'coldcopy'].map(name => ({ name, label: name, status: name === 'software' ? 'warn' : 'ok', summary: 'Illustrative collector result', run_at: observedAt, stale: false, enabled: true })) };
  if (pathname.startsWith('/api/runners/')) return { run_at: observedAt, status: 'ok', findings, hosts: hosts.map(h => ({ host: h.id, status: 'ok', metrics: { disk_used_pct: 42, pool: { used_pct: 61, pool_name: 'red' } } })) };
  if (pathname === '/api/linkcheck') return { origins: Object.fromEntries(services.filter(s => s.url).map(s => [new URL(s.url).origin, { up: true, status: 200 }])) };
  if (pathname === '/api/hldb/search') return { results: [{ title: 'Network, DHCP & DNS', path: 'homelab/agentic/runbooks/02-network-dhcp-dns.md', snippet: 'Pi-hole supplies DNS and DHCP. Check collector freshness before investigating a host.', query: params.get('q') || '' }] };
  if (pathname === '/api/hldb/changes') return { changes: findings.map(f => ({ ...f, timestamp: f.ts, change_type: f.source })) };
  if (pathname === '/api/hldb/status') return { status: 'ok', note: 'Fictional database summary', reports: 1842, hosts: 4 };
  if (pathname === '/api/hldb/schema') return { tables: [{ name: 'reports', description: 'Collector observations (demo)' }, { name: 'metrics', description: 'Historical metrics (demo)' }] };
  return undefined;
}
// Advance only fictional observations with the demo clock, so a preview left
// running overnight still has useful upcoming jobs. Live data never uses this.
function freshDemo(value) {
 const delta=Date.now()-Date.parse(observedAt);
 const walk=(v,key)=>{
  if(Array.isArray(v))return v.map(x=>walk(x,''));
  if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,walk(x,k)]));
  if(typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:/.test(v)&&Number.isFinite(Date.parse(v)))return new Date(Date.parse(v)+delta).toISOString();
  if(typeof v==='number'&&['t','fetched_at','start_unix'].includes(key))return v+delta/1000;
  return v;
 };
 return walk(value,'');
}
module.exports = { snapshot, fixture, freshDemo };
