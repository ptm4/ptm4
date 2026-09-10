// Live container identity from Dozzle's own event stream (same-origin /dozzle).
//
// The arch-agent fragments carry no container IDs, but Dozzle's SSE feed does —
// its `containers-changed` events are the full list with id, state, health and
// started time. Subscribing while the Containers page is open gives us both the
// deep-link IDs (/dozzle/container/<id>) and live state changes for free.
import { useEffect, useState } from 'react';

export interface DozzleContainer {
  id: string;
  name: string;
  state: string;
  health?: string;
  startedAt?: string;
  host: string;          // dozzle's internal host id (a uuid) — not our host names
}

export function useDozzle(): { byName: Record<string, DozzleContainer>; live: boolean } {
  const [byName, setByName] = useState<Record<string, DozzleContainer>>({});
  const [live, setLive] = useState(false);

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource('/dozzle/api/events/stream');
    } catch {
      return; // dozzle absent — the page degrades to report data only
    }
    const onContainers = (e: MessageEvent) => {
      try {
        const list = JSON.parse(e.data) as DozzleContainer[];
        setLive(true);
        // Merge — dozzle may emit one event per docker host it watches.
        setByName((prev) => {
          const next = { ...prev };
          for (const c of list) next[c.name] = c;
          return next;
        });
      } catch { /* malformed frame — skip */ }
    };
    es.addEventListener('containers-changed', onContainers);
    es.onerror = () => setLive(false);
    return () => { es?.close(); };
  }, []);

  return { byName, live };
}
