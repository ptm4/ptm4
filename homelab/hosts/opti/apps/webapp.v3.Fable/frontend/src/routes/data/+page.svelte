<script lang="ts">
  // Database — the homelab-db data plane map and the SQL console over the same
  // database, as two tabs. Absorbed routes/query/ 2026-09-10 — see
  // _parts/DataFlowView.svelte and _parts/QueryView.svelte for the (otherwise
  // unchanged) page bodies; SchemaTree.svelte and ResultsGrid.svelte moved here too.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import DataFlowView from './_parts/DataFlowView.svelte';
  import QueryView from './_parts/QueryView.svelte';

  type Tab = 'dataflow' | 'query';

  let raw = $derived(page.url.searchParams.get('tab'));
  let tab: Tab = $derived(raw === 'query' ? 'query' : 'dataflow');

  function selectTab(t: Tab) {
    const url = new URL(page.url);
    if (t === 'dataflow') url.searchParams.delete('tab'); else url.searchParams.set('tab', t);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="bot-tabs">
  <button type="button" class="bot-tab" class:active={tab === 'dataflow'} onclick={() => selectTab('dataflow')}>Data flow</button>
  <button type="button" class="bot-tab" class:active={tab === 'query'} onclick={() => selectTab('query')}>Query</button>
</div>

<!-- Only the active tab's component mounts, so the other tab's queries never run. -->
{#if tab === 'dataflow'}
  <DataFlowView />
{:else}
  <QueryView />
{/if}
