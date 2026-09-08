<script lang="ts">
  // Long-range trends — port of v2 LongTrendsWidget (widgets/hldb.tsx).
  //
  // The board's host-vitals sparkline tops out at 48h (in-memory rings on rpi).
  // This reads collector_metrics from homelab.db on opti, which goes back to
  // June 2026 at 30-minute resolution. opti is a single point of failure and
  // this dashboard runs on rpi, so the widget renders an honest "unavailable"
  // state rather than an error boundary when the upstream is down — retry: 0
  // for the same reason the bot proxies use it.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { opt, type WidgetProps } from '$lib/widgets/sdk';
  import { Sparkline, WidgetError, WidgetFrame, WidgetLoading } from '$lib/widgets/kit';

  interface MetricPoint { at: string; value: number | null }
  interface MetricsResp {
    metric?: string;
    days?: number;
    series?: { host: string; points: MetricPoint[] }[];
  }

  const UNAVAILABLE = 'homelab-db unavailable (opti down or not configured)';

  const METRIC_LABEL: Record<string, string> = {
    disk_used_pct: 'Root disk used',
    pool_used_pct: 'ZFS pool used',
    mem_used_gib: 'Memory used',
    pending_count: 'Pending updates',
    gateway_avg_ms: 'Gateway latency',
    internet_avg_ms: 'Internet latency',
    containers_count: 'Containers running',
  };

  const UNIT: Record<string, string> = {
    disk_used_pct: '%', pool_used_pct: '%', mem_used_gib: ' GiB',
    gateway_avg_ms: ' ms', internet_avg_ms: ' ms',
  };

  let { options = {} }: WidgetProps = $props();

  let metric = $derived(opt(options, 'metric', 'pool_used_pct'));
  let days = $derived(Number(opt(options, 'days', 30)));
  let host = $derived(opt(options, 'host', ''));

  const q = createQuery(() => ({
    queryKey: ['hldb-metrics', metric, days, host],
    queryFn: () => get<MetricsResp>(
      `/api/hldb/metrics?metric=${metric}&days=${days}${host ? `&host=${host}` : ''}`, 20_000),
    refetchInterval: 30 * 60_000,
    retry: 0,
  }));

  let label = $derived(METRIC_LABEL[metric] || metric);
  let title = $derived(`${label} · ${days}d`);
  let unit = $derived(UNIT[metric] ?? '');

  let series = $derived((q.data?.series ?? []).filter((s) => s.points.length > 1));

  const fmt = (v: number) => `${v.toFixed(1)}${unit}`;
</script>

<WidgetFrame {title} scroll>
  {#if q.isError}
    <WidgetError message={UNAVAILABLE} />
  {:else}
    {#if q.isLoading}<WidgetLoading />{/if}
    {#if !q.isLoading && series.length === 0}
      <div class="t-dim">No history for {metric} yet.</div>
    {/if}
    {#each series as s (s.host)}
      {@const values = s.points.map((p) => p.value)}
      {@const times = s.points.map((p) => Math.floor(Date.parse(p.at) / 1000))}
      {@const last = [...values].reverse().find((v) => v != null)}
      {@const first = values.find((v) => v != null)}
      {@const delta = last != null && first != null ? last - first : null}
      <div class="kv-row">
        <span class="mono">{s.host}</span>
        <Sparkline {values} {times} showDay {label} format={fmt} />
        <span>
          {last != null ? fmt(last) : '—'}
          {#if delta != null && Math.abs(delta) >= 0.1}
            <small class="t-dim">{delta > 0 ? '+' : ''}{delta.toFixed(1)}</small>
          {/if}
        </span>
      </div>
    {/each}
  {/if}
</WidgetFrame>
