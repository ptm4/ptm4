<script lang="ts">
  // CS2 / Leetify — dimension snapshot plus a rating sparkline over recent
  // runs. Ported from v2 LeetifyTrendWidget
  // (webapp.v2.legacy/frontend/src/widgets/integrations.tsx).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Sparkline } from '$lib/widgets/kit';
  import { createQuery, createQueries } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';

  // No configurable options for this widget (see registry.ts 'leetify-trend' entry).
  let {}: WidgetProps = $props();

  interface LeetifyHistory { history: { date: string }[] }
  interface LeetifyLatest { dimensions?: Record<string, number>; summary?: string; maps?: unknown[] }
  interface LeetifySnap { dimensions?: Record<string, number> }

  const latest = createQuery(() => ({
    queryKey: ['runner-report', 'leetify-latest'],
    queryFn: () => get<LeetifyLatest>('/api/runners/leetify-latest', 15_000),
    retry: 0,
  }));
  const history = createQuery(() => ({
    queryKey: ['history', 'leetify-latest'],
    queryFn: () => get<LeetifyHistory>('/api/runners/leetify-latest/history', 15_000),
    retry: 0,
  }));

  // Rating over time needs the dated snapshots; fetch the last 14 and read their
  // aim dimension (the one that moves and the one the coach keys on).
  let dates = $derived((history.data?.history ?? []).slice(0, 14).map((h) => h.date).reverse());
  const snaps = createQueries(() => ({
    queries: dates.map((d) => ({
      queryKey: ['leetify-snap', d],
      queryFn: () => get<LeetifySnap>(`/api/runners/leetify-latest/report/${d}`, 15_000),
      staleTime: 6 * 3600_000,
      retry: 0,
    })),
  }));

  let series = $derived(snaps.map((s) => {
    const dims = s.data?.dimensions ?? {};
    const key = Object.keys(dims).find((k) => /aim/i.test(k)) ?? Object.keys(dims)[0];
    return key ? (dims[key] ?? null) : null;
  }));
  let dims = $derived(latest.data?.dimensions ?? {});
  let dimEntries = $derived(Object.entries(dims).slice(0, 3));
  let showSpark = $derived(series.filter((v) => v != null).length > 1);
</script>

{#snippet detailsLink()}
  <a href="/leetify">details →</a>
{/snippet}

{#if latest.isError}
  <WidgetFrame title="CS2"><WidgetError message="no Leetify report yet" /></WidgetFrame>
{:else}
  <WidgetFrame title="CS2 / Leetify" head={detailsLink}>
    {#if latest.isLoading}
      <WidgetLoading />
    {/if}
    <div class="dim-strip">
      {#each dimEntries as [k, v] (k)}
        <div class="dim" data-s={v >= 60 ? 'strong' : v < 52 ? 'focus' : 'ok'}>
          <span class="dim-name">{k}</span>
          <span class="dim-val">{Math.round(v)}</span>
        </div>
      {/each}
    </div>
    {#if showSpark}
      <div class="spark-wrap" style="color: var(--brand)" title="trend over the last runs">
        <Sparkline values={series} label="Leetify trend" />
      </div>
    {/if}
    {#if latest.data?.summary}
      <div class="t-dim">{latest.data.summary}</div>
    {/if}
  </WidgetFrame>
{/if}
