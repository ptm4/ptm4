// One query per read-model, each carrying the v1/v2 polling cadence. Components
// compose these freely — TanStack Query dedupes by key, so ten widgets reading
// /api/containers still make one request per interval, and background tabs pause.
// TanStack svelte-query v6: createQuery takes an options *accessor* (so options can
// be reactive) and returns a reactive result object — read `q.data`, `q.isError`.
// Each helper must be called during component initialisation (it reads context).
import { createQuery } from '@tanstack/svelte-query';
import { get } from './client';
import { pollEvery } from './sse.svelte';
import type {
  ActivityResp, AgentsResp, ContainersResp, HostReport, LinkcheckResp, NotificationsResp,
  PiholeSummary, RunnersResp, TimersResp, UptimeResp, VitalsRollup, VitalsSeries,
} from './types';

// The vitals rollup and the containers document are pushed over SSE when the
// stream is live (lib/api/sse.svelte.ts replaces the cached data), so their polls
// relax to a 5-minute safety net; everything else keeps its cadence.
export const useVitals = () => createQuery(() => ({
  queryKey: ['vitals'],
  queryFn: () => get<VitalsRollup>('/api/vitals', 8000),
  refetchInterval: pollEvery(30_000),
}));

export const useVitalsSeries = (host: () => string, points = 240) => createQuery(() => ({
  queryKey: ['vitals', host(), points],
  queryFn: () => get<VitalsSeries>(`/api/vitals/${host()}?points=${points}`, 8000),
  refetchInterval: 30_000,
}));

export type VitalsRange = '1h' | '3h' | '9h' | '24h' | '48h';
export const VITALS_RANGES: VitalsRange[] = ['1h', '3h', '9h', '24h', '48h'];

// Long ranges come back at 5-minute resolution; refetching every 30s would be
// churn for data that moves once per bucket.
export const useVitalsRange = (host: () => string, range: () => VitalsRange) => createQuery(() => ({
  queryKey: ['vitals-range', host(), range()],
  queryFn: () => get<VitalsSeries>(`/api/vitals/${host()}?range=${range()}`, 8000),
  refetchInterval: range() === '1h' || range() === '3h' ? 30_000 : 5 * 60_000,
}));

export const useContainers = () => createQuery(() => ({
  queryKey: ['containers'],
  queryFn: () => get<ContainersResp>('/api/containers', 15_000),
  refetchInterval: pollEvery(60_000),
}));

export const useActivity = (limit: number | (() => number) = 20) => createQuery(() => {
  const n = typeof limit === 'function' ? limit() : limit;
  return {
    queryKey: ['activity', n],
    queryFn: () => get<ActivityResp>(`/api/activity?limit=${n}`, 15_000),
    refetchInterval: 5 * 60_000,
  };
});

export const useTimers = () => createQuery(() => ({
  queryKey: ['timers'],
  queryFn: () => get<TimersResp>('/api/timers', 15_000),
  refetchInterval: 5 * 60_000,
}));

export const usePihole = () => createQuery(() => ({
  queryKey: ['pihole'],
  queryFn: () => get<PiholeSummary>('/api/pihole/summary', 12_000),
  refetchInterval: 60_000,
}));

export const useUptime = () => createQuery(() => ({
  queryKey: ['uptime'],
  queryFn: () => get<UptimeResp>('/api/uptime', 12_000),
  refetchInterval: 60_000,
}));

export const useAgents = () => createQuery(() => ({
  queryKey: ['agents'],
  queryFn: () => get<AgentsResp>('/api/agents', 20_000),
  refetchInterval: 60_000,
}));

export const useRunners = () => createQuery(() => ({
  queryKey: ['runners'],
  queryFn: () => get<RunnersResp>('/api/runners', 15_000),
  refetchInterval: 5 * 60_000,
}));

export const useLinkcheck = () => createQuery(() => ({
  queryKey: ['linkcheck'],
  queryFn: () => get<LinkcheckResp>('/api/linkcheck', 15_000),
  refetchInterval: 30_000,
}));

// The daily runner reports that back the storage/network tiles.
export const useRunnerReport = (name: () => string) => createQuery(() => ({
  queryKey: ['runner-report', name()],
  queryFn: () => get<HostReport>(`/api/runners/${name()}`, 15_000),
  refetchInterval: 5 * 60_000,
}));

export const useNotifications = (all: () => boolean = () => false) => createQuery(() => ({
  queryKey: ['notifications', all()],
  queryFn: () => get<NotificationsResp>(`/api/notifications${all() ? '?all=1' : ''}`, 15_000),
  refetchInterval: 5 * 60_000,
}));
