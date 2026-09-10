// Fleet-level read models for the topology map and the per-host pages. /api/hosts is
// a v3 route: when the backend is v2 (the dev proxy against the live rpi, or a
// not-yet-upgraded deploy) it 404s, and everything here falls back to the static
// host table so the map still draws from vitals + containers alone.
import { createQuery } from '@tanstack/svelte-query';
import { get } from './client';
import { HOSTS } from '$lib/nav';
import { HOST_ROLES } from '$lib/impact';
import type { VitalsSample } from './types';

export interface FleetHost {
  name: string;
  label: string;
  ip: string;
  role: string;
  os?: string;
  kind?: 'server' | 'phone' | 'workstation';
  intermittent: boolean;
  agent: boolean;
  agent_base?: string | null;
  agent_version?: string | null;
  spof: Spof | null;
  vitals: Pick<VitalsSample, 't' | 'load1' | 'cpu_pct' | 'mem_pct' | 'temp_c' | 'uptime_s'> | null;
  vitals_error?: string | null;
  containers?: number;
  containers_up?: number;
  fragment_at?: string | null;
}

// What kind of single point of failure a host is, if any. 'storage+apps' is opti
// since the 2026-09-10 app-tier move: one box, two distinct blast radii.
export type Spof = 'storage' | 'storage+apps' | 'dns';

export interface Dependency { from: string; to: string; why: string }

export interface HostsResp {
  hosts: FleetHost[];
  depends: Dependency[];
  gateway: { ip: string; label: string; model?: string };
  generated_at?: string;
}

// Mirrors backend/routes/hosts.js. Keep the two in step — this copy is only the
// offline fallback, and a fallback that disagrees with the server is worse than none.
const SPOF: Record<string, Spof> = { opti: 'storage+apps', rpi: 'dns' };
const STATIC_DEPENDS: Dependency[] = [
  { from: 'noblenumbat', to: 'opti', why: 'mounts the pool over CIFS' },
  { from: 'rpi', to: 'opti', why: 'reads reports and agent logs over CIFS' },
  { from: 'opti', to: 'rpi', why: 'DNS' },
  { from: 'noblenumbat', to: 'rpi', why: 'DNS' },
  { from: 'android', to: 'rpi', why: 'DNS' },
  { from: 'tux', to: 'rpi', why: 'DNS' },
];

export const FALLBACK_FLEET: HostsResp = {
  hosts: [
    ...HOSTS.map((h) => ({
      name: h.name, label: h.label, ip: h.ip, role: HOST_ROLES[h.name] ?? h.role,
      intermittent: !!h.intermittent, agent: !h.intermittent, spof: SPOF[h.name] ?? null, vitals: null,
      kind: (h.name === 'android' ? 'phone' : 'server') as FleetHost['kind'],
    })),
    { name: 'tux', label: 'tux', ip: '192.168.1.3', role: 'workstation', intermittent: true, agent: false, spof: null, vitals: null, kind: 'workstation' },
  ],
  depends: STATIC_DEPENDS,
  gateway: { ip: '192.168.1.1', label: 'archer', model: 'TP-Link Archer BE3600' },
};

export const useHosts = () => createQuery(() => ({
  queryKey: ['hosts'],
  queryFn: () => get<HostsResp>('/api/hosts', 8000),
  refetchInterval: 60_000,
  retry: 0,
}));

export interface ArchLiveHost {
  host: string;
  status?: string;
  summary?: string;
  uptime?: string | number | null;
  disk_used_pct?: number | null;
  doctor_status?: string;
  containers?: { name: string; status: string | null }[];
  pool?: { used_pct?: number; pool_name?: string; size_gb?: number; free_gb?: number } | null;
  pending_updates?: number | null;
}
export interface ArchLiveResp {
  hosts: Record<string, ArchLiveHost>;
  run_at: string | null;
  doctor_summary: string | null;
  synced_at: string;
}

export const useArchLive = () => createQuery(() => ({
  queryKey: ['arch-live'],
  queryFn: () => get<ArchLiveResp>('/api/architecture/live', 12_000),
  refetchInterval: 5 * 60_000,
}));

export interface UpdateImage {
  host: string; container: string; image: string | null;
  current_digest: string | null; available_digest: string | null;
  compose_project: string | null; running: boolean; self: boolean;
}
export interface UpdatePackages {
  host: string; pending: number; security: number; reboot_required: boolean; reboot_pkgs: string[] | string | null;
}
export interface FleetUpdatesResp {
  images: UpdateImage[];
  packages: UpdatePackages[];
  counts: { images: number; packages: number; security: number; reboots: number };
  collected_at: string | null;
}

export const useUpdates = () => createQuery(() => ({
  queryKey: ['updates'],
  queryFn: () => get<FleetUpdatesResp>('/api/updates', 15_000),
  refetchInterval: 5 * 60_000,
}));

export interface ChangeEvent {
  at: string; host: string; kind: string; key: string;
  change: 'added' | 'removed' | 'changed';
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}
export interface ChangesResp { events?: ChangeEvent[]; event_count?: number; days?: number }

export const useChanges = (host: () => string, days: () => number) => createQuery(() => ({
  queryKey: ['hldb-changes', days(), host()],
  queryFn: () => get<ChangesResp>(`/api/hldb/changes?days=${days()}${host() ? `&host=${host()}` : ''}`, 20_000),
  refetchInterval: 10 * 60_000,
  retry: 0,
}));

// Health tone for a host from what the fleet already knows.
export type HostTone = 'ok' | 'warn' | 'crit' | 'off';
export function hostTone(h: FleetHost, opts: { updates?: number; vitalsError?: string | null; hasVitals?: boolean }): HostTone {
  const has = opts.hasVitals ?? !!h.vitals;
  const err = opts.vitalsError ?? h.vitals_error ?? null;
  if (!h.agent) return has ? 'ok' : 'off';
  if (!has || err) return h.intermittent ? 'off' : 'crit';
  if ((opts.updates ?? 0) > 0) return 'warn';
  return 'ok';
}
