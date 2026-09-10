<script lang="ts">
  // Home — the Fable synthesis: fleet strip, the LAN map as the hero with its
  // inspector, the ops feed beside the Now rail, and the Home board underneath,
  // read-only. Every piece is a component the dedicated pages also use.
  import { ArrowRight } from '@lucide/svelte';
  import FleetStrip from '$lib/components/FleetStrip.svelte';
  import NowRail from '$lib/components/NowRail.svelte';
  import TopoMap from '$lib/features/topology/TopoMap.svelte';
  import NodeInspector from '$lib/features/topology/NodeInspector.svelte';
  import { createFleetView } from '$lib/features/topology/fleet-view.svelte';
  import FeedItemView from '$lib/features/feed/FeedItemView.svelte';
  import { mergeFeed, dayLabel } from '$lib/features/feed/feed-merge';
  import { useActivity } from '$lib/api/queries';
  import { useIncidents } from '$lib/api/incidents';
  import { useChanges } from '$lib/api/fleet';
  import StreamsCard from '$lib/features/streams/StreamsCard.svelte';
  import LaunchDock from '$lib/components/LaunchDock.svelte';

  const fv = createFleetView();
  const activity = useActivity(30);
  const incidents = useIncidents();
  const changes = useChanges(() => '', () => 3);

  let selected = $state<string | null>(null);
  let sel = $derived(fv.views.find((v) => v.host.name === selected) ?? null);
  let selVitals = $derived(sel ? (fv.vitals.data?.hosts?.[sel.host.name]?.latest ?? null) : null);
  let selLive = $derived(sel ? (fv.live.data?.hosts?.[sel.host.name] ?? null) : null);

  let feed = $derived(mergeFeed(activity.data?.events, incidents.data?.incidents, changes.data?.events).slice(0, 8));
  let groups = $derived.by(() => {
    const out: { day: string; items: typeof feed }[] = [];
    for (const it of feed) {
      const day = it.kind === 'incident' && it.incident?.status === 'open' ? 'Needs action' : dayLabel(it.ts);
      const g = out[out.length - 1];
      if (g && g.day === day) g.items.push(it); else out.push({ day, items: [it] });
    }
    return out;
  });
</script>

<div class="home">
  <FleetStrip />
  <LaunchDock />

  <div class="shead"><h2>Topology</h2><span class="meta">live LAN · click a host</span><a class="more" href="/topology">Open the map <ArrowRight size={12} aria-hidden="true" /></a></div>
  <div class="stage">
    <TopoMap hosts={fv.views} depends={fv.fleet.depends} gateway={fv.fleet.gateway} {selected} onSelect={(n) => (selected = n)} compact />
    {#if sel}
      {#key sel.host.name}
        <NodeInspector host={sel.host} vitals={selVitals} live={selLive}
          containers={{ up: sel.containers.filter((c) => c.up).length, total: sel.containers.length }}
          updates={sel.containers.filter((c) => c.update).length} depends={fv.fleet.depends} />
      {/key}
    {:else}
      <div class="card hosts-mini">
        <div class="chead"><h3>Hosts</h3><span class="meta">{fv.views.length}</span></div>
        <div class="rows">
          {#each fv.views as v (v.host.name)}
            <button class="row hostrow" onclick={() => (selected = v.host.name)}>
              <span class="pip" data-s={v.tone === 'off' ? 'unknown' : v.tone}></span>
              <span class="who">{v.host.label}</span>
              <span class="what faint">{v.stat || v.host.role}</span>
            </button>
          {/each}
        </div>
        <p class="faint" style="font-size: 11.5px; margin: 0">Select a host to inspect it here.</p>
      </div>
    {/if}
  </div>

  <div class="shead"><h2>Feed</h2><span class="meta">latest across the fleet</span><a class="more" href="/feed">Full stream <ArrowRight size={12} aria-hidden="true" /></a></div>
  <div class="split">
    <div class="feed">
      {#if activity.isLoading}<div class="spin"></div>{/if}
      {#each groups as g (g.day)}
        <div class="divider">{g.day}</div>
        {#each g.items as it (it.key)}<FeedItemView item={it} />{/each}
      {/each}
      {#if activity.data && feed.length === 0}<div class="card"><p class="empty">Quiet — nothing reported recently.</p></div>{/if}
    </div>
    <div class="rail-col">
      <StreamsCard />
      <NowRail />
    </div>
  </div>
</div>

<style>
  .home { display: flex; flex-direction: column; gap: 14px; }
  .stage { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: stretch; }
  .split { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: start; }
  .feed { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .rail-col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .hosts-mini { gap: 8px; }
  .hostrow { background: none; border: 0; border-top: 1px solid var(--border); font: inherit; color: inherit; cursor: pointer; width: 100%; text-align: left; }
  .rows .hostrow:first-child { border-top: 0; }
  .hostrow:hover .who { color: var(--accent); }
  @media (max-width: 1080px) { .stage, .split { grid-template-columns: 1fr; } }
</style>
