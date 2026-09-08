<script lang="ts">
  // Port of DbHealthWidget from webapp.v2.legacy/frontend/src/widgets/hldb.tsx.
  // Backed by homelab.db on opti (routes/hldb.js -> :9100); opti is a single
  // point of failure so this renders an honest "unavailable" state (retry: 0)
  // rather than an error boundary when the upstream is down. Watches the thing
  // that watches everything else: a feed that quietly stops looks exactly like
  // a quiet homelab, which is the failure this makes loud.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Pill } from '$lib/widgets/kit';

  interface Dataset {
    id: string; label: string; stage: string; producer_host?: string | null;
    source: string; cadence_hours?: number | null; consumers?: string | null;
    notes?: string | null; last_source_at?: string | null; last_error?: string | null;
    age_hours?: number | null; stale?: boolean;
  }
  interface DataplaneResp {
    datasets?: Dataset[];
    database?: {
      history_from?: string; history_to?: string; runs?: number;
      rows?: Record<string, number>; schema_version?: number;
    };
  }

  const UNAVAILABLE = 'homelab-db unavailable (opti down or not configured)';

  let { options: _options = {} }: WidgetProps = $props();

  const q = createQuery(() => ({
    queryKey: ['hldb-dataplane'],
    queryFn: () => get<DataplaneResp>('/api/hldb/dataplane', 20_000),
    refetchInterval: 5 * 60_000,
    retry: 0,
  }));

  let datasets = $derived(q.data?.datasets ?? []);
  let db = $derived(q.data?.database);
  let stale = $derived(datasets.filter((d) => d.stale || d.last_error));
  let feeds = $derived(datasets.filter((d) => d.cadence_hours));
  let totalRows = $derived(Object.values(db?.rows ?? {}).reduce((a, b) => a + b, 0));
</script>

{#snippet dataFlowsLink()}
  <a class="w-meta" href="/data">data flows →</a>
{/snippet}

{#if q.isError}
  <WidgetFrame title="Homelab DB">
    <WidgetError message={UNAVAILABLE} />
  </WidgetFrame>
{:else}
  <WidgetFrame title="Homelab DB" head={dataFlowsLink} scroll>
    {#if q.isLoading}
      <WidgetLoading />
    {/if}
    {#if !q.isLoading}
      <div class="kv-rows">
        <div class="kv-row">
          <span>Feeds</span>
          <span>
            {#if stale.length === 0}
              <Pill tone="ok">{feeds.length} fresh</Pill>
            {:else}
              <Pill tone="warn">{stale.length} of {feeds.length} stale</Pill>
            {/if}
          </span>
        </div>
        <div class="kv-row">
          <span>Indexed</span>
          <span>{totalRows.toLocaleString()} rows</span>
        </div>
        <div class="kv-row">
          <span>History</span>
          <span class="t-dim">{db?.history_from ?? '—'} → {db?.history_to ?? '—'}</span>
        </div>
      </div>
      {#if stale.length > 0}
        <div class="kv-rows">
          {#each stale as d (d.id)}
            <div class="kv-row">
              <span class="mono">{d.id}</span>
              <span class="t-dim">
                {#if d.last_error}
                  {d.last_error.slice(0, 60)}
                {:else}
                  {relTime(d.last_source_at)} (expects {d.cadence_hours}h)
                {/if}
              </span>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </WidgetFrame>
{/if}
