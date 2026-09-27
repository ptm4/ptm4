<script lang="ts">
  // The Azure-style command bar: every action this resource supports, plus its links.
  // Buttons for an action already running on this resource show a spinner and disable.
  import { LoaderCircle } from '@lucide/svelte';
  import Icon from './Icon.svelte';
  import { actions } from '$lib/actions.svelte';
  import { live } from '$lib/live.svelte';
  import type { Resource } from '$lib/types';

  let { resource }: { resource: Resource } = $props();

  const running = $derived(
    new Set(live.jobs.filter((j) => j.status === 'running' && j.resource === resource.id).map((j) => j.kind)),
  );
  const linkLabel: Record<string, string> = {
    cockpit: 'Cockpit', omv: 'OpenMediaVault', pihole: 'Pi-hole', jellyfin: 'Jellyfin', kuma: 'Uptime Kuma',
  };
</script>

<div class="cmdbar" role="toolbar" aria-label="Actions for {resource.name}">
  {#each resource.actions as a (a.kind)}
    <button
      class="btn"
      class:danger={a.risky}
      disabled={running.has(a.kind)}
      onclick={() => actions.run(a, resource)}
      title={a.risky ? `${a.label} (asks for confirmation)` : a.label}
    >
      {#if running.has(a.kind)}<LoaderCircle size={15} class="spin" />{:else}<Icon name={a.icon} />{/if}
      {a.label}
    </button>
  {/each}
  {#each Object.entries(resource.links ?? {}) as [key, href] (key)}
    <a class="btn ghost" {href} target="_blank" rel="noreferrer">
      <Icon name="external-link" />{linkLabel[key] ?? key}
    </a>
  {/each}
</div>

<style>
  .cmdbar {
    display: flex; flex-wrap: wrap; gap: 6px;
    padding: var(--s2) 0; border-bottom: 1px solid var(--border);
  }
  :global(.spin) { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
