<script lang="ts">
  // Host metrics: last hour from Pertal (15s), longer ranges from homelab-db.
  import LineChart from './LineChart.svelte';
  import { api } from '$lib/api';
  import { bytes } from '$lib/format';

  // `pool`: the host has a ZFS pool, so it gets a pool chart beside its root disk.
  let { host, pool = false }: { host: string; pool?: boolean } = $props();
  const ranges = ['1h', '24h', '7d', '30d', '90d'] as const;
  let range = $state<(typeof ranges)[number]>('1h');

  const percent = (v: number) => `${Math.round(v)}%`;
  const charts = $derived([
    { metric: 'cpu_pct', label: 'CPU', max: 100, fmt: percent, color: 'var(--chart-1)' },
    { metric: 'mem_pct', label: 'Memory', max: 100, fmt: percent, color: 'var(--chart-2)' },
    { metric: 'root_pct', label: 'Root disk', max: 100, fmt: percent, color: 'var(--chart-5)' },
    ...(pool ? [{ metric: 'pool_pct', label: 'ZFS pool', max: 100, fmt: percent, color: 'var(--chart-6)' }] : []),
    { metric: 'temp_c', label: 'Temperature', max: null, fmt: (v: number) => `${Math.round(v)}°`, color: 'var(--chart-3)' },
    { metric: 'rx_bps', label: 'Network in', max: null, fmt: (v: number) => `${bytes(v)}/s`, color: 'var(--chart-4)' },
  ]);

  type Series = { points: [number, number | null][]; source?: string; error?: string };
  let data = $state<Record<string, Series>>({});
  let loading = $state(false);

  async function load() {
    loading = true;
    const results = await Promise.all(charts.map(async (c) => {
      try {
        const s = await api.metrics(host, c.metric, range);
        return [c.metric, { points: s.points, source: s.source }] as const;
      } catch (e) {
        return [c.metric, { points: [], error: (e as Error).message }] as const;
      }
    }));
    data = Object.fromEntries(results);
    loading = false;
  }

  $effect(() => { void host; void range; void load(); });
  $effect(() => {
    if (range !== '1h') return;
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  });
  const source = $derived(Object.values(data).find((d) => d.source)?.source ?? '');
</script>

<div class="head">
  <div class="seg" role="group" aria-label="Range">
    {#each ranges as r}<button aria-pressed={range === r} onclick={() => (range = r)}>{r}</button>{/each}
  </div>
  <span class="faint src">{loading ? 'loading…' : source}</span>
</div>

<div class="grid">
  {#each charts as c (c.metric)}
    <section class="panel">
      <div class="panel-head"><h2>{c.label}</h2></div>
      <div class="panel-body">
        {#if data[c.metric]?.error}
          <p class="err">{data[c.metric].error}</p>
        {:else}
          <LineChart points={data[c.metric]?.points ?? []} max={c.max} format={c.fmt} color={c.color} />
        {/if}
      </div>
    </section>
  {/each}
</div>

<style>
  .head { display: flex; align-items: center; gap: var(--s3); margin-bottom: var(--s3); flex-wrap: wrap; }
  .src { font-size: var(--fs-xs); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: var(--s3); }
  .err { margin: 0; color: var(--warn); font-size: var(--fs-sm); }
  @media (max-width: 720px) { .grid { grid-template-columns: minmax(0, 1fr); } }
</style>
