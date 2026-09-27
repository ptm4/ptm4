import type { ActivityEntry, Job, Resource } from './types';

export interface AppLink {
  label: string; url: string; icon: string; check?: string;
  reach: null | { up: boolean; status?: number; ms?: number; error?: string };
}
export interface LinkGroup { group: string; links: AppLink[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    signal: init?.signal ?? AbortSignal.timeout(10_000),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body?.error || `HTTP ${res.status}`);
  return body as T;
}

export const api = {
  state: () => request<any>('/api/state'),
  resource: (id: string) =>
    request<{ resource: Resource; children: Resource[]; jobs: Job[]; audit: Job[]; activity: ActivityEntry[] }>(
      `/api/resources/${encodeURIComponent(id)}`,
    ),
  activity: (limit = 150) => request<{ items: ActivityEntry[] }>(`/api/activity?limit=${limit}`),
  metrics: (host: string, metric: string, range: string) =>
    request<{ source: string; points: [number, number | null][] }>(
      `/api/metrics/${encodeURIComponent(host)}?metric=${metric}&range=${range}`,
      { signal: AbortSignal.timeout(15_000) },
    ),
  logs: (host: string, container: string, tail: number, since?: string) =>
    request<{ lines: { ts: string | null; text: string }[]; truncated: boolean }>(
      `/api/logs/${encodeURIComponent(host)}/${encodeURIComponent(container)}?tail=${tail}${since ? `&since=${since}` : ''}`,
      { signal: AbortSignal.timeout(15_000) },
    ),
  links: () => request<{ groups: LinkGroup[]; checked_at: string | null }>('/api/links'),
  reports: () => request<any>('/api/reports'),
  topology: () => request<any>('/api/topology'),
  // Starts a job and returns it immediately; progress arrives over SSE.
  action: (kind: string, resource: string, opts: { confirm?: boolean; params?: Record<string, unknown> } = {}) =>
    request<{ job: Job }>(`/api/actions/${encodeURIComponent(kind)}`, {
      method: 'POST',
      body: JSON.stringify({ resource, confirm: opts.confirm === true, params: opts.params ?? null }),
    }),
};
