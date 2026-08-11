// The widget SDK contract. A registry entry is everything the board engine needs
// to place, size, configure and render one widget type — so adding a feature to
// this dashboard means adding an entry here, not editing a page.
//
//   component  the renderer; receives { options }
//   defaults   initial grid size when the widget is added
//   min/max    resize bounds enforced by react-grid-layout
//   options    the configurable fields; drives the settings popover with no
//              per-widget form code
import type { ComponentType } from 'react';
import {
  ActivityWidget, ContainersWidget, FleetStatusWidget, HostVitalsWidget,
  MonitorsWidget, NetworkWidget, StatWidget, StorageWidget, UpkeepWidget,
} from './system';
import {
  AppGroupWidget, AppWidget, ClockWidget, PiholeWidget, QuickLinksWidget,
  VpnWidget, WeatherWidget,
} from './services';
import {
  BotsWidget, DownloadsWidget, LeetifyTrendWidget, NotificationsWidget, StreamsWidget,
} from './integrations';
import { ALL_LINKS, LINK_GROUPS } from '../lib/links';

export interface OptionDef {
  key: string;
  label: string;
  type: 'select' | 'number' | 'boolean' | 'text';
  choices?: { value: string; label: string }[];
  min?: number;
  max?: number;
}

export interface WidgetDef {
  type: string;
  label: string;
  description: string;
  component: ComponentType<{ options?: Record<string, unknown> }>;
  defaults: { w: number; h: number };
  min?: { w: number; h: number };
  options?: OptionDef[];
}

const HOSTS = [
  { value: 'rpi', label: 'rpi' },
  { value: 'opti', label: 'opti' },
  { value: 'noblenumbat', label: 'noblenumbat' },
];

export const WIDGETS: WidgetDef[] = [
  {
    type: 'host-vitals',
    label: 'Host vitals',
    description: 'CPU, memory, temp, network, every drive/pool, containers and live actions for one host — hover any metric for what contributes.',
    component: HostVitalsWidget,
    defaults: { w: 4, h: 6 },
    min: { w: 3, h: 5 },
    options: [
      { key: 'host', label: 'Host', type: 'select', choices: HOSTS },
      { key: 'range', label: 'Graph range', type: 'select', choices: [
        { value: '1h', label: 'Last hour' }, { value: '3h', label: '3 hours' },
        { value: '9h', label: '9 hours' }, { value: '24h', label: '24 hours' },
        { value: '48h', label: '48 hours' },
      ] },
    ],
  },
  {
    type: 'containers',
    label: 'Containers',
    description: 'Fleet container status — compact summary or the full table; the Containers page has the interactive version.',
    component: ContainersWidget,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 3 },
    options: [{ key: 'compact', label: 'Compact summary', type: 'boolean' }],
  },
  {
    type: 'activity',
    label: 'Activity feed',
    description: 'Findings, watchdog actions and backups from the latest reports.',
    component: ActivityWidget,
    defaults: { w: 8, h: 5 },
    min: { w: 3, h: 3 },
    options: [{ key: 'limit', label: 'Events', type: 'number', min: 5, max: 100 }],
  },
  {
    type: 'fleet-status',
    label: 'Fleet status',
    description: 'One-line rollup: worst runner status, monitors, agents, freshness.',
    component: FleetStatusWidget,
    defaults: { w: 5, h: 2 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'monitors',
    label: 'Monitors',
    description: 'Uptime Kuma monitor grid.',
    component: MonitorsWidget,
    defaults: { w: 4, h: 4 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'stat',
    label: 'Stat counter',
    description: 'A single number with a link: monitors, reports, drift or updates.',
    component: StatWidget,
    defaults: { w: 2, h: 2 },
    min: { w: 2, h: 2 },
    options: [{
      key: 'metric', label: 'Metric', type: 'select',
      choices: [
        { value: 'monitors', label: 'Monitors up' },
        { value: 'reports', label: 'Reports healthy' },
        { value: 'drift', label: 'Agent drift' },
        { value: 'updates', label: 'Image updates' },
      ],
    }],
  },
  {
    type: 'storage',
    label: 'Storage & disks',
    description: 'ZFS pool fill plus per-host OS disk usage.',
    component: StorageWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 3 },
  },
  {
    type: 'network',
    label: 'Network',
    description: 'Per-host reachability from the latest network report.',
    component: NetworkWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'upkeep',
    label: 'Services & upkeep',
    description: 'systemd timers across the fleet, last-fired times.',
    component: UpkeepWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'pihole',
    label: 'Pi-hole',
    description: 'Live block rate, query counts, and pause/resume.',
    component: PiholeWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 3 },
  },
  {
    type: 'vpn',
    label: 'VPN stack',
    description: 'Gluetun and the containers sharing its network namespace.',
    component: VpnWidget,
    defaults: { w: 4, h: 2 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'app',
    label: 'App tile',
    description: 'One service icon with a health dot.',
    component: AppWidget,
    defaults: { w: 1, h: 2 },
    min: { w: 1, h: 2 },
    options: [{
      key: 'label', label: 'Service', type: 'select',
      choices: ALL_LINKS.map((l) => ({ value: l.label, label: l.label })),
    }],
  },
  {
    type: 'app-group',
    label: 'App group',
    description: 'A whole bookmark group as an icon grid.',
    component: AppGroupWidget,
    defaults: { w: 6, h: 4 },
    min: { w: 2, h: 2 },
    options: [{
      key: 'group', label: 'Group', type: 'select',
      choices: LINK_GROUPS.map((g) => ({ value: g.group, label: g.group })),
    }],
  },
  {
    type: 'quick-links',
    label: 'Quick links',
    description: 'Compact list of favourite services.',
    component: QuickLinksWidget,
    defaults: { w: 4, h: 4 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'clock',
    label: 'Clock',
    description: 'Local time and date.',
    component: ClockWidget,
    defaults: { w: 3, h: 2 },
    min: { w: 2, h: 2 },
    options: [{ key: 'seconds', label: 'Show seconds', type: 'boolean' }],
  },
  {
    type: 'weather',
    label: 'Weather',
    description: "Today's forecast, from the weather bot's Open-Meteo data.",
    component: WeatherWidget,
    defaults: { w: 4, h: 2 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'notifications',
    label: 'Open findings',
    description: 'Unacknowledged findings from the doctor and security reports.',
    component: NotificationsWidget,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 2 },
    options: [{ key: 'limit', label: 'Show', type: 'number', min: 3, max: 20 }],
  },
  {
    type: 'bots',
    label: 'Discord bots',
    description: 'Per-bot enabled state, last result and next scheduled post.',
    component: BotsWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'streams',
    label: 'Streams',
    description: 'Active stream-station slots, with a jump to the player.',
    component: StreamsWidget,
    defaults: { w: 4, h: 2 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'leetify-trend',
    label: 'CS2 trend',
    description: 'Leetify dimensions plus a rating sparkline over recent runs.',
    component: LeetifyTrendWidget,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'downloads',
    label: 'Downloads',
    description: 'qBittorrent reachability behind the VPN namespace.',
    component: DownloadsWidget,
    defaults: { w: 3, h: 2 },
    min: { w: 2, h: 2 },
  },
];

export const WIDGET_BY_TYPE: Record<string, WidgetDef> =
  Object.fromEntries(WIDGETS.map((w) => [w.type, w]));
