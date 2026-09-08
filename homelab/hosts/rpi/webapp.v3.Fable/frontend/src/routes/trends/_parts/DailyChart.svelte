<script lang="ts">
  // Daily-resolution line (one point per doctor snapshot) with a min/max axis and
  // a date-span caption. No crosshair — at 30 points the caption says enough.
  let {
    series,
    color,
    unit,
    label,
  }: {
    series: { x: string; y: number }[];
    color: string;
    unit: string;
    label: string;
  } = $props();

  const W = 600, H = 120, PAD = 4;

  let ys = $derived(series.map((p) => p.y));
  let min = $derived(ys.length ? Math.min(...ys) : 0);
  let max = $derived(ys.length ? Math.max(...ys) : 0);
  let span = $derived(max - min || 1);
  let step = $derived(W / Math.max(1, series.length - 1));
  let d = $derived(series.map((p, i) =>
    `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${(H - PAD - ((p.y - min) / span) * (H - PAD * 2)).toFixed(1)}`).join(' '));
</script>

{#if series.length > 0}
  <div class="chart daily">
    <svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label={label}>
      <path {d} fill="none" stroke={color} stroke-width="1.5" vector-effect="non-scaling-stroke" />
    </svg>
    <div class="chart-axis">
      <span>{max.toFixed(1)}{unit}</span>
      <span>{min.toFixed(1)}{unit}</span>
    </div>
    <div class="t-dim">{series[0].x} → {series.at(-1)!.x} · {label}</div>
  </div>
{/if}

<style>
  /* the shared .chart grammar fixes svg height at 140px; the daily chart is 120px tall */
  .chart.daily svg { height: 120px; }
</style>
