<script lang="ts">
  // What depends on what, with live status: the network nodes, each host's containers,
  // then the diagram (lib/components/TopologyDiagram.svelte).
  import { onMount } from 'svelte';
  import StatusDot from '$lib/components/StatusDot.svelte';
  import TopologyDiagram from '$lib/components/TopologyDiagram.svelte';
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

  <TopologyDiagram topology={topo} />
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
</style>
