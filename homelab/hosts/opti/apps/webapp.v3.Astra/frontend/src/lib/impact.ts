// Blast-radius copy for destructive actions. These strings are the whole point of
// the typed-confirmation gates: they say what actually breaks while the thing is
// down, in this specific homelab.

export const HOST_ROLES: Record<string, string> = {
  rpi: 'DNS · DHCP · web',
  opti: 'storage · control plane',
  noblenumbat: 'media stack',
  android: 'local LLM',
};

export const HOST_REBOOT_IMPACT: Record<string, string> = {
  opti: 'ZFS pool and \\\\opti\\red drop for every host — reports, container data, Samba and the dispatcher all stall until it returns (~2–3 min). The agent runs a ZFS-DKMS guard first and refuses if the next kernel has no zfs module.',
  rpi: 'LAN DNS + DHCP (Pi-hole) AND this dashboard go down (~2 min). Your WireGuard tunnel survives — it terminates on the router. rpi boots from an SD card: small chance it does not come back, so reboot it remotely only if you must.',
  noblenumbat: 'Jellyfin, the *arr stack and the VPN go down (~2 min). vpn-stack-heal re-establishes the tunnel within 2 minutes of boot.',
};

// Units whose restart is disruptive enough for the typed gate.
export const CRITICAL_UNITS = new Set(['smbd.service', 'docker.service']);

export const UNIT_IMPACT: Record<string, string> = {
  'smbd.service': 'Samba drops briefly — hosts with \\\\opti\\red mounted may see I/O errors for a few seconds. (This is also the recovery lever for stale CIFS handles.)',
  'docker.service': 'Restarts the Docker daemon AND every container on the host.',
};

export const UNIT_LABELS: Record<string, string> = {
  'hl-agent-dispatcher.service': 'dispatcher',
  'hl-arch-agent.service': 'agent',
  'smbd.service': 'samba',
  'docker.service': 'docker',
  'vpn-stack-heal.service': 'vpn heal',
};

export const CRITICAL_CONTAINERS: Record<string, string> = {
  pihole: "Brief LAN-wide DNS blips — Pi-hole is this network's only DNS *and* DHCP server.",
  webapp: 'This dashboard stops responding while its container comes back. The operation still completes on the host.',
  'nginx-webapp': 'This dashboard goes offline while TLS comes back.',
  bitwarden: 'Vaultwarden is unavailable while it comes back — password access included.',
  'bitwarden-db': "Vaultwarden's database — Vaultwarden may error until it reconnects.",
  'nginx-bitwarden': "Vaultwarden's TLS front end goes down briefly.",
  gluetun: 'Tears down the VPN tunnel; every *arr and qBittorrent loses network until it re-establishes, and the forwarded port may change.',
  'notes-api': 'The Notes app at /notes/ is unavailable while it comes back.',
};

// Containers that serve this page: touching one kills the response to the very
// request that asked for it. Observed both ways — the fetch fails outright, OR
// nginx outlives the backend and answers 502/504 — so both branches must treat it
// as expected, or a self-update that actually succeeded reads as a red failure.
export const SELF_CONTAINERS = new Set(['webapp', 'nginx-webapp']);

export const agentTooOld = (host: string, what: string) =>
  `The agent on ${host} is too old for ${what} — reinstall hl-arch-agent.py (v0.4.0+) on that host.`;
