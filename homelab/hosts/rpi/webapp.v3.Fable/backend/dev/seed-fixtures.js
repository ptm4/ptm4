#!/usr/bin/env node
// Seed a scratch data directory so the backend can run off-box with believable
// reports: `node dev/seed-fixtures.js <dir>` writes agent-logs/, reports/ and
// arch-data/ under <dir>, then start the app with
//   AGENT_LOGS_DIR=<dir>/agent-logs REPORTS_DIR=<dir>/reports ARCH_DATA_DIR=<dir>/arch-data node server.js
// Vitals still come from the real agents (they are addressed by LAN IP); set
// VITALS_DISABLED=1 to run fully offline. Nothing here touches the live volume.
const fs = require('fs');
const path = require('path');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..', '..', '.dev-data'));
const AGENT_LOGS = path.join(root, 'agent-logs');
const REPORTS = path.join(root, 'reports');
const ARCH = path.join(root, 'arch-data');
for (const d of [AGENT_LOGS, path.join(AGENT_LOGS, 'homelab-doctor-latest'), REPORTS, path.join(ARCH, 'fragments')]) fs.mkdirSync(d, { recursive: true });

const now = new Date();
const iso = (minsAgo = 0) => new Date(now.getTime() - minsAgo * 60_000).toISOString();
const w = (file, data) => fs.writeFileSync(file, JSON.stringify(data, null, 2));

w(path.join(AGENT_LOGS, 'homelab-doctor-latest.json'), {
  status: 'warn', summary: '4/4 hosts, 31/31 containers — opti / at 85%', run_at: iso(24),
  findings: [
    { severity: 'warn', message: '[opti] root filesystem at 85% (warn ≥ 80%)' },
    { severity: 'warn', message: '[opti] pool red at 26% — growth 2 GB/week' },
    { severity: 'critical', message: '[noblenumbat] gluetun forwarded port changed 3 times in 24h' },
  ],
  recommendations: [{ severity: 'medium', message: '[rpi] vaultwarden 1.33.1 → 1.34.0 available' }],
  hosts: [
    { host: 'rpi', status: 'ok', summary: '16/16 containers', metrics: { containers: [
      { name: 'pihole', status: 'Up 20 days' }, { name: 'webapp', status: 'Up 2 hours' }, { name: 'nginx-webapp', status: 'Up 2 hours' },
      { name: 'bitwarden', status: 'Up 20 days' }, { name: 'uptime-kuma', status: 'Up 20 days' }, { name: 'dozzle', status: 'Up 20 days' },
    ], disk_used_pct: 29, vpn: null, autoupdate: { last_run: iso(600), result: 'ok' } } },
    { host: 'opti', status: 'warn', summary: 'root 85%', metrics: { pool: { used_pct: 26.1, pool_name: 'red', size_gb: 3700 }, disk_used_pct: 85,
      autoupdate: { last_run: iso(1300), result: 'held', detail: 'zfs-dkms held back' } } },
    { host: 'noblenumbat', status: 'ok', summary: '15/15 containers', metrics: { containers: [
      { name: 'gluetun', status: 'Up 20 hours' }, { name: 'jellyfin', status: 'Up 32 hours' }, { name: 'qbittorrent', status: 'Up 20 hours' },
      { name: 'sonarr', status: 'Up 32 hours' }, { name: 'radarr', status: 'Up 32 hours' }, { name: 'prowlarr', status: 'Exited (1) 5 minutes ago' },
    ], disk_used_pct: 18, vpn: { status: 'ok', forwarded_port: 52644, actions: [{ ts: iso(400), action: 'NAT-PMP lease renewed; forwarded port unchanged (52644)' }] } } },
  ],
});
w(path.join(AGENT_LOGS, 'homelab-doctor-latest', now.toISOString().slice(0, 10) + '.json'), {
  hosts: [{ host: 'opti', metrics: { pool: { used_pct: 26.1, pool_name: 'red' }, disk_used_pct: 85 } }],
});
w(path.join(AGENT_LOGS, 'hardware-latest.json'), {
  status: 'ok', summary: 'all disks healthy', run_at: iso(180),
  hosts: [
    { host: 'rpi', status: 'ok', metrics: { uptime: '20 days', cpu_model: 'Cortex-A72', mem_total_gib: 3.7, temp_c: 41, disks: [{ mount: '/', used_pct: 29, size_gb: 117 }] } },
    { host: 'opti', status: 'ok', metrics: { uptime: '42 days', cpu_model: 'i5-3570', mem_total_gib: 5.7, temp_c: 33, disks: [{ mount: '/', used_pct: 85, size_gb: 60 }] } },
    { host: 'noblenumbat', status: 'ok', metrics: { uptime: '1 day', cpu_model: 'i7-8665U', mem_total_gib: 15.4, temp_c: 46, disks: [{ mount: '/', used_pct: 18, size_gb: 476 }] } },
  ],
});
w(path.join(AGENT_LOGS, 'software-latest.json'), {
  status: 'warn', summary: '4 image updates · 23 packages', run_at: iso(240),
  findings: [{ severity: 'warn', message: '[rpi] 1 image update pending' }],
  hosts: [
    { host: 'rpi', metrics: { pending_count: 4, security_count: 1, reboot_required: false, image_updates: [{ image: 'vaultwarden/server', containers: ['bitwarden'], current: 'sha256:aa', available: 'sha256:bb' }] } },
    { host: 'opti', metrics: { pending_count: 19, security_count: 3, reboot_required: true, reboot_pkgs: ['linux-image-amd64'] } },
    { host: 'noblenumbat', metrics: { pending_count: 0, image_updates: [
      { image: 'jellyfin/jellyfin', containers: ['jellyfin'] }, { image: 'linuxserver/prowlarr', containers: ['prowlarr'] }, { image: 'qmcgaw/gluetun', containers: ['gluetun'] },
    ] } },
  ],
});
w(path.join(AGENT_LOGS, 'network-latest.json'), {
  status: 'ok', summary: 'all hosts reachable · gateway 1.2 ms', run_at: iso(20), findings: [],
  hosts: [{ host: 'rpi', metrics: { gateway_avg_ms: 1.2, internet_avg_ms: 14 } }, { host: 'opti', metrics: { gateway_avg_ms: 0.8 } }, { host: 'noblenumbat', metrics: { gateway_avg_ms: 2.1 } }],
});
w(path.join(AGENT_LOGS, 'coldcopy-latest.json'), { status: 'ok', summary: 'weekly cold copy finished — 41 GiB in 12m', run_at: iso(1200), findings: [] });
w(path.join(AGENT_LOGS, 'agents-state.json'), { 'homelab-doctor': { enabled: true }, hardware: { enabled: true }, software: { enabled: true }, network: { enabled: true }, coldcopy: { enabled: true } });

