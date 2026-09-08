// Live container identity from Dozzle's own event stream (same-origin /dozzle).
//
// The arch-agent fragments carry no container IDs, but Dozzle's SSE feed does —
// its `containers-changed` events are the full list with id, state, health and
// started time. Subscribing while a page is open gives us both the deep-link IDs
// (/dozzle/container/<id>) and live state changes for free.
// Call during component initialisation; the subscription closes with the component.
import { onDestroy } from 'svelte';

export interface DozzleContainer {
  id: string;
  name: string;
  state: string;
  health?: string;
  startedAt?: string;
  host: string;          // dozzle's internal host id (a uuid) — not our host names
}

export function createDozzle() {
  let byName = $state<Record<string, DozzleContainer>>({});
  let live = $state(false);
  let es: EventSource | null = null;

  try {
    es = new EventSource('/dozzle/api/events/stream');
    es.addEventListener('containers-changed', (e: MessageEvent) => {
      try {
        const list = JSON.parse(e.data) as DozzleContainer[];
        live = true;
        // Merge — dozzle may emit one event per docker host it watches.
        const next = { ...byName };
        for (const c of list) next[c.name] = c;
        byName = next;
      } catch { /* malformed frame — skip */ }
    });
    es.onerror = () => { live = false; };
  } catch {
    es = null; // dozzle absent — the page degrades to report data only
  }

  onDestroy(() => { es?.close(); });

  return {
    get byName() { return byName; },
    get live() { return live; },
  };
}
