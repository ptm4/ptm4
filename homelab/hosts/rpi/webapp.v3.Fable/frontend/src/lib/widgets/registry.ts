// The widget registry — one entry per widget type. Option schemas are the v2
// contract verbatim (they are what saved board documents carry), with `default`
// values added so a widget never has to guess.
import type { WidgetDef } from './sdk';
import HostVitals from './system/HostVitals.svelte';
import Containers from './system/Containers.svelte';
import Activity from './system/Activity.svelte';
import FleetStatus from './system/FleetStatus.svelte';
import Monitors from './system/Monitors.svelte';
import Stat from './system/Stat.svelte';
import Storage from './system/Storage.svelte';
import Network from './system/Network.svelte';
import Upkeep from './system/Upkeep.svelte';
import Pihole from './services/Pihole.svelte';
import Vpn from './services/Vpn.svelte';
import App from './services/App.svelte';
import AppGroup from './services/AppGroup.svelte';
import QuickLinks from './services/QuickLinks.svelte';
import Clock from './services/Clock.svelte';
import Weather from './services/Weather.svelte';
import Notifications from './integrations/Notifications.svelte';
import Bots from './integrations/Bots.svelte';
import Streams from './integrations/Streams.svelte';
import Cs2Matches from './integrations/Cs2Matches.svelte';
import LeetifyTrend from './integrations/LeetifyTrend.svelte';
import Downloads from './integrations/Downloads.svelte';
import PriceWatch from './integrations/PriceWatch.svelte';
import Changes from './hldb/Changes.svelte';
import LongTrends from './hldb/LongTrends.svelte';
import DbHealth from './hldb/DbHealth.svelte';
import { ALL_LINKS, LINK_GROUPS } from '$lib/links';

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
    component: HostVitals,
    defaults: { w: 4, h: 6 },
    min: { w: 3, h: 5 },
    options: [
      { key: 'host', label: 'Host', type: 'select', choices: HOSTS, default: 'rpi' },
      { key: 'range', label: 'Graph range', type: 'select', default: '3h', choices: [
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
    component: Containers,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 3 },
    options: [{ key: 'compact', label: 'Compact summary', type: 'boolean', default: true }],
  },
  {
    type: 'activity',
    label: 'Activity feed',
    description: 'Findings, watchdog actions and backups from the latest reports.',
    component: Activity,
    defaults: { w: 8, h: 5 },
    min: { w: 3, h: 3 },
    options: [{ key: 'limit', label: 'Events', type: 'number', min: 5, max: 100, default: 20 }],
  },
  {
    type: 'fleet-status',
    label: 'Fleet status',
    description: 'One-line rollup: worst runner status, monitors, agents, freshness.',
    component: FleetStatus,
    defaults: { w: 5, h: 2 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'monitors',
    label: 'Monitors',
    description: 'Uptime Kuma monitor grid.',
    component: Monitors,
    defaults: { w: 4, h: 4 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'stat',
    label: 'Stat counter',
    description: 'A single number with a link: monitors, reports, drift or updates.',
    component: Stat,
    defaults: { w: 2, h: 2 },
    min: { w: 2, h: 2 },
    options: [{
      key: 'metric', label: 'Metric', type: 'select', default: 'monitors',
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
    component: Storage,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 3 },
  },
  {
    type: 'network',
    label: 'Network',
    description: 'Per-host reachability from the latest network report.',
    component: Network,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'upkeep',
    label: 'Services & upkeep',
    description: 'systemd timers across the fleet, last-fired times.',
    component: Upkeep,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'pihole',
    label: 'Pi-hole',
    description: 'Live block rate, query counts, and pause/resume.',
    component: Pihole,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 3 },
  },
  {
    type: 'vpn',
    label: 'VPN stack',
    description: 'Gluetun and the containers sharing its network namespace.',
    component: Vpn,
    defaults: { w: 4, h: 2 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'app',
    label: 'App tile',
    description: 'One service icon with a health dot.',
    component: App,
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
    component: AppGroup,
    defaults: { w: 6, h: 4 },
    min: { w: 2, h: 2 },
    options: [{
      key: 'group', label: 'Group', type: 'select', default: 'Infrastructure',
      choices: LINK_GROUPS.map((g) => ({ value: g.group, label: g.group })),
    }],
  },
  {
    type: 'quick-links',
    label: 'Quick links',
    description: 'Compact list of favourite services.',
    component: QuickLinks,
    defaults: { w: 4, h: 4 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'clock',
    label: 'Clock',
    description: 'Local time and date.',
    component: Clock,
    defaults: { w: 3, h: 2 },
    min: { w: 2, h: 2 },
    options: [{ key: 'seconds', label: 'Show seconds', type: 'boolean', default: false }],
  },
  {
    type: 'weather',
    label: 'Weather',
    description: "Today's forecast, from the weather bot's Open-Meteo data.",
    component: Weather,
    defaults: { w: 4, h: 2 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'notifications',
    label: 'Open findings',
    description: 'Unacknowledged findings from the doctor and security reports.',
    component: Notifications,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 2 },
    options: [{ key: 'limit', label: 'Show', type: 'number', min: 3, max: 20, default: 6 }],
  },
  {
    type: 'bots',
    label: 'Discord bots',
    description: 'Per-bot enabled state, last result and next scheduled post.',
    component: Bots,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'streams',
    label: 'Streams',
    description: 'Active stream-station slots, with a jump to the player.',
    component: Streams,
    defaults: { w: 4, h: 2 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'cs2-matches',
    label: 'CS2 matches',
    description: "Today's HLTV slate — live scores, upcoming with stream links, results with map scores.",
    component: Cs2Matches,
    defaults: { w: 4, h: 5 },
    min: { w: 3, h: 3 },
    options: [
      { key: 'limit', label: 'Matches per section', type: 'number', min: 3, max: 20, default: 6 },
      { key: 'sections', label: 'Show', type: 'select', default: 'all', choices: [
        { value: 'all', label: 'Everything' },
        { value: 'upcoming', label: 'Live + upcoming' },
        { value: 'results', label: 'Results only' },
      ] },
    ],
  },
  {
    type: 'leetify-trend',
    label: 'CS2 trend',
    description: 'Leetify dimensions plus a rating sparkline over recent runs.',
    component: LeetifyTrend,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
  },
  {
    type: 'downloads',
    label: 'Downloads',
    description: 'qBittorrent reachability behind the VPN namespace.',
    component: Downloads,
    defaults: { w: 3, h: 2 },
    min: { w: 2, h: 2 },
  },
  {
    type: 'changes',
    label: 'What changed',
    description: 'Containers, mounts and services added, removed or changed across the fleet — from homelab.db, which keeps the history the nightly fragments overwrite.',
    component: Changes,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 2 },
    options: [
      { key: 'days', label: 'Window (days)', type: 'number', min: 1, max: 120, default: 14 },
      { key: 'host', label: 'Host', type: 'select', default: '', choices: [{ value: '', label: 'All hosts' }, ...HOSTS] },
    ],
  },
  {
    type: 'long-trends',
    label: 'Long-range trend',
    description: 'Months of a collector metric — disk, pool, memory, latency — well past the 48h the in-memory vitals rings hold.',
    component: LongTrends,
    defaults: { w: 4, h: 3 },
    min: { w: 3, h: 2 },
    options: [
      { key: 'metric', label: 'Metric', type: 'select', default: 'pool_used_pct', choices: [
        { value: 'pool_used_pct', label: 'ZFS pool used %' },
        { value: 'disk_used_pct', label: 'Root disk used %' },
        { value: 'mem_used_gib', label: 'Memory used GiB' },
        { value: 'pending_count', label: 'Pending updates' },
        { value: 'gateway_avg_ms', label: 'Gateway latency' },
        { value: 'internet_avg_ms', label: 'Internet latency' },
      ] },
      { key: 'days', label: 'Window (days)', type: 'number', min: 7, max: 400, default: 30 },
      { key: 'host', label: 'Host', type: 'select', default: '', choices: [{ value: '', label: 'All hosts' }, ...HOSTS] },
    ],
  },
  {
    type: 'price-watch',
    label: 'Price watch',
    description: 'PC-part prices for the opti rebuild — Newegg/eBay/Amazon, trend sparklines, green pill when an item hits its buy target.',
    component: PriceWatch,
    defaults: { w: 4, h: 4 },
    min: { w: 3, h: 2 },
    options: [
      { key: 'category', label: 'Category', type: 'select', default: '', choices: [
        { value: '', label: 'All parts' },
        { value: 'cpu', label: 'CPU' },
        { value: 'mobo', label: 'Motherboard' },
        { value: 'ram', label: 'RAM' },
        { value: 'psu', label: 'PSU' },
        { value: 'ssd', label: 'SSD' },
        { value: 'case', label: 'Case' },
      ] },
    ],
  },
  {
    type: 'db-health',
    label: 'Homelab DB',
    description: 'Whether every data feed is still feeding, how much is indexed, and how far the history reaches. Watches the thing that watches everything else.',
    component: DbHealth,
    defaults: { w: 3, h: 3 },
    min: { w: 2, h: 2 },
  },
];

export const WIDGET_BY_TYPE: Record<string, WidgetDef> =
  Object.fromEntries(WIDGETS.map((w) => [w.type, w]));
