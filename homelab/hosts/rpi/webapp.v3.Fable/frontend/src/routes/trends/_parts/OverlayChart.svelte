<script lang="ts">
  // Multi-host overlay line chart: one path per series on a shared time axis,
  // a legend with latest/min/max/avg per series, a crosshair that reads every
  // series at once, and an area fill under the focused series only. Nulls
  // break a series' path — a gap is "we don't know", never interpolated.
  let {
    times,
    series,
    percent = false,
    fmt = (v: number) => `${Math.round(v * 10) / 10}`,
    focusKey = null,
    longRange = false,
    height = 220,
    emptyMessage = 'not enough samples yet',
  }: {
    /** epoch seconds, ascending, shared by every series */
    times: number[];
    series: { key: string; label: string; color: string; values: (number | null)[] }[];
    /** clamp the y domain to 0–100 instead of padding around the data */
    percent?: boolean;
    fmt?: (v: number) => string;
    /** which series gets the area fill under its line (defaults to the first) */
    focusKey?: string | null;
    /** include month/day in hover + axis time labels — for ranges spanning days */
    longRange?: boolean;
    height?: number;
    emptyMessage?: string;
  } = $props();

  const PAD = 8;
  let H = $derived(height);

  let containerWidth = $state(600);
  let W = $derived(Math.max(containerWidth, 120));
  let step = $derived(W / Math.max(1, times.length - 1));

  let totalPresent = $derived(series.reduce((n, s) => n + s.values.filter((v) => v != null).length, 0));

  const clampPct = (v: number) => (percent ? Math.max(0, Math.min(100, v)) : v);

  let allPresent = $derived(series.flatMap((s) => s.values).filter((v): v is number => v != null).map(clampPct));
  let domain = $derived.by(() => {
    if (percent) return { min: 0, max: 100 };
    if (!allPresent.length) return { min: 0, max: 1 };
    let lo = Math.min(...allPresent);
    let hi = Math.max(...allPresent);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08;
    // Headroom shouldn't invent negative territory for metrics that never go
    // negative in reality (bps, load, temp) just because the padding is generous.
    const min = lo >= 0 ? Math.max(0, lo - pad) : lo - pad;
    return { min, max: hi + pad };
  });
  let yMin = $derived(domain.min);
  let yMax = $derived(domain.max);
  let ySpan = $derived(yMax - yMin || 1);
  const yFor = (v: number) => H - PAD - ((clampPct(v) - yMin) / ySpan) * (H - PAD * 2);

  function buildSegments(values: (number | null)[]): string[] {
    const out: string[] = [];
    let cur: string[] = [];
    values.forEach((v, i) => {
      if (v == null) {
        if (cur.length > 1) out.push(cur.join(' '));
        cur = [];
        return;
      }
      cur.push(`${cur.length ? 'L' : 'M'}${(i * step).toFixed(1)},${yFor(v).toFixed(1)}`);
    });
    if (cur.length > 1) out.push(cur.join(' '));
    return out;
  }

  let seriesSegs = $derived(series.map((s) => buildSegments(s.values)));

  let focusSeries = $derived(series.find((s) => s.key === focusKey) ?? series[0] ?? null);
  let focusIdx = $derived(focusSeries ? series.indexOf(focusSeries) : -1);
  let focusAreaPaths = $derived.by(() => {
    if (focusIdx < 0) return [];
    const baseline = (H - PAD).toFixed(1);
    return seriesSegs[focusIdx].map((seg) => {
      const parts = seg.split(' ');
      const firstX = parts[0].slice(1).split(',')[0];
      const lastX = parts.at(-1)!.replace('L', '').split(',')[0];
      return `${seg} L${lastX},${baseline} L${firstX},${baseline} Z`;
    });
  });

  // 4 evenly-spaced gridlines/labels from max down to min.
  let yTicks = $derived([0, 1, 2, 3].map((i) => yMax - (ySpan * i) / 3));

  // 5 evenly-spaced time labels (fewer if there aren't 5 distinct samples).
  let xTickIdx = $derived.by(() => {
    const n = times.length;
    if (n === 0) return [];
    if (n <= 5) return times.map((_, i) => i);
    return [...new Set([0, Math.round((n - 1) * 0.25), Math.round((n - 1) * 0.5), Math.round((n - 1) * 0.75), n - 1])];
  });

  function timeLabel(t: number): string {
    return new Date(t * 1000).toLocaleString([], {
      ...(longRange ? { month: 'short', day: 'numeric' } : {}),
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  let hover = $state<number | null>(null);
  function onMove(e: PointerEvent) {
    const n = times.length;
    if (!n) { hover = null; return; }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    hover = Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1))));
  }
  let hoverLeftPct = $derived(hover != null ? Math.min(80, Math.max(4, ((hover * step) / W) * 100)) : 0);
  let hoverTimeLabel = $derived(hover != null ? timeLabel(times[hover]) : '');

  let seriesStats = $derived(series.map((s) => {
    const present = s.values.filter((v): v is number => v != null);
    let latest: number | null = null;
    for (let i = s.values.length - 1; i >= 0; i--) { if (s.values[i] != null) { latest = s.values[i]; break; } }
    const min = present.length ? Math.min(...present) : null;
    const max = present.length ? Math.max(...present) : null;
    const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
    return { ...s, latest, min, max, avg };
  }));
