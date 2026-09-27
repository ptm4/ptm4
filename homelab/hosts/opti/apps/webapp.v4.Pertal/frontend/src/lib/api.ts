import type { ActivityEntry, Job, Resource } from './types';

export interface AppLink {
  label: string; url: string; icon: string; check?: string;
  reach: null | { up: boolean; status?: number; ms?: number; error?: string };
}
export interface LinkGroup { group: string; links: AppLink[] }

// Video is same-origin: nginx (prod) / vite (dev) proxy /hls to stream-station.
export const hlsUrl = (slot: number) => `/hls/slot${slot}/index.m3u8`;

export interface StreamSlot {
  slot: number; state: 'idle' | 'starting' | 'running' | 'ended' | 'error' | string;
  platform: string | null; channel: string | null; url: string | null; error?: string | null; uptime_s?: number | null;
}
export interface StreamChannel {
  platform: string; channel: string; label?: string; group: string; group_label: string;
  org: string | null; watching_slot: number | null; listed_matches: number;
}
export interface StreamMatch {
  id: string; url: string; event: string; stars: number; team1: string; team2: string;
  score1: number | null; score2: number | null; start_unix: number | null; status: string;
  rank1: number | null; rank2: number | null; top20: boolean; premier: boolean;
  channel: { platform: string; channel: string; label: string } | null; watching_slot: number | null;
}
export interface StreamGuide {
  station: { ok: boolean; version?: string; slots: StreamSlot[] };
  channels: StreamChannel[]; matches: StreamMatch[];
  vrs: { known: boolean; counted: number };
  hltv: { ok: boolean; stale: boolean; fetched_at: number | null; error: string | null };
}

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
  downloads: {
    get: () => request<any>('/api/downloads'),
    // multipart: .torrent files and/or magnet links. No JSON header — the browser sets the boundary.
    add: async (files: File[], urls: string) => {
      const form = new FormData();
      for (const f of files) form.append('torrents', f, f.name);
      if (urls.trim()) form.append('urls', urls.trim());
      const res = await fetch('/api/downloads/add', { method: 'POST', body: form, signal: AbortSignal.timeout(30_000) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError(res.status, body?.error || `HTTP ${res.status}`);
      return body as { job: Job };
    },
    op: (hash: string, op: 'pause' | 'resume' | 'delete', opts: { confirm?: boolean; deleteFiles?: boolean } = {}) =>
      request<{ job: Job }>(`/api/downloads/${hash}/${op}`, { method: 'POST', body: JSON.stringify(opts) }),
  },
  streams: {
    guide: () => request<StreamGuide>('/api/streams/guide'),
    watch: (body: { platform?: string; channel?: string; url?: string; slot?: number }) =>
      request<{ ok: boolean; slot: number; reused?: boolean }>('/api/streams/watch', { method: 'POST', body: JSON.stringify(body), signal: AbortSignal.timeout(20_000) }),
    stop: (slot: number) => request('/api/streams/stop', { method: 'POST', body: JSON.stringify({ slot }) }),
    keepalive: (slots: number[]) => request('/api/streams/keepalive', { method: 'POST', body: JSON.stringify({ slots }) }).catch(() => {}),
  },
  // Starts a job and returns it immediately; progress arrives over SSE.
  action: (kind: string, resource: string, opts: { confirm?: boolean; params?: Record<string, unknown> } = {}) =>
    request<{ job: Job }>(`/api/actions/${encodeURIComponent(kind)}`, {
      method: 'POST',
      body: JSON.stringify({ resource, confirm: opts.confirm === true, params: opts.params ?? null }),
    }),
};
