// Joins the fleet read models into what the map draws: one HostView per host with a
// health tone, a stat line and its container dots. Shared by the Topology page and
// the Home hero so both see the same fleet. Call during component initialisation.
import { useVitals, useContainers } from '$lib/api/queries';
import { useHosts, useArchLive, FALLBACK_FLEET, hostTone, type FleetHost, type HostsResp } from '$lib/api/fleet';
import type { HostView } from './TopoMap.svelte';

export function createFleetView() {
  const hostsQ = useHosts();
  const vitals = useVitals();
  const containers = useContainers();
  const live = useArchLive();

  const fleet = $derived<HostsResp>(hostsQ.data ?? FALLBACK_FLEET);

  const byHostContainers = $derived.by(() => {
    const m: Record<string, { name: string; up: boolean; update: boolean }[]> = {};
    for (const h of containers.data?.hosts ?? []) {
      m[h.host] = h.containers.map((c) => ({ name: c.name, up: c.up, update: c.update_available }));
    }
    return m;
  });

  const views = $derived.by<HostView[]>(() => fleet.hosts.map((host: FleetHost) => {
    const v = vitals.data?.hosts?.[host.name];
    const sample = v?.latest ?? null;
    const cs = byHostContainers[host.name] ?? [];
    const updates = cs.filter((c) => c.update).length;
    const down = cs.filter((c) => !c.up).length;
    let tone = hostTone(host, { updates, vitalsError: v?.error ?? host.vitals_error, hasVitals: !!sample });
    if (down > 0 && tone === 'ok') tone = 'warn';
    const bits: string[] = [];
    if (sample?.load1 != null) bits.push(sample.load1.toFixed(2));
    if (sample?.temp_c != null) bits.push(`${Math.round(sample.temp_c)}°C`);
    if (cs.length) bits.push(`${cs.length - down}/${cs.length} up`);
    if (updates) bits.push(`${updates} upd`);
    const lv = live.data?.hosts?.[host.name];
    if (lv?.pool?.used_pct != null) bits.push(`zfs ${Math.round(lv.pool.used_pct)}%`);
    return { host, tone, stat: bits.join(' · '), containers: cs };
  }));

  return {
    get fleet() { return fleet; },
    get views() { return views; },
    get vitals() { return vitals; },
    get containers() { return containers; },
    get live() { return live; },
    get hostsQ() { return hostsQ; },
    get loading() { return vitals.isLoading && containers.isLoading; },
  };
}
