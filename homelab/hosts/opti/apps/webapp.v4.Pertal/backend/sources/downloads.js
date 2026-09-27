// Downloads: qBittorrent (behind gluetun on noblenumbat) and the VPN it rides.
//   qbt:queue   5s   torrents + transfer totals
//   vpn:gluetun 30s  public IP / country / forwarded port from gluetun's control server
//
// qBittorrent's WebUI whitelists the LAN subnet, so no password is needed from opti.
// If that ever changes, set QBT_USER / QBT_PASS and the client logs in (cookie kept).
'use strict';

const QBT_URL = process.env.QBT_URL || 'http://192.168.1.6:8081';
const GLUETUN_URL = process.env.GLUETUN_URL || 'http://192.168.1.6:8003';
const USER = process.env.QBT_USER || '';
const PASS = process.env.QBT_PASS || '';

let cookie = null;
async function login(signal) {
  const res = await fetch(`${QBT_URL}/api/v2/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Referer: QBT_URL },
    body: new URLSearchParams({ username: USER, password: PASS }),
    signal,
  });
  const text = await res.text();
  if (!res.ok || text.trim() !== 'Ok.') throw new Error('qBittorrent refused the login');
  cookie = (res.headers.get('set-cookie') || '').split(';')[0];
}

// One request to qBittorrent's Web API. `body` may be URLSearchParams or FormData.
async function qbt(path, { method = 'GET', body, signal, timeoutMs = 8000 } = {}) {
  const sig = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
  const send = () => fetch(`${QBT_URL}/api/v2${path}`, {
    method, body, signal: sig,
    headers: { Referer: QBT_URL, ...(cookie ? { Cookie: cookie } : {}) },
  });
  let res = await send();
  if (res.status === 403 && USER) { await login(sig); res = await send(); }
  if (res.status === 403) throw new Error('qBittorrent answered 403 — set QBT_USER/QBT_PASS or whitelist opti in its WebUI settings');
  const text = await res.text();
  if (!res.ok) throw new Error(`qBittorrent ${path}: HTTP ${res.status}${text ? ` — ${text.slice(0, 120)}` : ''}`);
  try { return JSON.parse(text); } catch { return text; }
}

const pickTorrent = (t) => ({
  hash: t.hash, name: t.name, size: t.size, progress: t.progress, state: t.state,
  dlspeed: t.dlspeed, upspeed: t.upspeed, eta: t.eta, category: t.category,
  added_on: t.added_on, completion_on: t.completion_on, ratio: t.ratio,
  seeds: t.num_seeds, peers: t.num_leechs, save_path: t.save_path,
});

function registerDownloadSources(snapshots) {
  snapshots.register({
    key: 'qbt:queue', group: 'downloads', label: 'qBittorrent queue',
    intervalMs: 5000, timeoutMs: 6000, staleAfterMs: 30_000,
    fetch: async ({ signal }) => {
      const [torrents, transfer] = await Promise.all([qbt('/torrents/info', { signal }), qbt('/transfer/info', { signal })]);
      return {
        transfer: {
          status: transfer.connection_status, dl_speed: transfer.dl_info_speed, up_speed: transfer.up_info_speed,
          dl_total: transfer.dl_info_data, up_total: transfer.up_info_data, dht_nodes: transfer.dht_nodes,
        },
        torrents: torrents.map(pickTorrent).sort((a, b) => b.added_on - a.added_on),
      };
    },
  });
  snapshots.register({
    key: 'vpn:gluetun', group: 'downloads', label: 'VPN (gluetun)',
    intervalMs: 30_000, timeoutMs: 6000, staleAfterMs: 3 * 60_000,
    fetch: async ({ signal }) => {
      const get = async (p) => { const r = await fetch(`${GLUETUN_URL}${p}`, { signal }); if (!r.ok) throw new Error(`gluetun ${p}: HTTP ${r.status}`); return r.json(); };
      const [ip, pf] = await Promise.all([get('/v1/publicip/ip'), get('/v1/portforward').catch(() => ({ port: null }))]);
      return { public_ip: ip.public_ip ?? null, country: ip.country ?? null, city: ip.city ?? null, org: ip.organization ?? null, forwarded_port: pf.port ?? null };
    },
  });
}

module.exports = { registerDownloadSources, qbt };
