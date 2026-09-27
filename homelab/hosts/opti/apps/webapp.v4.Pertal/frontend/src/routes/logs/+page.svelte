<script lang="ts">
  // Logs for any container on any host. Selection lives in the URL (?c=host:name).
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import StatusDot from '$lib/components/StatusDot.svelte';
  import LogViewer from '$lib/components/LogViewer.svelte';
  import { live } from '$lib/live.svelte';

  const selected = $derived(page.url.searchParams.get('c'));
  const target = $derived(selected ? live.byId(selected) : null);
  let q = $state('');

  const groups = $derived.by(() => {
    const hosts = live.resources.filter((r) => r.type === 'host' && r.counts);
    return hosts.map((h) => ({
      host: h,
      items: live.resources.filter((c) => c.type === 'container' && c.host === h.id && (!q || c.name.includes(q.toLowerCase()))),
    }));
  });

  function pick(id: string) {
    const u = new URL(page.url);
    u.searchParams.set('c', id);
    goto(u, { keepFocus: true, noScroll: true });
  }
</script>

<svelte:head><title>Logs · Pertal</title></svelte:head>

<div class="layout" class:picked={!!target}>
  <aside class="panel list">
    <div class="panel-head"><input class="field" type="search" placeholder="Find a container…" bind:value={q} /></div>
    {#each groups as g (g.host.id)}
      <div class="hosthead faint">{g.host.name}</div>
      {#each g.items as c (c.id)}
        <button class="pick" class:on={c.id === selected} onclick={() => pick(c.id)}>
          <StatusDot status={c.status} /><span>{c.name}</span>
        </button>
      {/each}
    {/each}
  </aside>
  <section class="viewer">
    {#if target && target.type === 'container'}
      <div class="vhead">
        <button class="btn ghost back" onclick={() => goto('/logs')}>← All</button>
        <h1><a href="/r/{target.id}">{target.name}</a></h1>
        <span class="faint">on {target.host} · {target.state_text}</span>
      </div>
      <LogViewer host={target.host} container={target.name} />
    {:else}
      <div class="empty panel">Pick a container to read its logs.</div>
    {/if}
  </section>
</div>

<style>
  .layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: var(--s3); align-items: start; }
  .list { max-height: calc(100vh - 110px); overflow: auto; position: sticky; top: calc(var(--topbar-h) + 16px); }
  .list .field { width: 100%; }
  .hosthead { padding: 10px 14px 4px; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; }
  .pick {
    display: flex; align-items: center; gap: 8px; width: 100%; padding: 5px 14px;
    border: 0; background: none; text-align: left; cursor: pointer; font-size: var(--fs-sm); color: var(--ink-2);
  }
  .pick:hover { background: var(--surface-2); }
  .pick.on { background: var(--accent-dim); color: var(--ink); }
  .vhead { display: flex; align-items: baseline; gap: var(--s3); margin-bottom: var(--s3); flex-wrap: wrap; }
  .vhead h1 { font-size: var(--fs-lg); }
  .back { display: none; }
  @media (max-width: 900px) {
    .layout { grid-template-columns: minmax(0, 1fr); }
    .list { position: static; max-height: none; }
    .picked .list { display: none; }
    .layout:not(.picked) .viewer { display: none; }
    .back { display: inline-flex; }
  }
</style>
