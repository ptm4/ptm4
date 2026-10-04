<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import CockpitFrame from '$lib/components/CockpitFrame.svelte';
  import { CONSOLE_HOSTS, consoleHost, consolePath } from '$lib/console';

  const host = $derived(page.params.host ?? '');
  const path = $derived(consolePath(page.url.pathname.slice(`/console/${host}/`.length)));
  const hash = $derived(page.state.cockpitHash ?? '');
  $effect(() => {
    if (consoleHost(host)) { try { localStorage.setItem('pertal-console-host', host); } catch { /* private storage */ } }
  });
  onMount(() => {
    // URL queries/hashes never enter the Cockpit frame, including pasted links.
    if (page.url.hash || page.url.search) void goto(page.url.pathname, { replaceState: true, state: {} });
  });
</script>

<svelte:head><title>Console · {host} · Pertal</title></svelte:head>
<section class="console" aria-label="Host Console">
  <div class="tools">
    <nav aria-label="Console host">
      {#each CONSOLE_HOSTS as id}
        <a class="btn ghost" class:active={host === id} href="/console/{id}/system" aria-current={host === id ? 'page' : undefined}>{id}</a>
      {/each}
    </nav>
    {#if consoleHost(host)}<a class="btn ghost" href="/cp-{host}/{path}" target="_blank" rel="noreferrer">Open in new tab ↗</a>{/if}
  </div>
  {#if host === 'opti'}<p class="caution">Reboot here skips the ZFS module check — run <code>dkms status</code> first.</p>{/if}
  {#if host === 'noblenumbat'}<p class="caution">This host has hung at POST after reboots.</p>{/if}
  {#key host}<CockpitFrame {host} {path} {hash} />{/key}
</section>

<style>
  .console { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .tools { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; padding: var(--s2); border-bottom: 1px solid var(--border); }
  nav { display: flex; flex-wrap: wrap; gap: 4px; }
  .active { background: var(--accent-dim); color: var(--ink); }
  .caution { margin: 0; padding: 6px var(--s3); color: var(--warn); font-size: var(--fs-xs); border-bottom: 1px solid var(--border); }
</style>
