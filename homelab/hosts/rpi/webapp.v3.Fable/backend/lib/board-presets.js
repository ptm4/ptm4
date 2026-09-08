// Seed boards. Two are protected (reseeded if their file goes missing, never
// deletable):
//
//   home      — the Homarr-style board: app icon grid + a few live widgets.
//   dashboard — data-density parity with the v1 bento Home: host vitals, the
//               containers table, Pi-hole/VPN, storage, network, upkeep, the
//               activity feed and the counter row.
//
// Layouts are react-grid-layout's own shape ({i,x,y,w,h}) on a 12-column grid at
// `lg`; `sm` is a single-column stack in reading order. Widget option shapes are
// the contract in frontend/src/widgets/registry.ts.

const w = (id, type, options) => ({ id, type, ...(options ? { options } : {}) });

const HOME = {
  slug: 'home',
  name: 'Home',
  protected: true,
  wallpaper: 'graphite.svg',
  glass: { opacity: 0.62, blur: 18, dim: 0.28 },
  // Sizes are tuned to content: an app group of 9 icons needs 3 rows, one of 2
  // needs 2. Oversized cards were the "big empty rectangle" problem in the first
  // cut of this board.
  widgets: [
    w('w-clock', 'clock'),
    w('w-fleet', 'fleet-status'),
    w('w-weather', 'weather', { limit: 5 }),
    w('w-apps-infra', 'app-group', { group: 'Infrastructure' }),
    w('w-apps-media', 'app-group', { group: 'Media' }),
    w('w-apps-library', 'app-group', { group: 'Library management' }),
    w('w-apps-downloads', 'app-group', { group: 'Downloads' }),
    w('w-monitors', 'monitors'),
    w('w-notifications', 'notifications', { limit: 6 }),
    w('w-bots', 'bots'),
    w('w-activity', 'activity', { limit: 10 }),
  ],
  layouts: {
    lg: [
      { i: 'w-clock', x: 0, y: 0, w: 3, h: 2 },
      { i: 'w-fleet', x: 3, y: 0, w: 5, h: 2 },
      { i: 'w-weather', x: 8, y: 0, w: 4, h: 5 },
      { i: 'w-apps-infra', x: 0, y: 2, w: 8, h: 3 },
      { i: 'w-apps-media', x: 0, y: 5, w: 3, h: 3 },
      { i: 'w-apps-library', x: 3, y: 5, w: 5, h: 3 },
      { i: 'w-apps-downloads', x: 8, y: 5, w: 4, h: 3 },
      { i: 'w-monitors', x: 0, y: 8, w: 5, h: 4 },
      { i: 'w-notifications', x: 5, y: 8, w: 4, h: 4 },
      { i: 'w-bots', x: 9, y: 8, w: 3, h: 4 },
      { i: 'w-activity', x: 0, y: 12, w: 12, h: 4 },
    ],
    sm: [
      { i: 'w-clock', x: 0, y: 0, w: 2, h: 2 },
      { i: 'w-fleet', x: 0, y: 2, w: 2, h: 2 },
      { i: 'w-weather', x: 0, y: 4, w: 2, h: 5 },
      { i: 'w-apps-infra', x: 0, y: 9, w: 2, h: 5 },
      { i: 'w-apps-media', x: 0, y: 14, w: 2, h: 2 },
      { i: 'w-apps-library', x: 0, y: 16, w: 2, h: 4 },
      { i: 'w-apps-downloads', x: 0, y: 20, w: 2, h: 2 },
      { i: 'w-notifications', x: 0, y: 22, w: 2, h: 4 },
      { i: 'w-bots', x: 0, y: 26, w: 2, h: 4 },
      { i: 'w-monitors', x: 0, y: 30, w: 2, h: 5 },
      { i: 'w-activity', x: 0, y: 35, w: 2, h: 5 },
    ],
  },
};

