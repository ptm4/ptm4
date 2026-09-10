// Updates center — one work queue instead of hunting through host cards.
//
// Two kinds of pending work, both already collected by existing runners/agents:
//   container images  — software-latest's image_updates ⋈ the live container list
//   apt packages      — software-latest's per-host package counts
//
// Applying an update reuses the existing per-container agent endpoint
// (/api/agents/:host/update-container); this route is read-only aggregation.
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('../lib/controls');
const { readFragments } = require('../lib/arch-data');

const readReport = (name) => {
  try { return JSON.parse(fs.readFileSync(path.join(AGENT_LOGS_DIR, `${name}.json`), 'utf8')); }
  catch (_) { return null; }
};

// Containers serving this page: an update replaces the thing answering the request.
// Flagged so the UI can warn rather than hide them.
const SELF_CONTAINERS = new Set(['webapp', 'nginx-webapp']);

module.exports = async function updatesRoutes(app) {
  app.get('/', async () => {
    const software = readReport('software-latest');
    const doctor = readReport('homelab-doctor-latest');
    const fragments = readFragments();

    const images = [];
    const packages = [];

    for (const h of software?.hosts || []) {
      const m = h.metrics || {};

      for (const u of m.image_updates || []) {
        for (const container of u.containers || []) {
          const frag = fragments[h.host]?.docker?.containers?.find((c) => c.name === container);
          const docRow = (doctor?.hosts || []).find((x) => x.host === h.host)
            ?.metrics?.containers?.find((c) => c.name === container);
          images.push({
            host: h.host,
            container,
            image: u.image || frag?.image || null,
            current_digest: u.current || null,
            available_digest: u.available || null,
            compose_project: frag?.compose_project || null,
            running: frag?.state === 'running' || /^up/i.test(docRow?.status || ''),
            self: SELF_CONTAINERS.has(container),
          });
        }
      }

      if (m.pending_count) {
        packages.push({
          host: h.host,
          pending: m.pending_count,
          security: m.security_count || 0,
          reboot_required: !!m.reboot_required,
          reboot_pkgs: m.reboot_pkgs || null,
        });
      } else if (m.reboot_required) {
        packages.push({
          host: h.host, pending: 0, security: 0,
          reboot_required: true, reboot_pkgs: m.reboot_pkgs || null,
        });
      }
    }

    images.sort((a, b) => a.host.localeCompare(b.host) || a.container.localeCompare(b.container));
    packages.sort((a, b) => a.host.localeCompare(b.host));

    return {
      images,
      packages,
      counts: {
        images: images.length,
        packages: packages.reduce((n, p) => n + p.pending, 0),
        security: packages.reduce((n, p) => n + p.security, 0),
        reboots: packages.filter((p) => p.reboot_required).length,
      },
      collected_at: software?.run_at || null,
      generated_at: new Date().toISOString(),
    };
  });
};
