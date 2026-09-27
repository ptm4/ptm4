// Shapes served by the Pertal backend (backend/lib/resources.js, actions.js, jobs.js).
export type Status = 'ok' | 'warn' | 'crit' | 'unknown' | 'offline';
export type Severity = 'ok' | 'warn' | 'crit';

export interface Reason { severity: Severity; text: string; source: string; at?: string | null }
export interface Fact { label: string; value: string | null; tone?: 'warn' | 'crit' }
export interface ActionRef { kind: string; label: string; icon: string; risky: boolean }

export interface Resource {
  id: string;
  type: 'host' | 'container';
  kind: 'host' | 'app' | 'bot' | 'infra';
  name: string;
  host: string;
  status: Status;
  status_text: string;
  state_text: string;
  online?: boolean | null;
  reasons: Reason[];
  facts: Fact[];
  metrics: null | {
    cpu_pct: number | null; mem_pct: number | null; load1: number | null; cores: number | null;
    temp_c: number | null; uptime_s: number | null; rx_bps: number | null; tx_bps: number | null;
    mem_total_bytes: number | null;
  };
  counts: null | { containers: number; running: number };
  state?: string;
  health?: string | null;
  links: Record<string, string>;
  sources: string[];
  updated_at: string | null;
  actions: ActionRef[];
}

export interface Issue {
  severity: Severity; resource_id: string | null; resource: string; host: string | null;
  text: string; details?: string[]; source: string; at: string | null;
}

export interface Summary {
  overall: Severity;
  hosts: { total: number; up: number; down: number; offline: number };
  containers: { total: number; running: number };
  issues: Issue[];
  counts: { crit: number; warn: number };
}

export interface SnapMeta {
  key: string; label: string; group: string | null; ok: boolean | null; error: string | null;
  fetched_at: string | null; age_ms: number | null; stale: boolean; interval_ms: number;
  stale_after_ms: number; failures: number; took_ms: number | null;
}

export type StepStatus = 'pending' | 'running' | 'ok' | 'failed' | 'skipped';
export interface JobStep {
  key: string; label: string; detail: string | null; status: StepStatus;
  started_at: string | null; finished_at: string | null; ms: number | null; output: string | null;
}
export interface Job {
  id: string; kind: string; title: string; host: string | null; target: string | null;
  actor: string; danger: boolean; resource: string | null;
  status: 'running' | 'ok' | 'failed' | 'interrupted';
  started_at: string; finished_at: string | null; error: string | null; steps: JobStep[];
}

export interface ActivityEntry {
  id: string; at: string; type: 'source' | 'container' | 'inventory' | 'job';
  severity: Severity; text?: string; host?: string | null; resource_id?: string | null;
  source?: string; job?: Job;
}
