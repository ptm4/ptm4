<script lang="ts">
  // Activity — the Feed (chronological stream) and Incidents (grouped, actionable
  // findings) merged into one page with a Stream/Incidents toggle. Defaults to
  // Incidents when something is open and needs attention, Stream otherwise. Absorbed
  // routes/incidents/ 2026-09-10 — see _parts/StreamView.svelte and
  // _parts/IncidentsView.svelte for the (otherwise unchanged) page bodies.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { useIncidents } from '$lib/api/incidents';
  import NowRail from '$lib/components/NowRail.svelte';
  import StreamView from './_parts/StreamView.svelte';
  import IncidentsView from './_parts/IncidentsView.svelte';

  type View = 'stream' | 'incidents';

  // Same default query IncidentsView/StreamView make (showAll=false) — TanStack Query
  // dedupes by key, so this doesn't add a request beyond what the active view already
  // makes. Only needed here to pick a default view before the user has chosen one.
  const incidentsGate = useIncidents();
  let openCount = $derived((incidentsGate.data?.incidents ?? []).filter((i) => i.status === 'open').length);

  let explicit = $derived(page.url.searchParams.get('view'));
  let view: View = $derived(
    explicit === 'incidents' ? 'incidents'
    : explicit === 'stream' ? 'stream'
    : openCount > 0 ? 'incidents' : 'stream',
  );

  // Always writes the param explicitly (never deletes it back to "no param"), so a
  // manual pick always wins over the open-incidents default above.
  function selectView(v: View) {
    const url = new URL(page.url);
    url.searchParams.set('view', v);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="feed-page">
  <div class="shead">
    <h2>Activity</h2>
    <span class="meta">{view === 'stream' ? 'everything, newest first' : 'findings correlated by host and time'}</span>
    <div class="bot-tabs right">
      <button type="button" class="bot-tab" class:active={view === 'stream'} onclick={() => selectView('stream')}>Stream</button>
      <button type="button" class="bot-tab" class:active={view === 'incidents'} onclick={() => selectView('incidents')}>
        Incidents {#if openCount > 0}<span class="chip" data-s="warn">{openCount}</span>{/if}
      </button>
    </div>
  </div>

  <div class="split">
    <div class="feed-main">
      {#if view === 'stream'}
        <StreamView />
      {:else}
        <IncidentsView />
      {/if}
    </div>
    <NowRail />
  </div>
</div>

<style>
  .feed-page { display: flex; flex-direction: column; gap: 14px; }
  .split { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: start; }
  .feed-main { min-width: 0; }
  @media (max-width: 1080px) { .split { grid-template-columns: 1fr; } }
</style>
