// The fleet Pertal knows about. Matches the host table in rules/01-homelab-context.md.
// Hardcoded on purpose: these are the fixed machines, and every other module (sources,
// resources, actions) reads them from here so there is exactly one list.
'use strict';

const HOSTS = [
  {
    id: 'opti', label: 'opti', ip: '192.168.1.11', os: 'Debian 12',
    role: 'Storage + app tier',
    agent: 'http://192.168.1.11:8787',
    console: { root: '/cp-opti', upstream: 'http://cockpit-opti:9090' },
    links: { cockpit: '/console/opti/system', terminal: '/console/opti/system/terminal', omv: 'http://192.168.1.11' },
  },
  {
    id: 'rpi', label: 'rpi', ip: '192.168.1.10', os: 'Ubuntu 24.04',
    role: 'DNS (Pi-hole)',
    agent: 'http://192.168.1.10:8787',
    console: { root: '/cp-rpi', upstream: 'http://cockpit-rpi:9090' },
    links: { cockpit: '/console/rpi/system', terminal: '/console/rpi/system/terminal', pihole: 'http://192.168.1.10/admin' },
  },
  {
    id: 'noblenumbat', label: 'noblenumbat', ip: '192.168.1.6', os: 'Ubuntu 24.04',
    role: 'Media',
    agent: 'http://192.168.1.6:8787',
    console: { root: '/cp-noblenumbat', upstream: 'http://cockpit-noblenumbat:9090' },
    links: { cockpit: '/console/noblenumbat/system', terminal: '/console/noblenumbat/system/terminal', jellyfin: 'http://192.168.1.6:8096', kuma: 'http://192.168.1.6:3001' },
  },
  {
    // No agent: an unrooted phone. Reachability is a TCP probe of its sshd.
    id: 'android', label: 'android', ip: '192.168.1.54', os: 'Android (Termux)',
    role: 'Local LLM',
    agent: null,
    probe: { port: 8022 },
    intermittent: true,
    links: {},
  },
];

const AGENT_HOSTS = Object.fromEntries(HOSTS.filter((h) => h.agent).map((h) => [h.id, h]));
const hostById = (id) => HOSTS.find((h) => h.id === id) || null;

module.exports = { HOSTS, AGENT_HOSTS, hostById };
