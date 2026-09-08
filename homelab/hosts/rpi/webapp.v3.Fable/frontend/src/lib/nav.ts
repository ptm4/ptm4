// The navigation model — one source for the rail, the command palette, the topbar
// title and the mobile menu. Ordered by how often each thing is reached for.
import type { Component } from 'svelte';
import {
  LayoutDashboard, Grid2x2, Waypoints, ListOrdered, TriangleAlert, SlidersHorizontal,
  Boxes, ShieldCheck, TrendingUp, FileText, Shield, ScrollText, Database, Terminal,
  Bot, Crosshair, BrainCircuit, Rocket, Network, Tv, ServerCog, Workflow, Settings,
  Server, Smartphone, Radio,
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
    { path: '/streams', label: 'Streams', icon: Radio, key: '2' },
    { path: '/launchpad', label: 'Launchpad', icon: Rocket, key: '3' },
    { path: '/feed', label: 'Feed', icon: ListOrdered },
    { path: '/incidents', label: 'Incidents', icon: TriangleAlert },
    { path: '/topology', label: 'Topology', icon: Waypoints },
  ]},
  { title: 'Control', items: [
    { path: '/cockpit', label: 'Control center', icon: SlidersHorizontal },
    { path: '/containers', label: 'Containers', icon: Boxes },
    { path: '/updates', label: 'Updates', icon: TrendingUp },
    { path: '/pihole', label: 'Pi-hole', icon: ShieldCheck },
    { path: '/trends', label: 'Trends', icon: TrendingUp },
    { path: '/reports', label: 'Reports', icon: FileText },
    { path: '/security', label: 'Security', icon: Shield },
    { path: '/logs', label: 'Logs', icon: ScrollText },
  ]},
  { title: 'Boards & data', items: [
    { path: '/b/home', label: 'Home board', icon: Grid2x2 },
    { path: '/b/dashboard', label: 'Dashboard', icon: Grid2x2 },
    { path: '/data', label: 'Data', icon: Database },
    { path: '/query', label: 'Query', icon: Terminal },
  ]},
  { title: 'Play', items: [
    { path: '/bots', label: 'Discord bots', icon: Bot },
    { path: '/leetify', label: 'CS2 / Leetify', icon: Crosshair },
    { path: '/llm', label: 'Local LLM', icon: BrainCircuit },
  ]},
  { title: 'Pages', items: [
    { path: '/architecture/', label: 'Architecture', icon: Network, external: true },
    { path: '/legacy/streams/', label: 'Streams (v1)', icon: Tv, external: true },
    { path: '/samba/', label: 'Samba', icon: ServerCog, external: true },
    { path: '/agentic/', label: 'Agentic', icon: Workflow, external: true },
    { path: '/agents/', label: 'Agents', icon: ServerCog, external: true },
    { path: '/notes/', label: 'Notes', icon: FileText, external: true },
  ]},
];

export const SETTINGS_ITEM: NavItem = { path: '/settings', label: 'Settings', icon: Settings };

// The hosts group is data-driven (from /api/hosts once it exists; until then this
// static list, which is also the fallback when the backend is unreachable).
export interface HostNav { name: string; label: string; role: string; ip: string; icon: Component; intermittent?: boolean }
export const HOSTS: HostNav[] = [
  { name: 'opti', label: 'opti', role: 'storage · control plane', ip: '192.168.1.11', icon: Server },
  { name: 'rpi', label: 'rpi', role: 'DNS · DHCP · web', ip: '192.168.1.10', icon: Server },
  { name: 'noblenumbat', label: 'noblenumbat', role: 'media', ip: '192.168.1.6', icon: Server },
  { name: 'android', label: 'android', role: 'local LLM', ip: '192.168.1.54', icon: Smartphone, intermittent: true },
];

const TITLES = new Map<string, string>();
for (const g of NAV) for (const i of g.items) TITLES.set(i.path, i.label);
TITLES.set('/settings', 'Settings');
TITLES.set('/links', 'Launchpad');

export function titleFor(pathname: string): string {
  if (TITLES.has(pathname)) return TITLES.get(pathname)!;
  if (pathname.startsWith('/b/')) return 'Board';
  if (pathname.startsWith('/host/')) return decodeURIComponent(pathname.slice(6));
  return "Pert's Pocket";
}
