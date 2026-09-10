import { browser } from '$app/environment';
import { get } from './client';
import type { MonitorRollup } from './types';

let snapshot = $state<MonitorRollup | null>(null);
let histories = $state<Record<string, NonNullable<MonitorRollup['hosts'][string]['latest']>[]>>({ opti: [], rpi: [], noblenumbat: [] });
let state = $state<'off' | 'connecting' | 'live' | 'reconnecting'>('off');
let lastError = $state<string | null>(null);
let source: EventSource | null = null;
let fallback: number | null = null;
let visibility: (() => void) | null = null;

const HOSTS = ['opti', 'rpi', 'noblenumbat'];
const endpoint = () => `/api/monitor/events?hosts=${HOSTS.join(',')}&interval=2`;

async function poll() {
  try {
    accept(await get<MonitorRollup>(`/api/monitor/snapshot?hosts=${HOSTS.join(',')}&interval=2`, 1900));
    lastError = null;
  } catch (err) { lastError = err instanceof Error ? err.message : String(err); }
}

function accept(next: MonitorRollup) {
  snapshot = next;
  for (const [host, row] of Object.entries(next.hosts)) {
    const sample = row.latest;
    if (!sample) continue;
    const old = histories[host] || [];
    if (old.at(-1)?.measured_at === sample.measured_at) continue;
    histories = { ...histories, [host]: [...old, sample].slice(-450) };
  }
}

function open() {
  if (!browser || document.hidden || source) return;
  state = 'connecting';
  source = new EventSource(endpoint());
  source.addEventListener('snapshot', (event) => {
    try { accept(JSON.parse((event as MessageEvent).data)); state = 'live'; lastError = null; if (fallback != null) { clearInterval(fallback); fallback = null; } } catch { /* ignore malformed frame */ }
  });
  source.onerror = () => {
    state = 'reconnecting';
    if (fallback == null) { void poll(); fallback = window.setInterval(poll, 2000); }
  };
}

function close() {
  source?.close(); source = null;
  if (fallback != null) { clearInterval(fallback); fallback = null; }
}

export const monitorLive = {
  get snapshot() { return snapshot; }, get histories() { return histories; }, get state() { return state; }, get lastError() { return lastError; },
  start() {
    if (!browser) return;
    open();
    visibility = () => { if (document.hidden) { close(); state = 'off'; } else open(); };
    document.addEventListener('visibilitychange', visibility);
  },
  stop() { close(); if (visibility) document.removeEventListener('visibilitychange', visibility); visibility = null; state = 'off'; },
};
