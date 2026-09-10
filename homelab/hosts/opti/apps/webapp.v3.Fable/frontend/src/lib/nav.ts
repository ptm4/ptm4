// The navigation model — one source for the rail, the command palette, the topbar
// title and the mobile menu.
//
// Consolidated 2026-09-10, from 26 entries to 13. What went and where:
//   Home board, Dashboard (widget boards)  → deleted; Dashboard is now the monitor
//   Containers, Updates, Pi-hole, Logs     → tabs on /cockpit
//   Security                               → /reports?filter=security
//   Incidents                              → /feed?view=incidents
//   Query                                  → /data?tab=query
//   Streams (v1), Agents, Architecture     → moved off the rail into Settings
// Added 2026-09-10: Docs (/docs), reading homelab-db's docs table.
// The rule for earning a rail entry: it is a place you go, not a view of somewhere
// you already are.
import type { Component } from 'svelte';
import {
  LayoutDashboard, Activity, Waypoints, SlidersHorizontal, Radio, Rocket,
  FileText, TrendingUp, Database, Bot, Crosshair, BrainCircuit, Settings, BookOpen, ScrollText,
  Server, Smartphone, Gauge,
} from '@lucide/svelte';

export interface NavItem {
  path: string;
  label: string;
  icon: Component;
  /** keyboard hint shown in the rail */
  key?: string;
  /** full page load (legacy standalone page) rather than a client route */
  external?: boolean;
}

export interface NavGroup { title: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  { title: 'Now', items: [
    { path: '/', label: 'Home', icon: LayoutDashboard, key: '1' },
    { path: '/dashboard', label: 'Monitor', icon: Gauge, key: '2' },
    { path: '/streams', label: 'Streams', icon: Radio, key: '3' },
    { path: '/launchpad', label: 'Launchpad', icon: Rocket, key: '4' },
  ]},
  { title: 'Operate', items: [
    { path: '/cockpit', label: 'Control center', icon: SlidersHorizontal },
    { path: '/feed', label: 'Activity', icon: Activity },
    // Logs came back out of the Cockpit tabs on Peter's ask (2026-09-10): mid-incident
    // you go TO the logs, so they pass the "place you go" test after all. The Cockpit
    // tab remains as a second door to the same panel.
    { path: '/logs', label: 'Logs', icon: ScrollText },
    { path: '/topology', label: 'Topology', icon: Waypoints },
    { path: '/reports', label: 'Reports', icon: FileText },
  ]},
  { title: 'Data', items: [
    { path: '/trends', label: 'Metrics', icon: TrendingUp },
    // Docs earns a rail slot rather than living under Settings because it is now the
    // only documentation there is. The repo markdown is a pointer to it, not a copy.
    { path: '/docs', label: 'Docs', icon: BookOpen },
    { path: '/data', label: 'Database', icon: Database },
  ]},
  { title: 'Play', items: [
    { path: '/bots', label: 'Discord bots', icon: Bot },
    { path: '/leetify', label: 'CS2 / Leetify', icon: Crosshair },
    { path: '/llm', label: 'Local LLM', icon: BrainCircuit },
  ]},
];

export const SETTINGS_ITEM: NavItem = { path: '/settings', label: 'Settings', icon: Settings };

/** Standalone pages the dashboard serves but does not own. Reachable from Settings
 *  and the command palette; they no longer take up a rail slot each. */
export const LEGACY_PAGES: NavItem[] = [
  { path: '/architecture/', label: 'Architecture map', icon: Waypoints, external: true },
  { path: '/agents/', label: 'Agents', icon: Server, external: true },
  { path: '/samba/', label: 'Samba', icon: Server, external: true },
  { path: '/agentic/', label: 'Agentic workspace', icon: FileText, external: true },
  { path: '/notes/', label: 'Notes', icon: FileText, external: true },
  { path: '/legacy/streams/', label: 'Streams (v1)', icon: Radio, external: true },
  { path: '/legacy/', label: 'Legacy UI (v1)', icon: LayoutDashboard, external: true },
];

// The hosts group is data-driven (from /api/hosts once it exists; until then this
// static list, which is also the fallback when the backend is unreachable).
export interface HostNav { name: string; label: string; role: string; ip: string; icon: Component; intermittent?: boolean }
export const HOSTS: HostNav[] = [
  { name: 'opti', label: 'opti', role: 'storage · control plane · apps', ip: '192.168.1.11', icon: Server },
  { name: 'rpi', label: 'rpi', role: 'DNS', ip: '192.168.1.10', icon: Server },
  { name: 'noblenumbat', label: 'noblenumbat', role: 'media', ip: '192.168.1.6', icon: Server },
  { name: 'android', label: 'android', role: 'local LLM', ip: '192.168.1.54', icon: Smartphone, intermittent: true },
];

const TITLES = new Map<string, string>();
for (const g of NAV) for (const i of g.items) TITLES.set(i.path, i.label);
TITLES.set('/settings', 'Settings');
TITLES.set('/links', 'Launchpad');

/** Sub-views that live inside a page, so the topbar can name where you actually are. */
const SUBTITLES: Record<string, Record<string, string>> = {
  '/cockpit': { containers: 'Containers', updates: 'Updates', pihole: 'Pi-hole', logs: 'Logs' },
  '/feed': { incidents: 'Incidents', stream: 'Stream', audit: 'Audit' },
  '/data': { query: 'Query' },
  '/reports': { security: 'Security', collectors: 'Collectors' },
};

export function titleFor(pathname: string, search?: URLSearchParams): string {
  const sub = SUBTITLES[pathname];
  if (sub && search) {
    for (const key of ['tab', 'view', 'filter']) {
      const v = search.get(key);
      if (v && sub[v]) return `${TITLES.get(pathname) ?? pathname} · ${sub[v]}`;
    }
  }
  if (TITLES.has(pathname)) return TITLES.get(pathname)!;
  if (pathname.startsWith('/host/')) return decodeURIComponent(pathname.slice(6));
  return "Pert's Pocket";
}
