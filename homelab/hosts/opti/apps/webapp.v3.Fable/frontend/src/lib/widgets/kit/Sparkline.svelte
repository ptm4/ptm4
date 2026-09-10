<script lang="ts">
  // Inline SVG sparkline — port of the v1/v2 hand-rolled one. Nulls break the
  // line rather than being interpolated: a gap is the honest "we don't know".
  // Pass `times` (epoch seconds, parallel to values) to make it interactive: a
  // pointer over the chart snaps to the nearest sample and shows value + time.
  let {
    values,
    times,
    width = 120,
    height = 26,
    label,
    format,
    showDay = false,
  }: {
    values: (number | null)[];
    times?: (number | null)[];
    width?: number;
    height?: number;
    label?: string;
    format?: (v: number) => string;
    /** include the weekday in the hover time — for ranges spanning days */
    showDay?: boolean;
  } = $props();

  let hover = $state<number | null>(null);

  let present = $derived(values.filter((v): v is number => v != null));
  let min = $derived(present.length ? Math.min(...present) : 0);
  let max = $derived(present.length ? Math.max(...present) : 0);
  let span = $derived(max - min || 1);
  let step = $derived(width / Math.max(1, values.length - 1));
  const yFor = (v: number) => height - ((v - min) / span) * (height - 2) - 1;

  // Snap to the nearest sample that actually exists (gaps stay gaps).
  function snap(frac: number): number | null {
    const i = Math.max(0, Math.min(values.length - 1, Math.round(frac * (values.length - 1))));
    for (let d = 0; d < values.length; d++) {
      if (values[i - d] != null) return i - d;
      if (values[i + d] != null) return i + d;
    }
    return null;
  }

  let segments = $derived.by(() => {
    const out: string[] = [];
    let current: string[] = [];
    values.forEach((v, i) => {
      if (v == null) {
        if (current.length > 1) out.push(current.join(' '));
        current = [];
        return;
      }
      const x = (i * step).toFixed(1);
      const y = yFor(v).toFixed(1);
      current.push(`${current.length ? 'L' : 'M'}${x},${y}`);
    });
    if (current.length > 1) out.push(current.join(' '));
    return out;
  });

  // A soft fill under each run gives the line body — a bare 1.5px stroke reads
  // as a stray scratch at this size.
  let gid = $derived(`sparkfill-${(label ?? 'x').replace(/\W+/g, '')}-${Math.round(min)}-${Math.round(max)}`);

  let interactive = $derived(!!times);
  let hv = $derived(hover != null && values[hover] != null ? hover : null);
  const fmt = (v: number) => (format ?? ((x: number) => `${Math.round(x * 10) / 10}`))(v);
  const timeStr = (t: number | null | undefined) =>
    t ? new Date(t * 1000).toLocaleString([], {
      ...(showDay ? { weekday: 'short' } : {}), hour: '2-digit', minute: '2-digit',
    }) : '';

  function onMove(e: PointerEvent) {
    if (!interactive) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    hover = snap((e.clientX - rect.left) / rect.width);
  }
</script>

{#if present.length >= 2}
  <span class="spark-box" role="img" aria-label={label} onpointermove={onMove} onpointerleave={() => (hover = null)}>
    <svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="currentColor" stop-opacity="0.35" />
          <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
        </linearGradient>
      </defs>
      {#each segments as d, i (i)}
        {@const first = d.slice(1).split(' ')[0].split(',')[0]}
        {@const last = d.split(' ').at(-1)!.replace('L', '').split(',')[0]}
        <g>
          <path d="{d} L{last},{height} L{first},{height} Z" fill="url(#{gid})" stroke="none" />
          <path {d} fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
        </g>
      {/each}
      {#if hv != null}
        <line x1={hv * step} y1="0" x2={hv * step} y2={height} stroke="currentColor" stroke-opacity="0.35" stroke-width="1" vector-effect="non-scaling-stroke" />
      {/if}
    </svg>
    {#if hv != null}
      <span class="spark-dot" style="left: {(hv * step / width) * 100}%; top: {(yFor(values[hv]!) / height) * 100}%"></span>
      <span class="spark-tip" style="left: {Math.min(78, Math.max(6, (hv * step / width) * 100))}%">
        {fmt(values[hv]!)}{times?.[hv] ? ` · ${timeStr(times[hv])}` : ''}
      </span>
    {/if}
  </span>
{/if}
