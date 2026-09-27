<script lang="ts">
  // What depends on what, with live status. Host columns (network → servers), then the
  // dependency list: a red line means one end of that dependency is actually down.
  import { onMount } from 'svelte';
  import StatusDot from '$lib/components/StatusDot.svelte';
  import { api } from '$lib/api';
  import { live } from '$lib/live.svelte';

  let topo = $state<any>(null);
  let err = $state<string | null>(null);
  async function load() {
    try { topo = await api.topology(); err = null; } catch (e) { err = (e as Error).message; }
  }
  onMount(load);
  // Rebuild whenever the resource model changes (cheap: it is computed server-side).
  $effect(() => { void live.builtAt; void load(); });

  const label = (id: string) => {
    const n = topo?.nodes.find((x: any) => x.id === id);
    if (n) return n.label;
    const r = live.byId(id);
    return r ? (r.type === 'container' ? `${r.name} (${r.host})` : r.name) : id;
  };
  const link = (id: string) => (live.byId(id) ? `/r/${id}` : null);
</script>

<svelte:head><title>Topology · Pertal</title></svelte:head>

<h1>Topology</h1>
{#if err}<p class="empty">{err}</p>{/if}

{#if topo}
  <div class="net">
    {#each topo.nodes as n (n.id)}
      <div class="panel node"><strong>{n.label}</strong>{#if n.sub}<span class="faint">{n.sub}</span>{/if}</div>
    {/each}
  </div>

  <div class="hosts">
    {#each topo.hosts as h (h.id)}
      <section class="panel host" data-status={h.status}>
        <a class="hhead" href="/r/{h.id}"><StatusDot status={h.status} /><strong>{h.label}</strong><span class="faint">{h.role}</span></a>
        <div class="chips">
          {#each h.children as c (c.id)}
            <a class="chip {c.kind}" href="/r/{c.id}" title="{c.name}: {c.status}"><StatusDot status={c.status} />{c.name}</a>
          {:else}
            <span class="faint small">{h.state_text}</span>
          {/each}
        </div>
      </section>
    {/each}
  </div>

  <section class="panel">
    <div class="panel-head"><h2>Dependencies</h2><span class="faint">red = one end is down</span></div>
    <div class="rows">
      {#each topo.edges as e (e.from + e.to)}
        <div class="row edge" class:broken={e.status !== 'ok'}>
          {#if link(e.from)}<a href={link(e.from)}>{label(e.from)}</a>{:else}<span>{label(e.from)}</span>{/if}
          <span class="arrow" class:crit-line={e.critical}>→</span>
          {#if link(e.to)}<a href={link(e.to)}>{label(e.to)}</a>{:else}<span>{label(e.to)}</span>{/if}
          <span class="muted what">{e.label}</span>
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  h1 { margin-bottom: var(--s3); }
  .net { display: flex; flex-wrap: wrap; gap: var(--s2); margin-bottom: var(--s3); }
  .node { display: flex; flex-direction: column; padding: 8px 12px; font-size: var(--fs-sm); }
  .hosts { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--s3); margin-bottom: var(--s3); }
  .host { padding: var(--s3); }
  .host[data-status='crit'] { border-color: color-mix(in srgb, var(--crit) 45%, var(--border)); }
  .hhead { display: flex; align-items: center; gap: 8px; color: var(--ink); text-decoration: none; margin-bottom: 10px; }
  .hhead .faint { margin-left: auto; font-size: var(--fs-xs); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 999px;
    border: 1px solid var(--border); font-size: var(--fs-xs); color: var(--ink-2); text-decoration: none;
  }
  .chip:hover { border-color: var(--border-2); color: var(--ink); text-decoration: none; }
  .chip.bot { border-style: dashed; }
  .small { font-size: var(--fs-xs); }
  .edge { grid-template-columns: auto auto auto minmax(0, 1fr); font-size: var(--fs-sm); }
  .arrow { color: var(--ink-3); }
  .arrow.crit-line { color: var(--ink-2); font-weight: 700; }
  .edge.broken { background: var(--crit-dim); }
  .edge.broken .arrow { color: var(--crit); }
  .what { font-size: var(--fs-xs); }
  @media (max-width: 720px) { .edge { grid-template-columns: auto auto auto; } .what { grid-column: 1 / -1; } }
</style>
