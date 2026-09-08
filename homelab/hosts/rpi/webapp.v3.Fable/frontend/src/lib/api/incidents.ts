// Incidents — findings correlated by host + time window (backend/routes/incidents.js).
// Acking an incident acks its member findings in the same store the bell reads.
import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
import { get, post } from './client';
import type { Notification } from './types';
import type { ChangeEvent } from './fleet';

export type IncidentStatus = 'open' | 'muted' | 'acked';

export interface Incident {
  id: string;
  host: string | null;
  severity: 'crit' | 'warn' | 'info';
  title: string;
  count: number;
  open_count: number;
  sources: string[];
  first_seen: string | null;
  last_seen: string | null;
  status: IncidentStatus;
  muted_until: string | null;
  items: (Notification & { acked_at: string | null })[];
  changes: ChangeEvent[];
}

export interface IncidentsResp {
  incidents: Incident[];
  open: number;
  muted: number;
  acked: number;
  generated_at: string;
}

export const useIncidents = (all: () => boolean = () => false) => createQuery(() => ({
  queryKey: ['incidents', all()],
  queryFn: () => get<IncidentsResp>(`/api/incidents${all() ? '?all=1' : ''}`, 20_000),
  refetchInterval: 5 * 60_000,
  retry: 0,
}));

export function useIncidentActions() {
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ['incidents'] });
    qc.invalidateQueries({ queryKey: ['notifications'] });
  };
  const ack = createMutation(() => ({
    mutationFn: ({ id, acked = true }: { id: string; acked?: boolean }) => post(`/api/incidents/${id}/ack`, { acked }),
    onSuccess: done,
  }));
  const mute = createMutation(() => ({
    mutationFn: ({ id, days, clear }: { id: string; days?: number; clear?: boolean }) =>
      post(`/api/incidents/${id}/mute`, clear ? { clear: true } : { days: days ?? 7 }),
    onSuccess: done,
  }));
  return { ack, mute };
}
