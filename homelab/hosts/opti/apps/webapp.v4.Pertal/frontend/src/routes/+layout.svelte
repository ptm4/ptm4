<script lang="ts">
  import '$lib/theme/app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { Menu, Search, WifiOff } from '@lucide/svelte';
  import Icon from '$lib/components/Icon.svelte';
  import JobTray from '$lib/components/JobTray.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import SearchPalette from '$lib/components/SearchPalette.svelte';
  import AppsMenu from '$lib/components/AppsMenu.svelte';
  import { live } from '$lib/live.svelte';
  import { theme } from '$lib/theme.svelte';
  import { NAV } from '$lib/nav';
  import { ago } from '$lib/format';

  let { children } = $props();
  let drawer = $state(false);
  let search = $state(false);

  onMount(() => {
    void theme; // applies the saved theme
    live.start();
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); search = true; }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  });

  $effect(() => { void page.url.pathname; drawer = false; });

  const isActive = (href: string) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href) || (href === '/resources' && page.url.pathname.startsWith('/r/')));
  const attention = $derived((live.summary?.counts.crit ?? 0) + (live.summary?.counts.warn ?? 0));
</script>

<div class="app" class:drawer>
  <header class="topbar">
    <button class="btn ghost icon menu" aria-label="Open navigation" onclick={() => (drawer = !drawer)}><Menu size={18} /></button>
    <a class="brand" href="/"><img src="/favicon.svg" alt="" width="22" height="22" /> Pertal</a>
    <button class="search" onclick={() => (search = true)}>
      <Search size={14} /><span>Search resources…</span><kbd>Ctrl K</kbd>
    </button>
    <AppsMenu />
    <span class="live" class:off={!live.connected} title={live.connected ? 'Live: receiving updates' : 'Not connected — showing last known data'}>
      <span class="pulse"></span>{live.connected ? 'live' : 'offline'}
    </span>
  </header>

  <nav class="rail" aria-label="Main">
    {#each NAV as n (n.href)}
      {#if n.ready}
        <a href={n.href} class:active={isActive(n.href)} aria-current={isActive(n.href) ? 'page' : undefined}>
          <Icon name={n.icon} size={16} />
          <span>{n.label}</span>
          {#if n.href === '/' && attention}<span class="count">{attention}</span>{/if}
        </a>
      {:else}
        <span class="soon" title="Coming in the v4 build">
          <Icon name={n.icon} size={16} /><span>{n.label}</span><em>soon</em>
        </span>
      {/if}
    {/each}
    <div class="rail-foot faint">Pertal {live.version}</div>
  </nav>
  <div class="scrim" role="presentation" onclick={() => (drawer = false)}></div>

  <main>
    {#if live.error && !live.connected}
      <div class="banner">
        <WifiOff size={18} />
        <div>
          <strong>Can't reach opti.</strong>
          {#if live.loaded}Showing what Pertal last knew{#if live.lastMessageAt}, from {ago(new Date(live.lastMessageAt).toISOString(), live.now)}{/if}.{/if}
          If this device has network, opti or its app tier is down —
          <a href="http://noblenumbat.lan:3001/" target="_blank" rel="noreferrer">Uptime Kuma</a>
          runs on noblenumbat and sees it from outside.
          <span class="faint">({live.error})</span>
        </div>
      </div>
    {/if}
    {@render children()}
  </main>
</div>

<SearchPalette bind:open={search} />
<ConfirmDialog />
<JobTray />

<style>
  .app {
    display: grid;
    grid-template-columns: var(--rail-w) minmax(0, 1fr);
    grid-template-rows: var(--topbar-h) 1fr;
    grid-template-areas: 'top top' 'rail main';
    min-height: 100vh;
  }
  .topbar {
    grid-area: top; position: sticky; top: 0; z-index: 30;
    display: flex; align-items: center; gap: var(--s3);
    padding: 0 var(--s4);
    background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .menu { display: none; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 700; color: var(--brand); text-decoration: none; letter-spacing: .02em; }
  .search {
    flex: 1; max-width: 460px; margin: 0 auto; display: flex; align-items: center; gap: 8px;
    height: 30px; padding: 0 10px; border: 1px solid var(--border-2); border-radius: var(--r);
    background: var(--bg-inset); color: var(--ink-3); cursor: pointer; font-size: var(--fs-sm);
  }
  .search span { flex: 1; text-align: left; }
  kbd { font: var(--fs-xs) var(--mono); padding: 1px 5px; border: 1px solid var(--border-2); border-radius: var(--r-sm); }
  .live { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--ink-3); text-transform: uppercase; letter-spacing: .06em; }
  .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
  .live:not(.off) .pulse { animation: pulse 2.4s ease-in-out infinite; }
  .live.off { color: var(--warn); }
  .live.off .pulse { background: var(--warn); }
  @keyframes pulse { 50% { opacity: .35; } }

  .rail {
    grid-area: rail; position: sticky; top: var(--topbar-h); height: calc(100vh - var(--topbar-h));
    display: flex; flex-direction: column; gap: 2px; padding: var(--s3) var(--s2);
    background: var(--surface); border-right: 1px solid var(--border); overflow-y: auto;
  }
  .rail a, .rail .soon {
    display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 10px;
    border-radius: var(--r); color: var(--ink-2); font-size: var(--fs-md); text-decoration: none;
  }
  .rail a:hover { background: var(--surface-2); color: var(--ink); }
  .rail a.active { background: var(--accent-dim); color: var(--ink); box-shadow: inset 2px 0 0 var(--accent); }
  .rail .soon { color: var(--ink-3); opacity: .6; cursor: default; }
  .rail .soon em { margin-left: auto; font-size: var(--fs-xs); font-style: normal; }
  .count { margin-left: auto; font-size: var(--fs-xs); padding: 0 6px; border-radius: 999px; background: var(--warn-dim); color: var(--warn); }
  .rail-foot { margin-top: auto; padding: 8px 10px 0; font-size: var(--fs-xs); }
  .scrim { display: none; }

  main { grid-area: main; min-width: 0; padding: var(--s4) var(--s5) 96px; }
  .banner {
    display: flex; align-items: flex-start; gap: 10px; margin-bottom: var(--s4); padding: 10px 14px;
    border: 1px solid var(--crit); border-radius: var(--r); background: var(--crit-dim); color: var(--ink); font-size: var(--fs-sm);
  }
  .banner :global(svg) { color: var(--crit); flex: none; margin-top: 1px; }
  .banner strong { color: var(--crit); }

  @media (max-width: 900px) {
    .app { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'top' 'main'; }
    .menu { display: inline-flex; }
    .search span, .search kbd { display: none; }
    .search { flex: 0 0 auto; width: 36px; justify-content: center; margin: 0 0 0 auto; }
    .rail {
      position: fixed; z-index: 50; top: 0; left: 0; bottom: 0; height: 100vh; width: min(280px, 84vw);
      transform: translateX(-100%); transition: transform .18s ease; padding-top: var(--s4);
      box-shadow: var(--shadow);
    }
    .drawer .rail { transform: none; }
    .rail a, .rail .soon { height: 44px; }
    .drawer .scrim { display: block; position: fixed; inset: 0; z-index: 45; background: rgba(0, 0, 0, .45); }
    main { padding: var(--s3) var(--s3) 120px; }
  }
</style>
