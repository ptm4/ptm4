<script lang="ts">
  // Phone navigation: the five things you reach for on the couch, one tap each. The
  // rail is still there behind "More". Hidden on desktop by app.css.
  import { page } from '$app/state';
  import { Home, Tv, ListOrdered, Rocket, Menu } from '@lucide/svelte';
  import { app } from '$lib/stores/ui.svelte';
  import { useStationStatus } from '$lib/api/streams';

  const station = useStationStatus();
  let liveCount = $derived((station.data?.slots ?? []).filter((s) => s.state === 'running' || s.state === 'starting').length);
  const is = (p: string) => (p === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(p));
</script>

<nav class="bottomnav" aria-label="Primary (mobile)">
  <a href="/" class:on={is('/')}><Home size={20} /><span>Home</span></a>
  <a href="/streams" class:on={is('/streams')}><Tv size={20} />{#if liveCount}<i class="live">{liveCount}</i>{/if}<span>Streams</span></a>
  <a href="/feed" class:on={is('/feed')}><ListOrdered size={20} /><span>Feed</span></a>
  <a href="/launchpad" class:on={is('/launchpad')}><Rocket size={20} /><span>Launch</span></a>
  <button onclick={() => app.setRail(true)}><Menu size={20} /><span>More</span></button>
</nav>

<style>
  .bottomnav { display: none; }
  @media (max-width: 860px) {
    .bottomnav {
      position: fixed; left: 0; right: 0; bottom: 0; z-index: 50;
      display: grid; grid-template-columns: repeat(5, 1fr);
      background: color-mix(in srgb, var(--bg) 92%, transparent);
      backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
      border-top: 1px solid var(--border);
      padding: 6px 4px calc(6px + env(safe-area-inset-bottom));
    }
    .bottomnav a, .bottomnav button {
      position: relative; display: flex; flex-direction: column; align-items: center; gap: 3px;
      color: var(--ink-3); text-decoration: none; font: 500 10.5px var(--sans); background: none; border: 0; padding: 4px 0; cursor: pointer;
    }
    .bottomnav a.on { color: var(--accent); }
    .bottomnav .live { position: absolute; top: 0; right: calc(50% - 18px); font: 700 9px var(--mono); color: var(--bg); background: var(--crit); border-radius: 99px; padding: 1px 4px; font-style: normal; }
  }
</style>
