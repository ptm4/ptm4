// Drawer / rail entries, in the order they appear. `ready: false` marks v4 pages still
// being built — shown (last, greyed) so the shape of the finished app is visible.
// The Launchpad is not here: it lives behind the Apps button in the top bar.
export interface NavItem { href: string; label: string; icon: string; ready: boolean }

export const NAV: NavItem[] = [
  { href: '/', label: 'Status', icon: 'gauge', ready: true },
  { href: '/resources', label: 'Resources', icon: 'boxes', ready: true },
  { href: '/topology', label: 'Topology', icon: 'network', ready: true },
  { href: '/activity', label: 'Activity', icon: 'activity', ready: true },
  { href: '/logs', label: 'Logs', icon: 'scroll-text', ready: true },
  { href: '/streams', label: 'Streams', icon: 'radio', ready: true },
  { href: '/downloads', label: 'Downloads', icon: 'download', ready: true },
  { href: '/requests', label: 'Requests', icon: 'inbox', ready: true },
  { href: '/reports', label: 'Reports', icon: 'file-chart-column', ready: true },
  { href: '/settings', label: 'Settings', icon: 'settings', ready: true },
];

// Pages reachable by search but not listed in the rail.
export const EXTRA_PAGES = [{ href: '/launchpad', label: 'Launchpad (all apps)' }];