const DASHBOARD = {
  slug: 'dashboard',
  name: 'Dashboard',
  protected: true,
  wallpaper: 'graphite.svg',
  glass: { opacity: 0.62, blur: 18, dim: 0.28 },
  widgets: [
    w('w-host-rpi', 'host-vitals', { host: 'rpi' }),
    w('w-host-opti', 'host-vitals', { host: 'opti' }),
    w('w-host-nn', 'host-vitals', { host: 'noblenumbat' }),
    w('w-containers', 'containers', { compact: true }),
    w('w-pihole', 'pihole'),
    w('w-vpn', 'vpn'),
    w('w-storage', 'storage'),
    w('w-network', 'network'),
    w('w-upkeep', 'upkeep'),
    w('w-activity', 'activity', { limit: 20 }),
    w('w-stat-monitors', 'stat', { metric: 'monitors' }),
    w('w-stat-reports', 'stat', { metric: 'reports' }),
    w('w-stat-drift', 'stat', { metric: 'drift' }),
    w('w-stat-updates', 'stat', { metric: 'updates' }),
    w('w-quick', 'quick-links'),
  ],
  layouts: {
    lg: [
      { i: 'w-stat-monitors', x: 0, y: 0, w: 3, h: 2 },
      { i: 'w-stat-reports', x: 3, y: 0, w: 3, h: 2 },
      { i: 'w-stat-drift', x: 6, y: 0, w: 3, h: 2 },
      { i: 'w-stat-updates', x: 9, y: 0, w: 3, h: 2 },
      { i: 'w-host-rpi', x: 0, y: 2, w: 4, h: 6 },
      { i: 'w-host-opti', x: 4, y: 2, w: 4, h: 6 },
      { i: 'w-host-nn', x: 8, y: 2, w: 4, h: 6 },
      { i: 'w-containers', x: 0, y: 8, w: 4, h: 4 },
      { i: 'w-vpn', x: 4, y: 8, w: 4, h: 4 },
      { i: 'w-pihole', x: 8, y: 8, w: 4, h: 4 },
      { i: 'w-storage', x: 0, y: 13, w: 4, h: 4 },
      { i: 'w-network', x: 4, y: 13, w: 4, h: 4 },
      { i: 'w-upkeep', x: 8, y: 13, w: 4, h: 4 },
      { i: 'w-activity', x: 0, y: 17, w: 8, h: 5 },
      { i: 'w-quick', x: 8, y: 17, w: 4, h: 5 },
    ],
    sm: [
      { i: 'w-stat-monitors', x: 0, y: 0, w: 1, h: 2 },
      { i: 'w-stat-reports', x: 1, y: 0, w: 1, h: 2 },
      { i: 'w-stat-drift', x: 0, y: 2, w: 1, h: 2 },
      { i: 'w-stat-updates', x: 1, y: 2, w: 1, h: 2 },
      { i: 'w-host-rpi', x: 0, y: 4, w: 2, h: 6 },
      { i: 'w-host-opti', x: 0, y: 9, w: 2, h: 6 },
      { i: 'w-host-nn', x: 0, y: 14, w: 2, h: 6 },
      { i: 'w-containers', x: 0, y: 19, w: 2, h: 4 },
      { i: 'w-pihole', x: 0, y: 25, w: 2, h: 4 },
      { i: 'w-vpn', x: 0, y: 29, w: 2, h: 3 },
      { i: 'w-storage', x: 0, y: 32, w: 2, h: 4 },
      { i: 'w-network', x: 0, y: 36, w: 2, h: 4 },
      { i: 'w-upkeep', x: 0, y: 40, w: 2, h: 4 },
      { i: 'w-activity', x: 0, y: 44, w: 2, h: 5 },
      { i: 'w-quick', x: 0, y: 49, w: 2, h: 5 },
    ],
  },
};

const PRESETS = { home: HOME, dashboard: DASHBOARD };
const PROTECTED = Object.keys(PRESETS);

// A brand-new user board: empty grid, inherits global wallpaper/glass settings.
function blankBoard(slug, name) {
  return {
    slug, name,
    protected: false,
    wallpaper: null,
    glass: null,
    widgets: [],
    layouts: { lg: [], sm: [] },
  };
}

module.exports = { PRESETS, PROTECTED, blankBoard };
