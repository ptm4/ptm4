<script lang="ts">
  import { page } from '$app/state';
  import { Search, Bell, SunMoon, Menu, Palette } from '@lucide/svelte';
  import { titleFor } from '$lib/nav';
  import { ui } from '$lib/stores/theme.svelte';
  import { app } from '$lib/stores/ui.svelte';
  import { useNotifications } from '$lib/api/queries';
  import { sse } from '$lib/api/sse.svelte';
  import { relTime } from '$lib/format';

  const notif = useNotifications();
  let liveLabel = $derived(
    sse.state === 'live' ? 'live · sse'
    : sse.state === 'connecting' ? 'connecting'
    : sse.state === 'degraded' ? 'reconnecting'
    : 'polling');
  let liveTitle = $derived(
    sse.state === 'live'
      ? `Server-sent events connected${sse.lastEventAt ? ` — last ${sse.lastEvent} ${relTime(new Date(sse.lastEventAt).toISOString())}` : ''}`
      : sse.state === 'off' ? 'No event stream from this backend — widgets poll on their normal cadence'
      : 'Event stream interrupted — polling until it returns');
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

  let title = $derived(titleFor(page.url.pathname));
  // Boards carry their own hero title; the topbar goes quiet there.
  let quiet = $derived(page.url.pathname === '/' || page.url.pathname.startsWith('/b/'));
  let unacked = $derived(notif.data?.unacked ?? 0);
</script>

<header class="topbar">
  <button class="tbtn icon rail-toggle" onclick={() => app.setRail(!app.railOpen)} aria-label="Menu"><Menu /></button>
  <span class="crumb">
    {#if quiet}<b>Pert’s Pocket</b> · {title.toLowerCase()}{:else}<b>{title}</b>{/if}
  </span>
  <span class="live" data-s={sse.state === 'live' ? 'live' : sse.state === 'degraded' || sse.state === 'connecting' ? 'degraded' : 'poll'} title={liveTitle}><i></i> {liveLabel}</span>

  <button class="search" onclick={() => app.setCmdk(true)}>
    <Search size={14} aria-hidden="true" />
    <span>Go to, open, run — or ask…</span>
    <kbd>{isMac ? '⌘' : 'Ctrl'} K</kbd>
  </button>

  <a class="tbtn" href="/incidents" title="Open findings">
    <Bell aria-hidden="true" /> <span class="lbl">Incidents</span>
    {#if unacked > 0}<span class="bell" data-s={unacked > 5 ? 'crit' : 'warn'}>{unacked}</span>{/if}
  </a>
  <button class="tbtn icon" title="Accent: {ui.accent} — click to cycle" onclick={() => ui.cycleAccent()}><Palette aria-hidden="true" /></button>
  <button class="tbtn icon" title="Theme: {ui.theme} — click to toggle" onclick={() => ui.toggleTheme()}><SunMoon aria-hidden="true" /></button>
  <a class="tbtn" href="/legacy/" title="The v1 dashboard, unchanged"><span class="lbl">Legacy</span></a>
</header>
