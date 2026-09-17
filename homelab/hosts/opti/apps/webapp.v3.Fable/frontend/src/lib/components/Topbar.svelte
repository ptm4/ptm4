<script lang="ts">
  import { page } from '$app/state';
  import { Search, Bell, SunMoon, Menu, Palette, RefreshCw, Settings } from '@lucide/svelte';
  import { titleFor } from '$lib/nav';
  import { ui } from '$lib/stores/theme.svelte';
  import { app } from '$lib/stores/ui.svelte';
  import { useNotifications } from '$lib/api/queries';
  import { sse } from '$lib/api/sse.svelte';
  import { relTime } from '$lib/format';
  import { jobStore } from '$lib/stores/jobs.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { useQueryClient } from '@tanstack/svelte-query';

  const qc = useQueryClient();
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

  // Refresh — the missing verb, in the one place every page can reach.
  //
  // Most of this dashboard is derived from collector reports on a schedule, so after
  // you change something by hand (upgrade packages, restart a service) the tiles keep
  // showing the pre-change number until the next scheduled run. This asks the
  // collectors to go and look again NOW, as a job whose steps you can watch, and
  // re-ingests afterwards so every view agrees.
  //
  // Deliberately not automatic on page load: each run is an SSH fan-out across four
  // hosts and takes a minute or two, so doing it implicitly would make the app feel
  // broken rather than fresh. Asking is the honest interaction.
  let refreshing = $state(false);
  async function refreshAll() {
    if (refreshing) return;
    refreshing = true;
    try {
      const res = await fetch('/api/refresh', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { job } = await res.json();
      if (job) jobStore.push(job);
      toast('Re-collecting fleet data — watch the steps bottom-right', 'ok', { ttlMs: 4000 });
    } catch (e) {
      toast(`Could not start a refresh: ${(e as Error).message}`, 'crit');
    } finally {
      refreshing = false;
    }
  }

  // A refresh job finishing is the moment every derived view is wrong-until-refetched,
  // so invalidate the queries that read collector output rather than waiting for their
  // own poll to come round.
  $effect(() => {
    const done = jobStore.all.find((j) => j.kind === 'refresh' && j.status !== 'running');
    if (!done) return;
    for (const k of [['updates'], ['containers'], ['activity'], ['incidents'],
                     ['notifications'], ['runners'], ['reports'], ['hosts']]) {
      qc.invalidateQueries({ queryKey: k });
    }
  });

  let title = $derived(titleFor(page.url.pathname, page.url.searchParams));
  // Boards carry their own hero title; the topbar goes quiet there.
  let quiet = $derived(page.url.pathname === '/');
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

  <a class="tbtn" href="/feed?view=incidents" title="Open findings">
    <Bell aria-hidden="true" /> <span class="lbl">Incidents</span>
    {#if unacked > 0}<span class="bell" data-s={unacked > 5 ? 'crit' : 'warn'}>{unacked}</span>{/if}
  </a>
  <button class="tbtn icon" title="Re-collect all fleet data now (packages, disks, network, health)"
          onclick={refreshAll} disabled={refreshing} aria-label="Refresh fleet data">
    <RefreshCw aria-hidden="true" />
  </button>
  <button class="tbtn icon" title="Accent: {ui.accent} — click to cycle" onclick={() => ui.cycleAccent()}><Palette aria-hidden="true" /></button>
  <button class="tbtn icon" title="Theme: {ui.theme} — click to toggle" onclick={() => ui.toggleTheme()}><SunMoon aria-hidden="true" /></button>
  <a class="tbtn icon" href="/settings" title="Settings" aria-label="Settings"><Settings aria-hidden="true" /></a>
  <a class="tbtn" href="/legacy/" title="The v1 dashboard, unchanged"><span class="lbl">Legacy</span></a>
</header>
