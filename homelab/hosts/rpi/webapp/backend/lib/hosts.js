// The single source of truth for "which hosts run an hl-arch-agent".
// Matches rules/01-homelab-context.md's host table. Hardcoded rather than
// env-configured because these are the fixed three hosts the agent is installed
// on — consistent with how build-arch-data.py and the network runner already
// hardcode this homelab's known topology.
// Consumed by routes/agents.js (control proxies) and plugins/vitals-poller.js.
const AGENT_HOSTS = {
  opti:        { label: 'opti',        base: 'http://192.168.1.11:8787' },
  rpi:         { label: 'rpi',         base: 'http://192.168.1.10:8787' },
  noblenumbat: { label: 'noblenumbat', base: 'http://192.168.1.6:8787' },
};

module.exports = { AGENT_HOSTS };
