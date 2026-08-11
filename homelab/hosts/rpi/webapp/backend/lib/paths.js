// Central directory resolution for everything the container reads or writes.
// Resolution order per dir: env override → container mount → repo-relative dev path.
// The env overrides are what let the smoke/parity suite run the whole app off-box
// (noblenumbat, CI) against scratch dirs without touching the real volume.
const fs = require('fs');
const path = require('path');

const WEBAPP_ROOT = path.join(__dirname, '..', '..');            // homelab/hosts/rpi/webapp
const HOMELAB_ROOT = path.join(WEBAPP_ROOT, '..', '..', '..');   // homelab/
const REPO_ROOT = path.join(HOMELAB_ROOT, '..');                 // ptm4/

function pick(envName, mountPath, devPath) {
  if (process.env[envName]) return process.env[envName];
  if (fs.existsSync(mountPath)) return mountPath;
  return devPath;
}

module.exports = {
  WEBAPP_ROOT,

  // opti pool over CIFS, :ro — runner reports + agents-state.json
  AGENT_LOGS_DIR: pick('AGENT_LOGS_DIR', '/agent-logs', path.join(HOMELAB_ROOT, 'agent-logs')),

  // opti pool over CIFS, :ro — security agent reports
  REPORTS_DIR: pick('REPORTS_DIR', '/reports', path.join(HOMELAB_ROOT, 'security-reports')),

  // the ONE writable mount (named volume arch_data) — fragments, vitals, ui state
  ARCH_DATA_DIR: pick('ARCH_DATA_DIR', '/arch-data', path.join(HOMELAB_ROOT, 'arch-data-dev')),

  // ptm4 repo root, :ro — the agentic manifest + wiring files
  WORKSPACE_DIR: pick('WORKSPACE_DIR', '/workspace', REPO_ROOT),

  // old vanilla app, served verbatim at /legacy/ (and at / until the Vite build exists)
  LEGACY_DIR: path.join(WEBAPP_ROOT, 'frontend-legacy'),

  // Vite build output of the v2 app — present once CI has built it
  DIST_DIR: path.join(WEBAPP_ROOT, 'frontend', 'dist'),
};
