<script lang="ts">
  // Reports — collector runs (/api/runners) and security-agent reports (/api/reports)
  // in one page, switchable with a filter. Both sides render the identical
  // ReportCard/ReportModal grammar from $lib/components/reports/; only apiBase
  // differs. Absorbed routes/security/ 2026-09-10 — see _parts/CollectorsGrid.svelte
  // and _parts/SecurityGrid.svelte for the (otherwise unchanged) page bodies.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import CollectorsGrid from './_parts/CollectorsGrid.svelte';
  import SecurityGrid from './_parts/SecurityGrid.svelte';

  type Filter = 'all' | 'collectors' | 'security';
  const FILTERS: { id: Filter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'collectors', label: 'Collectors' },
    { id: 'security', label: 'Security' },
  ];

  let raw = $derived(page.url.searchParams.get('filter'));
  let filter: Filter = $derived(raw === 'collectors' || raw === 'security' ? raw : 'all');

  function selectFilter(id: Filter) {
    const url = new URL(page.url);
    if (id === 'all') url.searchParams.delete('filter'); else url.searchParams.set('filter', id);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="reports-page">
  <div class="bot-tabs">
    {#each FILTERS as f (f.id)}
      <button type="button" class="bot-tab" class:active={filter === f.id} onclick={() => selectFilter(f.id)}>{f.label}</button>
    {/each}
  </div>

  <!-- Only the active filter's components mount, so a filtered-out source's query never runs. -->
  {#if filter !== 'security'}<CollectorsGrid />{/if}
  {#if filter !== 'collectors'}<SecurityGrid />{/if}
</div>
