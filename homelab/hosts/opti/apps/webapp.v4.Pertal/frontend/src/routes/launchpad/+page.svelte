<script lang="ts">
  import { onMount } from 'svelte';
  import Age from '$lib/components/Age.svelte';
  import { api, type LinkGroup } from '$lib/api';

  let groups = $state<LinkGroup[]>([]);
  let checkedAt = $state<string | null>(null);
  let err = $state<string | null>(null);

  async function load() {
    try {
      const d = await api.links();
      groups = d.groups;
      checkedAt = d.checked_at;
      err = null;
    } catch (e) {
      err = (e as Error).message;
    }
  }
  onMount(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  });
</script>

<svelte:head><title>Launchpad · Pertal</title></svelte:head>

<div class="head">
  <h1>Launchpad</h1>
  <span class="faint">reachability checked <Age at={checkedAt} staleAfterMs={10 * 60_000} /></span>
</div>
{#if err}<p class="empty">{err}</p>{/if}

{#each groups as g (g.group)}
  <h2 class="group faint">{g.group}</h2>
  <div class="grid">
    {#each g.links as l (l.url)}
      <a class="panel tile" href={l.url} target="_blank" rel="noreferrer" class:down={l.reach && !l.reach.up}>
        <img src="/icons/apps/{l.icon}" alt="" width="28" height="28" />
        <span class="label">{l.label}</span>
        {#if l.reach}
          <span class="reach" title={l.reach.up ? `HTTP ${l.reach.status} in ${l.reach.ms} ms` : l.reach.error}>
            {#if l.reach.up}<span class="dot"></span>{:else}<span class="badge crit">down</span>{/if}
          </span>
        {/if}
      </a>
    {/each}
  </div>
{/each}

<style>
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s2); }
  .group { margin: var(--s4) 0 var(--s2); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: var(--s2); }
  .tile { display: flex; align-items: center; gap: 10px; padding: 10px 12px; color: var(--ink); text-decoration: none; }
  .tile:hover { border-color: var(--border-2); background: var(--surface-2); text-decoration: none; }
  .tile.down { border-color: color-mix(in srgb, var(--crit) 45%, var(--border)); }
  .tile img { flex: none; border-radius: 6px; }
  .label { flex: 1; min-width: 0; font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 720px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .tile { padding: 12px 10px; } }
</style>
