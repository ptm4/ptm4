// Settings → Maintenance (backend/routes/maintenance.js). Host state is read live from
// each hl-arch-agent; toggles run as audited jobs (kind 'autoupdate').
import { createQuery } from '@tanstack/svelte-query';
import { get, post } from './client';
import type { Job } from '$lib/stores/jobs.svelte';

export interface AutoupdateHost {
  host: string;
  reachable: boolean;
  error: string | null;
  supported: boolean;
  mode: 'enabled' | 'disabled' | null;
  guaranteed: boolean | null;
  will_run_unattended: boolean | null;
  installed: boolean | null;
  script_honors_flag: boolean | null;
  flag: { by: string | null; at: string | null; reason: string | null } | null;
  timer: { unit_file_state: string | null; active: string | null; next_run: string | null; last_trigger: string | null } | null;
  last_run: { active: string | null; result: string | null; started_at: string | null; finished_at: string | null } | null;
  problems: string[];
  checked_at: string;
}

export interface AutoupdateResp {
  hosts: AutoupdateHost[];
  summary: { total: number; enabled: number; disabled: number; unknown: number };
  checked_at: string;
}

export interface AuditEntry extends Job { summary?: string }

export const AUTOUPDATE_KEY = ['maintenance', 'autoupdate'];
export const AUTOUPDATE_AUDIT_KEY = ['maintenance', 'autoupdate', 'audit'];

export const useAutoupdate = () => createQuery(() => ({
  queryKey: AUTOUPDATE_KEY,
  queryFn: () => get<AutoupdateResp>('/api/maintenance/autoupdate', 15_000),
  refetchInterval: 60_000,
  retry: 0,
}));

export const useAutoupdateAudit = () => createQuery(() => ({
  queryKey: AUTOUPDATE_AUDIT_KEY,
  queryFn: () => get<{ entries: AuditEntry[] }>('/api/jobs/audit?kind=autoupdate&days=365&limit=100', 10_000),
  refetchInterval: 120_000,
  retry: 0,
}));

export const setAutoupdate = (host: string, enabled: boolean, reason: string) =>
  post<{ ok: boolean; job: Job | null; state?: AutoupdateHost; error?: string }>(
    `/api/maintenance/autoupdate/${encodeURIComponent(host)}`, { enabled, reason }, 60_000);
