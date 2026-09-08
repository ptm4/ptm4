// Shared vocabulary for the trends explorer — metric/host tables, colour
// assignment and formatting helpers. Kept local to this route (not $lib)
// since nothing outside /trends needs it.
import { fmtBytesPerSec } from '$lib/format';

export type MetricKey = 'cpu_pct' | 'mem_pct' | 'temp_c' | 'load1' | 'rx_bps' | 'tx_bps';

export const VITALS_METRICS: { key: MetricKey; label: string; unit: string; percent: boolean }[] = [
  { key: 'cpu_pct', label: 'CPU', unit: '%', percent: true },
  { key: 'mem_pct', label: 'Memory', unit: '%', percent: true },
  { key: 'temp_c', label: 'Temperature', unit: '°C', percent: false },
  { key: 'load1', label: 'Load (1m)', unit: '', percent: false },
  { key: 'rx_bps', label: 'Network in', unit: '/s', percent: false },
  { key: 'tx_bps', label: 'Network out', unit: '/s', percent: false },
];

export const HOSTS = ['rpi', 'opti', 'noblenumbat'] as const;
export type HostName = (typeof HOSTS)[number];

// One categorical colour per host, drawn from the shared chart palette so a
// host means the same colour everywhere on this page.
const HOST_COLOR: Record<string, string> = {
  rpi: 'var(--c-network)',
  opti: 'var(--c-storage)',
  noblenumbat: 'var(--c-media)',
};
const HOST_COLOR_FALLBACK = ['var(--c-apps)', 'var(--c-aqua)'];
export function colorForHost(host: string): string {
  if (HOST_COLOR[host]) return HOST_COLOR[host];
  const idx = Math.abs([...host].reduce((a, c) => a + c.charCodeAt(0), 0));
  return HOST_COLOR_FALLBACK[idx % HOST_COLOR_FALLBACK.length];
}

export function fmtVitals(metric: MetricKey, v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  if (metric.endsWith('_bps')) return fmtBytesPerSec(v);
  if (metric === 'temp_c') return `${Math.round(v * 10) / 10}°C`;
  if (metric.endsWith('_pct')) return `${Math.round(v * 10) / 10}%`;
  return `${Math.round(v * 100) / 100}`;
}

// Signed variant for deltas — same rounding, an explicit +/− prefix.
export function fmtDelta(metric: MetricKey, d: number | null | undefined): string {
  if (d == null || Number.isNaN(d)) return '—';
  if (Math.abs(d) < (metric.endsWith('_bps') ? 1 : 0.05)) return `±${fmtVitals(metric, 0)}`;
  const sign = d > 0 ? '+' : '−';
  return `${sign}${fmtVitals(metric, Math.abs(d))}`;
}

export interface HldbMetricMeta { key: string; label: string; unit: string; percent: boolean }

export const HLDB_METRICS: HldbMetricMeta[] = [
  { key: 'pool_used_pct', label: 'ZFS pool used', unit: '%', percent: true },
  { key: 'disk_used_pct', label: 'Root disk used', unit: '%', percent: true },
  { key: 'mem_used_gib', label: 'Memory used', unit: ' GiB', percent: false },
  { key: 'pending_count', label: 'Pending updates', unit: '', percent: false },
  { key: 'gateway_avg_ms', label: 'Gateway latency', unit: ' ms', percent: false },
  { key: 'internet_avg_ms', label: 'Internet latency', unit: ' ms', percent: false },
];

export const LR_DAYS = [7, 30, 90, 365] as const;

export function fmtHldb(unit: string, v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${Math.round(v * 10) / 10}${unit}`;
}

// ── time-series alignment ───────────────────────────────────────────────────
// Every host is queried independently, so their sample timestamps don't line
// up perfectly. We union all timestamps into one shared axis and look each
// host's value up by exact timestamp — a host missing a sample at that instant
// gets a real gap (null), never an interpolated guess.
export interface SeriesPoint { t: number; v: number | null }

export function alignSeries(
  hostPoints: { host: string; points: SeriesPoint[] }[],
): { times: number[]; byHost: Record<string, (number | null)[]> } {
  const timeSet = new Set<number>();
  for (const h of hostPoints) for (const p of h.points) timeSet.add(p.t);
  const times = [...timeSet].sort((a, b) => a - b);
  const byHost: Record<string, (number | null)[]> = {};
  for (const h of hostPoints) {
    const map = new Map(h.points.map((p) => [p.t, p.v] as const));
    byHost[h.host] = times.map((t) => (map.has(t) ? (map.get(t) ?? null) : null));
  }
  return { times, byHost };
}
