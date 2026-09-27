// Drawer / rail entries. `ready: false` marks v4 pages still being built — shown so the
// shape of the finished app is visible, but not clickable.
export interface NavItem { href: string; label: string; icon: string; ready: boolean }

export const NAV: NavItem[] = [
  { href: '/', label: 'Status', icon: 'activity', ready: true },
  { href: '/resources', label: 'Resources', icon: 'boxes', ready: true },
  { href: '/activity', label: 'Activity', icon: 'scroll-text', ready: true },
  { href: '/topology', label: 'Topology', icon: 'network', ready: false },
  { href: '/logs', label: 'Logs', icon: 'file-chart-column', ready: false },
  { href: '/downloads', label: 'Downloads', icon: 'download', ready: false },
  { href: '/requests', label: 'Requests', icon: 'inbox', ready: false },
  { href: '/streams', label: 'Streams', icon: 'radio', ready: false },
  { href: '/launchpad', label: 'Launchpad', icon: 'rocket', ready: false },
  { href: '/settings', label: 'Settings', icon: 'settings', ready: true },
];
