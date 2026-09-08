<script lang="ts">
  // Storage & disks — ZFS pool fill on opti (from the latest doctor report) plus
  // per-host OS disk usage (from the latest hardware report). Reads
  // /api/runners/homelab-doctor-latest and /api/runners/hardware-latest (both
  // 5min cadence, 15s timeout) — presentation, not new collection.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, Pill, Meter } from '$lib/widgets/kit';
  import { useRunnerReport } from '$lib/api/queries';
  import { toneFor } from '$lib/format';

  let { options: _options = {} }: WidgetProps = $props();

  const doctor = useRunnerReport(() => 'homelab-doctor-latest');
  const hardware = useRunnerReport(() => 'hardware-latest');

  let opti = $derived(doctor.data?.hosts?.find((h) => h.host === 'opti'));
  let pool = $derived(
    (opti?.metrics as any)?.pool as
      | { used_pct?: number; size_gb?: number; free_gb?: number; pool_name?: string }
      | undefined,
  );

  let diskRows = $derived(
    (hardware.data?.hosts ?? [])
      .map((h) => ({ host: h.host, d: ((h.metrics as any)?.disks ?? [])[0] }))
      .filter((r) => r.d),
  );
</script>

{#snippet metaPill()}
  <Pill>opti</Pill>
{/snippet}

<WidgetFrame title="Storage & disks" head={metaPill}>
  {#if pool}
    <div class="big-metric">{Math.round(pool.used_pct ?? 0)}%<small> {pool.pool_name ?? 'pool'}</small></div>
    <Meter pct={pool.used_pct ?? null} />
    <div class="t-dim">
      {pool.free_gb != null ? `${Math.round(pool.free_gb)} GB free` : ''}
      {pool.size_gb != null ? ` of ${Math.round(pool.size_gb)} GB` : ''}
    </div>
  {:else}
    <WidgetError message="no pool data in the latest doctor report" />
  {/if}
  <div class="kv-rows">
    {#each diskRows as r (r.host)}
      <div class="kv-row">
        <span>{r.host}</span>
        <span class={`t-${toneFor(r.d.used_pct) || 'dim'}`}>{r.d.used_pct}%{r.d.size_gb ? ` of ${Math.round(r.d.size_gb)} GB` : ''}</span>
      </div>
    {/each}
  </div>
</WidgetFrame>
