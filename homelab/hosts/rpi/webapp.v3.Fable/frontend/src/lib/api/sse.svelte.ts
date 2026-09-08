// Server-sent events client — one EventSource per tab against /api/events. Each
// event either replaces a query's cached data outright (vitals, containers: the
// payload IS the read model) or invalidates it (activity, notifications, incidents:
// the payload is a delta, refetching is cheap). While the stream is healthy the
// polling queries back off; on any failure they resume their normal cadence, so a
// backend without this route (v2, or a proxy that swallows SSE) costs nothing but
// a few retries.
import { browser } from '$app/environment';
import type { QueryClient } from '@tanstack/svelte-query';

export type SseState = 'off' | 'connecting' | 'live' | 'degraded';

let state = $state<SseState>('off');
let lastEventAt = $state<number | null>(null);
let lastEvent = $state<string | null>(null);
let es: EventSource | null = null;
let failures = 0;
let everLive = false;
let retryTimer: number | null = null;

const RETRY_AFTER_GIVING_UP_MS = 5 * 60_000;

export const sse = {
  get state() { return state; },
  get live() { return state === 'live'; },
  get lastEventAt() { return lastEventAt; },
  get lastEvent() { return lastEvent; },
};

export function startSse(qc: QueryClient): () => void {
  if (!browser || es) return stopSse;
  open(qc);
  return stopSse;
}

function open(qc: QueryClient) {
  state = 'connecting';
  try {
    es = new EventSource('/api/events');
  } catch {
    state = 'off';
    return;
  }
  const mark = (name: string) => { lastEventAt = Date.now(); lastEvent = name; };

  es.addEventListener('hello', () => { state = 'live'; everLive = true; failures = 0; mark('hello'); });
  es.addEventListener('vitals', (e) => {
    try { qc.setQueryData(['vitals'], JSON.parse((e as MessageEvent).data)); mark('vitals'); } catch { /* malformed */ }
  });
  es.addEventListener('containers', (e) => {
    try { qc.setQueryData(['containers'], JSON.parse((e as MessageEvent).data)); mark('containers'); } catch { /* malformed */ }
  });
  es.addEventListener('activity', () => { qc.invalidateQueries({ queryKey: ['activity'] }); mark('activity'); });
  es.addEventListener('notifications', () => { qc.invalidateQueries({ queryKey: ['notifications'] }); mark('notifications'); });
  es.addEventListener('incidents', () => { qc.invalidateQueries({ queryKey: ['incidents'] }); mark('incidents'); });

  es.onerror = () => {
    // The browser reconnects on its own (retry: 5000). A backend that never says
    // hello — no /api/events at all — gets three tries, then we stop hammering it
    // and check back in five minutes.
    failures += 1;
    state = 'degraded';
    if (!everLive && failures >= 3) {
      es?.close();
      es = null;
      state = 'off';
      retryTimer = window.setTimeout(() => { retryTimer = null; open(qc); }, RETRY_AFTER_GIVING_UP_MS);
    }
  };
}

export function stopSse() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  es?.close();
  es = null;
  state = 'off';
}

// Poll cadence helper: the normal interval, or the relaxed one while the stream is live.
export const pollEvery = (normalMs: number, relaxedMs = 5 * 60_000) => (state === 'live' ? relaxedMs : normalMs);