</script>

{#if totalPresent < 2}
  <div class="empty">{emptyMessage}</div>
{:else}
  <div class="ov-row">
    <div class="y-ticks" style="height:{H}px">
      {#each yTicks as yt, i (i)}
        <span style="top:{((yFor(yt)) / H) * 100}%">{fmt(yt)}</span>
      {/each}
    </div>
    <div class="chart-col" bind:clientWidth={containerWidth}>
      <div
        class="chart overlay"
        role="img"
        aria-label="metric overlay chart"
        onpointermove={onMove}
        onpointerleave={() => (hover = null)}
      >
        <svg viewBox="0 0 {W} {H}" style="height:{H}px" preserveAspectRatio="none" aria-hidden="true">
          {#each yTicks as yt, i (i)}
            <line x1="0" y1={yFor(yt).toFixed(1)} x2={W} y2={yFor(yt).toFixed(1)} class="gridline" />
          {/each}
          {#if focusSeries}
            {#each focusAreaPaths as d, i (i)}
              <path {d} fill={focusSeries.color} fill-opacity="0.12" stroke="none" />
            {/each}
          {/if}
          {#each series as s, si (s.key)}
            {#each seriesSegs[si] as d, i (i)}
              <path {d} fill="none" stroke={s.color} stroke-width="1.5" vector-effect="non-scaling-stroke" />
            {/each}
          {/each}
          {#if hover != null}
            <line
              x1={(hover * step).toFixed(1)} y1="0" x2={(hover * step).toFixed(1)} y2={H}
              class="crosshair" vector-effect="non-scaling-stroke"
            />
          {/if}
        </svg>
        {#if hover != null}
          <div class="ov-tip" style="left: {hoverLeftPct}%">
            <b>{hoverTimeLabel}</b>
            {#each series as s (s.key)}
              <div class="ov-tip-row">
                <span class="tip-dot" style="background:{s.color}"></span>{s.label}: {s.values[hover] != null ? fmt(s.values[hover]!) : '—'}
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div class="x-ticks">
        {#each xTickIdx as idx (idx)}
          <span style="left: {times.length > 1 ? (idx / (times.length - 1)) * 100 : 0}%">{timeLabel(times[idx])}</span>
        {/each}
      </div>
    </div>
  </div>

  <div class="legend">
    {#each seriesStats as s (s.key)}
      <div class="legend-item">
        <span class="legend-dot" style="background:{s.color}"></span>
        <span class="legend-label">{s.label}</span>
        <span class="legend-vals">
          <b>{s.latest != null ? fmt(s.latest) : '—'}</b>
          <span class="faint">min {s.min != null ? fmt(s.min) : '—'} · max {s.max != null ? fmt(s.max) : '—'} · avg {s.avg != null ? fmt(s.avg) : '—'}</span>
        </span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .ov-row { position: relative; display: flex; gap: 6px; align-items: stretch; }
  .y-ticks { position: relative; flex: 0 0 auto; width: 42px; }
  .y-ticks span {
    position: absolute; left: 0; right: 6px; transform: translateY(-50%);
    font-size: var(--fs-xs); color: var(--ink-3); font-variant-numeric: tabular-nums;
    text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .chart-col { flex: 1; min-width: 0; }
  .chart.overlay { cursor: crosshair; }
  .crosshair { stroke: var(--ink-2); stroke-opacity: .55; stroke-width: 1; }

  .ov-tip {
    position: absolute; top: 4px; transform: translateX(-30%);
    padding: 4px 8px; border-radius: var(--r-sm);
    background: var(--surface-2); border: 1px solid var(--border-2);
    color: var(--ink); font-size: var(--fs-xs); font-variant-numeric: tabular-nums;
    white-space: nowrap; pointer-events: none; z-index: 5; line-height: 1.55;
  }
  .ov-tip-row { display: flex; align-items: center; gap: 5px; }

  .x-ticks { position: relative; height: 15px; margin-top: 2px; }
  .x-ticks span {
    position: absolute; transform: translateX(-50%); white-space: nowrap;
    font-size: var(--fs-xs); color: var(--ink-3); font-variant-numeric: tabular-nums;
  }
  .x-ticks span:first-child { transform: translateX(0); }
  .x-ticks span:last-child { transform: translateX(-100%); }

  .legend { display: flex; flex-wrap: wrap; gap: var(--s3); margin-top: var(--s3); }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); }
  .legend-dot, .tip-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
  .legend-vals { display: flex; flex-direction: column; gap: 1px; }
  .legend-vals b { font-variant-numeric: tabular-nums; }
  .legend-vals .faint { font-size: var(--fs-xs); }
</style>
