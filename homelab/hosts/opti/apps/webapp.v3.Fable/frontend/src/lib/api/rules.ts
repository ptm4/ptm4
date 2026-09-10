// Alert rules (backend/routes/rules.js).
import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
import { get, post, put, del } from './client';

export type RuleKind = 'disk' | 'pool' | 'cpu' | 'mem' | 'temp' | 'load' | 'host_down' | 'container_down' | 'updates' | 'reboot_required' | 'stream_stalled';
export const NUMERIC_KINDS: RuleKind[] = ['disk', 'pool', 'cpu', 'mem', 'temp', 'load', 'updates', 'stream_stalled'];
export const KIND_LABEL: Record<RuleKind, string> = {
  disk: 'Root disk %', pool: 'ZFS pool %', cpu: 'CPU %', mem: 'Memory %', temp: 'Temperature °C', load: 'Load (1m)',
  host_down: 'Host unreachable', container_down: 'Container down', updates: 'Pending packages',
  reboot_required: 'Reboot required', stream_stalled: 'Stream slot stalled (s)',
};

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  kind: RuleKind;
  host?: string | null;
  container?: string | null;
  op?: '>' | '<';
  threshold?: number;
  for_min?: number;
  severity: 'warn' | 'critical';
}

export interface RuleHit {
  key: string; rule_id: string; rule: string; kind: RuleKind; severity: 'warn' | 'critical';
  host: string | null; value: number | null; message: string; since: string;
}

export interface RulesResp { rules: Rule[]; seeded: boolean; kinds: RuleKind[]; hits: RuleHit[]; evaluated_at: string | null }

export const useRules = () => createQuery(() => ({
  queryKey: ['rules'],
  queryFn: () => get<RulesResp>('/api/rules', 12_000),
  refetchInterval: 60_000,
  retry: 0,
}));

export function useRuleActions() {
  const qc = useQueryClient();
  const done = () => { qc.invalidateQueries({ queryKey: ['rules'] }); qc.invalidateQueries({ queryKey: ['incidents'] }); qc.invalidateQueries({ queryKey: ['notifications'] }); };
  const create = createMutation(() => ({ mutationFn: (r: Omit<Rule, 'id'>) => post<Rule>('/api/rules', r), onSuccess: done }));
  const update = createMutation(() => ({ mutationFn: ({ id, ...patch }: Partial<Rule> & { id: string }) => put<Rule>(`/api/rules/${id}`, patch), onSuccess: done }));
  const remove = createMutation(() => ({ mutationFn: (id: string) => del(`/api/rules/${id}`), onSuccess: done }));
  const reset = createMutation(() => ({ mutationFn: () => post('/api/rules/reset'), onSuccess: done }));
  const evaluate = createMutation(() => ({ mutationFn: () => post<{ hits: RuleHit[] }>('/api/rules/evaluate', undefined, 30_000), onSuccess: done }));
  return { create, update, remove, reset, evaluate };
}
