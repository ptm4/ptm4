<script lang="ts">
  // hltv: Valve Regional Standings viewer — fetched on demand, not persisted.
  import { createMutation } from '@tanstack/svelte-query';
  import { ListOrdered } from '@lucide/svelte';
  import { get, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import type { VrsList } from '$lib/bots';

  function extraErrorMessage(e: unknown, fallback: string): string {
    return (e as ApiError)?.message ?? fallback;
  }

  let vrs = $state<VrsList | null>(null);
  const load = createMutation(() => ({
    mutationFn: () => get<VrsList>('/api/hltv/vrs', 25_000),
    onSuccess: (d) => { vrs = d; },
    onError: (e: Error) => toast(extraErrorMessage(e, 'VRS fetch failed.'), 'crit'),
  }));
</script>

<section class="card bot-extra">
  <div class="w-head">
    <span class="w-title">Valve Regional Standings</span>
    {#if vrs?.as_of}<span class="w-meta">as of {vrs.as_of}</span>{/if}
  </div>
  {#if vrs?.teams}
    <div class="kv-rows vrs-list">
      {#each vrs.teams as t, i (i)}
        <div class="kv-row"><span class="mono">#{i + 1}</span><span>{t}</span></div>
      {/each}
    </div>
  {/if}
  <div class="w-actions">
    <button class="tbtn" disabled={load.isPending} onclick={() => load.mutate()}>
      <ListOrdered size={14} aria-hidden="true" /> {load.isPending ? 'Fetching…' : vrs ? 'Refresh VRS list' : 'Show VRS list'}
    </button>
  </div>
  <p class="form-note t-dim">
    VRS = Valve Regional Standings (official ranking, refreshed ~weekly) — the only
    ranking the digest uses.
  </p>
</section>