w(path.join(REPORTS, 'journal-hunt-latest.json'), {
  status: 'warn', summary: '1 suspicious pattern in 24h of journals', run_at: iso(90),
  findings: [{ severity: 'high', host: 'rpi', message: '14 failed SSH logins from 192.168.1.77 in 10 minutes' }],
});
w(path.join(REPORTS, 'persistence-audit-latest.json'), { status: 'ok', summary: 'no new persistence mechanisms', run_at: iso(95), findings: [] });

const frag = (host, containers) => w(path.join(ARCH, 'fragments', `${host}.json`), {
  host, collected_at: iso(15), agent_version: '0.4.2',
  docker: { containers: containers.map((c) => ({ name: c[0], state: c[1] ?? 'running', image: c[2] ?? `${c[0]}:latest`, status_since: iso(c[3] ?? 2000), compose_project: 'compose', ports: [] })) },
  timers: [
    { raw: `Sun ${now.toISOString().slice(0, 10)} 02:00:00 UTC 4h left Sat 22:00:00 UTC 2h ago homelab-autoupdate.timer homelab-autoupdate.service` },
    { raw: `Mon ${now.toISOString().slice(0, 10)} 09:00:00 UTC 11h left Sun 09:00:00 UTC 13h ago hardware-report.timer hardware-report.service` },
  ],
});
frag('rpi', [['pihole'], ['webapp', 'running', 'node:lts-alpine', 120], ['nginx-webapp', 'running', 'nginx:stable-alpine', 120], ['bitwarden', 'running', 'vaultwarden/server'], ['uptime-kuma'], ['dozzle']]);
frag('noblenumbat', [['gluetun', 'running', 'qmcgaw/gluetun', 1200], ['jellyfin'], ['qbittorrent'], ['sonarr'], ['radarr'], ['prowlarr', 'exited', 'linuxserver/prowlarr', 5]]);
frag('opti', []);

console.log(`seeded ${root}`);
console.log(`AGENT_LOGS_DIR=${AGENT_LOGS}`);
console.log(`REPORTS_DIR=${REPORTS}`);
console.log(`ARCH_DATA_DIR=${ARCH}`);
