// The live store: one EventSource to /api/events keeps every page current. Pages read
// from here and never poll. If the stream drops, the store says so (connected=false)
// and falls back to polling /api/state until it reconnects — and every value keeps
// showing its own age, so nothing silently goes stale.
import type { ActivityEntry, Job, Resource, SnapMeta, Summary } from './types';

class Live {
  resources = $state<Resource[]>([]);
  summary = $state<Summary | null>(null);
  snapshots = $state<Record<string, SnapMeta>>({});
  jobs = $state<Job[]>([]);
  activity = $state<ActivityEntry[]>([]);
  version = $state<string>('');
  builtAt = $state<string | null>(null);
  connected = $state(false);
  loaded = $state(false);
  error = $state<string | null>(null);
  lastMessageAt = $state<number | null>(null);
  now = $state(Date.now());

  #es: EventSource | null = null;
  #poll: ReturnType<typeof setInterval> | null = null;
  #started = false;

  byId = (id: string) => this.resources.find((r) => r.id === id) ?? null;

  start() {
    if (this.#started) return;
    this.#started = true;
    setInterval(() => {
      this.now = Date.now();
      // Watchdog: the server pings every 15s. Silence for 45s means the stream is dead
      // even if the socket looks open (a proxy can hold it after Pertal went away).
      if (this.connected && this.lastMessageAt && this.now - this.lastMessageAt > 45_000) {
        this.connected = false;
        if (!this.#poll) this.#poll = setInterval(() => this.#load(), 15_000);
        this.#connect();
      }
    }, 1000);
    this.#load();
    this.#connect();
  }

  async #load() {
    try {
      const res = await fetch('/api/state', { signal: AbortSignal.timeout(8000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const s = await res.json();
      this.#applyState(s);
      if (Array.isArray(s.activity)) this.activity = s.activity;
      this.error = null;
    } catch (e) {
      this.error = `Pertal is not answering (${(e as Error).message})`;
    }
  }

  #applyState(s: any) {
    this.resources = s.resources ?? [];
    this.summary = s.summary ?? null;
    if (s.snapshots) this.snapshots = s.snapshots;
    if (Array.isArray(s.jobs)) this.#mergeJobs(s.jobs);
    this.version = s.version ?? this.version;
    this.builtAt = s.built_at ?? null;
    this.loaded = true;
  }

  #mergeJobs(list: Job[]) {
    const byId = new Map(this.jobs.map((j) => [j.id, j]));
    for (const j of list) byId.set(j.id, j);
    this.jobs = [...byId.values()].sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, 50);
  }

  upsertJob(job: Job) {
    this.#mergeJobs([job]);
  }

  #retryMs = 2000;

  // Browsers only auto-retry an EventSource after a *network* drop. A non-200 answer
  // (nginx's 502 while Pertal restarts during a deploy) closes it for good — so a
  // closed stream is reopened here, with backoff, instead of leaving the page polling.
  #reconnectLater() {
    const wait = this.#retryMs;
    this.#retryMs = Math.min(this.#retryMs * 2, 30_000);
    setTimeout(() => this.#connect(), wait);
  }

  #connect() {
    this.#es?.close();
    const es = new EventSource('/api/events');
    this.#es = es;
    const on = (name: string, fn: (d: any) => void) =>
      es.addEventListener(name, (ev) => {
        this.lastMessageAt = Date.now();
        try { fn(JSON.parse((ev as MessageEvent).data)); } catch { /* ignore malformed */ }
      });

    es.onopen = () => {
      this.connected = true;
      this.lastMessageAt = Date.now();
      this.error = null;
      this.#retryMs = 2000;
      if (this.#poll) { clearInterval(this.#poll); this.#poll = null; }
    };
    es.onerror = () => {
      this.connected = false;
      // Meanwhile keep the page honest by polling.
      if (!this.#poll) this.#poll = setInterval(() => this.#load(), 15_000);
      if (es.readyState === EventSource.CLOSED && this.#es === es) this.#reconnectLater();
    };
    on('hello', (s) => this.#applyState(s));
    on('ping', () => {});
    on('resources', (d) => {
      this.resources = d.resources;
      this.summary = d.summary;
      this.builtAt = d.built_at;
    });
    on('snapshot', (m: SnapMeta) => (this.snapshots = { ...this.snapshots, [m.key]: m }));
    on('job', (j: Job) => this.upsertJob(j));
    on('activity', (a: ActivityEntry) => (this.activity = [a, ...this.activity].slice(0, 200)));
  }
}

export const live = new Live();

// Age of a snapshot right now, derived from fetched_at so it ticks without new events.
export function snapAge(m: SnapMeta | undefined, now: number): number | null {
  return m?.fetched_at ? now - Date.parse(m.fetched_at) : null;
}
