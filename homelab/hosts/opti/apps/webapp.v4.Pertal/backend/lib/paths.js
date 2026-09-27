// Where the container reads and writes. Order per dir: env override → container mount
// → repo-relative dev path. ARCH_DATA_DIR is shared with v3 (named volume arch_data), so
// job audit, vitals and agent fragments survive the cutover.
'use strict';
const fs = require('fs');
const path = require('path');

const APP_ROOT = path.join(__dirname, '..', '..'); // homelab/hosts/opti/apps/webapp.v4.Pertal

function pick(envName, mountPath, devPath) {
  if (process.env[envName]) return process.env[envName];
  if (fs.existsSync(mountPath)) return mountPath;
  return devPath;
}

module.exports = {
  APP_ROOT,
  ARCH_DATA_DIR: pick('ARCH_DATA_DIR', '/arch-data', path.join(APP_ROOT, '.dev-data', 'arch-data')),
  DIST_DIR: process.env.DIST_DIR || path.join(APP_ROOT, 'frontend', 'dist'),
};
