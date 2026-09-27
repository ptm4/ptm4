<script lang="ts">
  // Minimal SVG line chart: no library, fills its container's width, gaps (null) break
  // the line instead of being drawn as zero. Hover shows the nearest point.
  let {
    points,
    max = null,
    format = (v: number) => String(Math.round(v)),
    height = 140,
    color = 'var(--chart-1)',
  }: {
    points: [number, number | null][];
    max?: number | null;
    format?: (v: number) => string;
    height?: number;
    color?: string;
  } = $props();

  let width = $state(600);
  let hover = $state<number | null>(null);

  const valid = $derived(points.filter((p) => p[1] != null) as [number, number][]);
  const t0 = $derived(points.length ? points[0][0] : 0);
  const t1 = $derived(points.length ? points[points.length - 1][0] : 1);
  const vmax = $derived(max ?? Math.max(1, ...valid.map((p) => p[1])) * 1.1);
  // Left margin sized to the widest y-axis label (≈6.5px per mono char at 10px).
  const pad = $derived({ l: Math.max(30, Math.max(...[0, vmax / 2, vmax].map((v) => format(v).length)) * 6.5 + 10), r: 8, t: 8, b: 20 });
  const x = (t: number) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / vmax) * (height - pad.t - pad.b);

  // Split into runs at gaps (null) and at time jumps > 3x the median step.
  const paths = $derived.by(() => {
    const steps = points.slice(1).map((p, i) => p[0] - points[i][0]).sort((a, b) => a - b);
    const gap = (steps[Math.floor(steps.length / 2)] || 60) * 3;
    const runs: string[] = [];
    let cur = '';
    let prevT: number | null = null;
    for (const [t, v] of points) {
      if (v == null || (prevT != null && t - prevT > gap)) { if (cur) runs.push(cur); cur = ''; }
      if (v != null) cur += `${cur ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
      prevT = t;
    }
    if (cur) runs.push(cur);
    return runs;
  });

  const ticks = $derived([0, vmax / 2, vmax]);
  const fmtTime = (t: number) => {
    const d = new Date(t * 1000);
    return t1 - t0 > 2 * 86400
      ? d.toLocaleDateString([], { month: 'short', day: 'numeric' })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  function onMove(e: PointerEvent) {
    const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
    const t = t0 + ((e.clientX - rect.left - pad.l) / (width - pad.l - pad.r)) * (t1 - t0);
    let best = -1, bd = Infinity;
    valid.forEach((p, i) => { const d = Math.abs(p[0] - t); if (d < bd) { bd = d; best = i; } });
    hover = best >= 0 ? best : null;
  }
</script>

<div class="chart" bind:clientWidth={width}>
  {#if !valid.length}
    <div class="empty" style="height:{height}px">No data for this range yet</div>
  {:else}
    <svg {width} {height} onpointermove={onMove} onpointerleave={() => (hover = null)} role="img" aria-label="Line chart">
      {#each ticks as v}
        <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} class="grid" />
        <text x={pad.l - 6} y={y(v) + 4} text-anchor="end" class="lbl">{format(v)}</text>
      {/each}
      <text x={pad.l} y={height - 4} class="lbl">{fmtTime(t0)}</text>
      <text x={width - pad.r} y={height - 4} text-anchor="end" class="lbl">{fmtTime(t1)}</text>
      {#each paths as d}<path {d} fill="none" stroke={color} stroke-width="1.6" stroke-linejoin="round" />{/each}
      {#if hover != null}
        {@const p = valid[hover]}
        <line x1={x(p[0])} x2={x(p[0])} y1={pad.t} y2={height - pad.b} class="cursor" />
        <circle cx={x(p[0])} cy={y(p[1])} r="3" fill={color} />
        <text x={Math.min(x(p[0]) + 6, width - 90)} y={pad.t + 12} class="tip">{format(p[1])} · {fmtTime(p[0])}</text>
      {/if}
    </svg>
  {/if}
</div>

<style>
  .chart { width: 100%; }
  svg { display: block; touch-action: pan-y; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .cursor { stroke: var(--ink-3); stroke-dasharray: 3 3; }
  .lbl { fill: var(--ink-3); font: 10px var(--mono); }
  .tip { fill: var(--ink); font: 11px var(--mono); }
  .empty { display: flex; align-items: center; justify-content: center; color: var(--ink-3); font-size: var(--fs-sm); }
</style>
