<script lang="ts">
  // Topology — the LAN itself as the page. Map on the left, inspector on the right,
  // the fleet's activity and updates below.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import TopoMap from '$lib/features/topology/TopoMap.svelte';
  import NodeInspector from '$lib/features/topology/NodeInspector.svelte';
  import { createFleetView } from '$lib/features/topology/fleet-view.svelte';
  import { useUpdates } from '$lib/api/fleet';
  import { relTime } from '$lib/format';
  import FleetStrip from '$lib/components/FleetStrip.svelte';

  const fv = createFleetView();
  const updates = useUpdates();

  let selected = $state<string | null>(page.url.searchParams.get('host') ?? 'opti');
  function select(name: string | null) {
    selected = name;
    const url = new URL(page.url);
    if (name) url.searchParams.set('host', name); else url.searchParams.delete('host');
    goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }

  let sel = $derived(fv.views.find((v) => v.host.name === selected) ?? null);
  let selVitals = $derived(sel ? (fv.vitals.data?.hosts?.[sel.host.name]?.latest ?? null) : null);
  let selLive = $derived(sel ? (fv.live.data?.hosts?.[sel.host.name] ?? null) : null);
  let selUpdates = $derived(sel ? sel.containers.filter((c) => c.update).length : 0);
  let selContainers = $derived(sel ? { up: sel.containers.filter((c) => c.up).length, total: sel.containers.length } : { up: 0, total: 0 });
</script>

<div class="topo-page">
  <FleetStrip />
  <div class="shead">
    <h2>Topology</h2>
    <span class="meta">live LAN · 192.168.1.0/24{fv.live.data?.run_at ? ` · doctor ${relTime(fv.live.data.run_at)}` : ''}{fv.hostsQ.isError ? ' · static host table (backend without /api/hosts)' : ''}</span>
    <a class="more" href="/architecture/">Full architecture map →</a>
  </div>

  {#if fv.loading}
    <div class="spin"></div>
  {:else}
    <div class="stage">
      <TopoMap hosts={fv.views} depends={fv.fleet.depends} gateway={fv.fleet.gateway} {selected} onSelect={select} />
      {#if sel}
        {#key sel.host.name}
          <NodeInspector host={sel.host} vitals={selVitals} live={selLive} containers={selContainers} updates={selUpdates} depends={fv.fleet.depends} />
        {/key}
      {:else}
        <div class="card insp-empty"><p class="dim">Click a host on the map to inspect it.</p></div>
      {/if}
    </div>
  {/if}

  <div class="grid">
    <section class="card c6">
      <div class="chead"><h3>Hosts</h3><span class="meta">{fv.views.length} nodes</span></div>
      <div class="rows">
        {#each fv.views as v (v.host.name)}
          <a class="row hostrow" href="/host/{v.host.name}">
            <span class="pip" data-s={v.tone === 'off' ? 'unknown' : v.tone}></span>
            <span class="who">{v.host.label}</span>
            <span class="what">{v.host.role} · {v.host.ip}</span>
            <span class="num faint">{v.stat || (v.host.intermittent ? 'offline' : '—')}</span>
          </a>
        {/each}
      </div>
    </section>
    <section class="card c6">
      <div class="chead"><h3>Pending work</h3><span class="meta">{updates.data ? `${updates.data.counts.images} images · ${updates.data.counts.packages} packages` : '…'}</span></div>
      {#if updates.isError}<p class="err">Updates unavailable.</p>{/if}
      <div class="rows">
        {#each (updates.data?.images ?? []).slice(0, 8) as u (u.host + u.container)}
          <div class="row"><span class="who">{u.container}</span><span class="what">{u.host}{u.image ? ` · ${u.image}` : ''}</span><span class="chip" data-s="warn">image</span></div>
        {/each}
        {#each updates.data?.packages ?? [] as p (p.host)}
          <div class="row"><span class="who">{p.host}</span><span class="what">{p.pending} packages{p.security ? ` · ${p.security} security` : ''}{p.reboot_required ? ' · reboot required' : ''}</span><span class="chip" data-s={p.security ? 'crit' : 'warn'}>apt</span></div>
        {/each}
        {#if updates.data && updates.data.images.length === 0 && updates.data.packages.length === 0}
          <p class="empty">Nothing pending across the fleet.</p>
        {/if}
      </div>
      <a class="faint" style="font-size: 11.5px" href="/updates">All updates →</a>
    </section>
  </div>
</div>

<style>
  .topo-page { display: flex; flex-direction: column; gap: 18px; }
  .stage { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: stretch; }
  .insp-empty { display: grid; place-items: center; }
  .hostrow { text-decoration: none; color: inherit; }
  .hostrow:hover .who { color: var(--accent); }
  @media (max-width: 1080px) { .stage { grid-template-columns: 1fr; } }
</style>
