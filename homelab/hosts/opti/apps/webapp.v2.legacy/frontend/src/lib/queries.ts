// One hook per read-model, each carrying the v1 polling cadence. Widgets compose
// these freely — TanStack Query dedupes, so ten widgets reading /api/containers
// still make one request per interval, and background tabs pause automatically.
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import type {
  ActivityResp, AgentsResp, ContainersResp, HostReport, LinkcheckResp,
  PiholeSummary, RunnersResp, TimersResp, UptimeResp, VitalsRollup, VitalsSeries,
} from './api-types';

export const useVitals = () => useQuery({
  queryKey: ['vitals'],
  queryFn: () => get<VitalsRollup>('/api/vitals', 8000),
  refetchInterval: 30_000,
});

export const useVitalsSeries = (host: string, points = 240) => useQuery({
  queryKey: ['vitals', host, points],
  queryFn: () => get<VitalsSeries>(`/api/vitals/${host}?points=${points}`, 8000),
  refetchInterval: 30_000,
});

export type VitalsRange = '1h' | '3h' | '9h' | '24h' | '48h';
export const VITALS_RANGES: VitalsRange[] = ['1h', '3h', '9h', '24h', '48h'];

// Long ranges come back at 5-minute resolution; refetching every 30s would be
// churn for data that moves once per bucket.
export const useVitalsRange = (host: string, range: VitalsRange) => useQuery({
  queryKey: ['vitals-range', host, range],
  queryFn: () => get<VitalsSeries>(`/api/vitals/${host}?range=${range}`, 8000),
  refetchInterval: range === '1h' || range === '3h' ? 30_000 : 5 * 60_000,
});

export const useContainers = () => useQuery({
  queryKey: ['containers'],
  queryFn: () => get<ContainersResp>('/api/containers', 15_000),
  refetchInterval: 60_000,
});

export const useActivity = (limit = 20) => useQuery({
  queryKey: ['activity', limit],
  queryFn: () => get<ActivityResp>(`/api/activity?limit=${limit}`, 15_000),
  refetchInterval: 5 * 60_000,
});

export const useTimers = () => useQuery({
  queryKey: ['timers'],
  queryFn: () => get<TimersResp>('/api/timers', 15_000),
  refetchInterval: 5 * 60_000,
});

export const usePihole = () => useQuery({
  queryKey: ['pihole'],
  queryFn: () => get<PiholeSummary>('/api/pihole/summary', 12_000),
  refetchInterval: 60_000,
});

export const useUptime = () => useQuery({
  queryKey: ['uptime'],
  queryFn: () => get<UptimeResp>('/api/uptime', 12_000),
  refetchInterval: 60_000,
});

export const useAgents = () => useQuery({
  queryKey: ['agents'],
  queryFn: () => get<AgentsResp>('/api/agents', 20_000),
  refetchInterval: 60_000,
});

export const useRunners = () => useQuery({
  queryKey: ['runners'],
  queryFn: () => get<RunnersResp>('/api/runners', 15_000),
  refetchInterval: 5 * 60_000,
});

export const useLinkcheck = () => useQuery({
  queryKey: ['linkcheck'],
  queryFn: () => get<LinkcheckResp>('/api/linkcheck', 15_000),
  refetchInterval: 30_000,
});

// The daily runner reports that back the storage/network tiles.
export const useRunnerReport = (name: string) => useQuery({
  queryKey: ['runner-report', name],
  queryFn: () => get<HostReport>(`/api/runners/${name}`, 15_000),
  refetchInterval: 5 * 60_000,
});
