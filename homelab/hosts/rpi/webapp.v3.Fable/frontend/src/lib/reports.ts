// Shared shapes for runner/security reports (the /api/runners and /api/reports
// families) plus the human, diagnosable message for a failed dispatcher call.

export interface ReportMeta {
  name: string;
  label: string;
  agent: string | null;
  status: string;
  summary: string;
  run_at: string | null;
  stale: boolean;
  has_alert?: boolean;
  enabled: boolean;
}

export interface Finding {
  severity?: string;
  message?: string;
}

export interface ReportDoc {
  status?: string;
  summary?: string;
  run_at?: string;
  findings?: Finding[];
  recommendations?: Finding[];
  log?: string;
  hosts?: { host?: string; summary?: string; metrics?: Record<string, unknown> }[];
  [key: string]: unknown;
}

export type ReportApiBase = 'runners' | 'reports';

// v1's dispatcherError — says which link in the chain broke.
export function dispatcherErrorMessage(status: number, detail: string): string {
  switch (status) {
    case 503: return `Dispatcher not configured — set DISPATCHER_URL in the webapp's .env on the Pi. ${detail}`;
    case 502: return `Backend reached, but could not connect to the dispatcher on opti (network/firewall, or wrong DISPATCHER_URL). ${detail}`;
    case 401: return `Dispatcher rejected the request (401) — HL_DISPATCH_TOKEN mismatch between the webapp and opti. ${detail}`;
    default: return `Request failed (HTTP ${status}). ${detail}`;
  }
}
