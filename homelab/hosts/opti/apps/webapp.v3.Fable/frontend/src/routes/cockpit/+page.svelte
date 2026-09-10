<script lang="ts">
  // Control center — the single operations surface. Overview (the original
  // Cockpit content: FleetBar + per-host cards) is one tab among five; Containers,
  // Updates, Pi-hole and Logs were folded in from their own routes so there is
  // one nav entry instead of five. Tab state lives in the URL (`?tab=`) so a tab
  // is linkable and the back button works, matching the pattern already used by
  // routes/bots/+page.svelte. Each tab's body is its own component and only the
  // active one is instantiated ({#if}/{:else if}), so an inactive tab's queries
  // (containers, updates, pihole, dozzle) do not run.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import OverviewPanel from './_parts/OverviewPanel.svelte';
  import ContainersPanel from './_parts/ContainersPanel.svelte';
  import UpdatesPanel from './_parts/UpdatesPanel.svelte';
  import PiholePanel from './_parts/PiholePanel.svelte';
  import LogsPanel from './_parts/LogsPanel.svelte';

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'containers', label: 'Containers' },
    { id: 'updates', label: 'Updates' },
    { id: 'pihole', label: 'Pi-hole' },
    { id: 'logs', label: 'Logs' },
  ] as const;
  type TabId = (typeof TABS)[number]['id'];
  const TAB_IDS: readonly string[] = TABS.map((t) => t.id);
  const isTabId = (v: string | null): v is TabId => !!v && TAB_IDS.includes(v);

  let tab = $derived<TabId>(
    (() => {
      const v = page.url.searchParams.get('tab');
      return isTabId(v) ? v : 'overview';
    })(),
  );

  function selectTab(id: TabId) {
    const url = new URL(page.url);
    url.searchParams.set('tab', id);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="bot-tabs">
  {#each TABS as t (t.id)}
    <button type="button" class="bot-tab" class:active={tab === t.id} onclick={() => selectTab(t.id)}>
      {t.label}
    </button>
  {/each}
</div>

{#if tab === 'overview'}
  <OverviewPanel />
{:else if tab === 'containers'}
  <ContainersPanel />
{:else if tab === 'updates'}
  <UpdatesPanel />
{:else if tab === 'pihole'}
  <PiholePanel />
{:else if tab === 'logs'}
  <LogsPanel />
{/if}
