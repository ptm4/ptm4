<script lang="ts">
  // Trends — the metrics explorer. Three data sources, one grammar:
  //  1) live vitals (30s ring buffer on rpi, up to 48h) — one overlay chart per
  //     metric, one line per toggled host, built by calling useVitalsRange once
  //     per host (fixed accessors) and filtering which lines render by toggle.
  //  2) long range (homelab.db on opti, 30-min resolution back to June 2026) —
  //     same overlay chart, honest "unavailable" when opti is down (retry: 0).
  //  3) daily pool/disk (doctor snapshots via /api/trends) — unchanged from v1.
  // Metric + range + host toggles round-trip through the URL (?m=&r=&h=) so a
  // view is bookmarkable; first load falls back to localStorage, then defaults.
  import { createQuery } from '@tanstack/svelte-query';
  import { get, ApiError } from '$lib/api/client';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { useVitalsRange, VITALS_RANGES, type VitalsRange } from '$lib/api/queries';
  import { Sparkline } from '$lib/widgets/kit';
  import OverlayChart from './_parts/OverlayChart.svelte';
  import DailyChart from './_parts/DailyChart.svelte';
  import {
    VITALS_METRICS, HOSTS, type MetricKey, colorForHost, fmtVitals, fmtDelta,
    HLDB_METRICS, LR_DAYS, fmtHldb, alignSeries,
  } from './_parts/metrics';

  interface TrendsResp {
    days: number;
    pool: { date: string; used_pct: number; pool_name: string | null }[];
    disks: Record<string, { date: string; used_pct: number }[]>;
  }

  interface HldbPoint { at: string; value: number | null }
  interface HldbResp { metric?: string; days?: number; series?: { host: string; points: HldbPoint[] }[] }

  // ── deep-link state: metric / range / hosts live in ?m=&r=&h= ─────────────
  const M_KEY = 'trends-metric';
  const R_KEY = 'trends-range';
  const H_KEY = 'trends-hosts';
  const isMetric = (v: unknown): v is MetricKey => VITALS_METRICS.some((m) => m.key === v);
  const isRange = (v: unknown): v is VitalsRange => (VITALS_RANGES as readonly string[]).includes(v as string);
  const validHosts = (list: string[]) => list.filter((h) => (HOSTS as readonly string[]).includes(h));

  function initMetric(): MetricKey {
    const q = page.url.searchParams.get('m');
    if (isMetric(q)) return q;
    try { const v = localStorage.getItem(M_KEY); if (isMetric(v)) return v; } catch { /* private mode */ }
    return 'cpu_pct';
  }
  function initRange(): VitalsRange {
    const q = page.url.searchParams.get('r');
    if (isRange(q)) return q;
    try { const v = localStorage.getItem(R_KEY); if (isRange(v)) return v; } catch { /* private mode */ }
    return '1h';
  }
  function initHosts(): string[] {
    const q = page.url.searchParams.get('h');
    if (q) { const list = validHosts(q.split(',').map((s) => s.trim())); if (list.length) return list; }
    try {
      const v = localStorage.getItem(H_KEY);
      if (v) { const list = validHosts(JSON.parse(v)); if (list.length) return list; }
    } catch { /* private mode */ }
    return [...HOSTS];
  }

  let metric = $state<MetricKey>(initMetric());
  let range = $state<VitalsRange>(initRange());
  let selectedHosts = $state<string[]>(initHosts());

  // Host + range + metric survive reloads (localStorage) and are shareable (URL).
  function persist() {
    try {
      localStorage.setItem(M_KEY, metric);
      localStorage.setItem(R_KEY, range);
      localStorage.setItem(H_KEY, JSON.stringify(selectedHosts));
    } catch { /* private mode */ }
    const url = new URL(page.url);
    url.searchParams.set('m', metric);
    url.searchParams.set('r', range);
    url.searchParams.set('h', selectedHosts.join(','));
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function setMetric(m: MetricKey) { metric = m; persist(); }
  function setRange(r: VitalsRange) { range = r; persist(); }
  function toggleHost(h: string) {
    if (selectedHosts.includes(h)) {
      if (selectedHosts.length === 1) return; // always leave at least one host on
      selectedHosts = selectedHosts.filter((x) => x !== h);
    } else {
      selectedHosts = HOSTS.filter((x) => selectedHosts.includes(x) || x === h);
    }
    persist();
  }

  // ── live vitals: one fixed-host query each; toggles only filter rendering ──
  const seriesRpi = useVitalsRange(() => 'rpi', () => range);
  const seriesOpti = useVitalsRange(() => 'opti', () => range);
  const seriesNn = useVitalsRange(() => 'noblenumbat', () => range);
  const HOST_Q = { rpi: seriesRpi, opti: seriesOpti, noblenumbat: seriesNn } as const;
  const hostQuery = (h: string) => HOST_Q[h as keyof typeof HOST_Q];

  let metricMeta = $derived(VITALS_METRICS.find((m) => m.key === metric)!);
  let liveLoading = $derived(selectedHosts.every((h) => hostQuery(h).isLoading));
  let liveErrors = $derived(
    selectedHosts
      .map((h) => ({ h, q: hostQuery(h) }))
      .filter(({ q }) => q.isError || q.data?.error)
      .map(({ h, q }) => `${h}: ${q.isError ? ((q.error as Error)?.message ?? 'backend unreachable') : q.data?.error}`),
  );
  let liveAligned = $derived(alignSeries(
    selectedHosts.map((h) => ({
      host: h,
      points: (hostQuery(h).data?.samples ?? []).map((s) => ({ t: s.t, v: s[metric] })),
    })),
  ));
  let liveSeries = $derived(selectedHosts.map((h) => ({
    key: h, label: h, color: colorForHost(h), values: liveAligned.byHost[h] ?? [],
  })));
  let liveLongRange = $derived(range === '24h' || range === '48h');

  // ── quick stats: current / 1h delta / peak-in-range, per selected host ─────
  function hostStats(h: string) {
    const samples = hostQuery(h).data?.samples ?? [];
    const withVal = samples.filter((s) => s[metric] != null);
    if (!withVal.length) return { current: null as number | null, delta: null as number | null, peak: null as number | null };
    const latest = withVal[withVal.length - 1];
    const current = latest[metric] as number;
    const targetT = latest.t - 3600;
    let base: number | null = null;
    for (let i = withVal.length - 1; i >= 0; i--) {
      if (withVal[i].t <= targetT) { base = withVal[i][metric] as number; break; }
    }
    if (base == null) base = withVal[0][metric] as number;
    const peak = Math.max(...withVal.map((s) => s[metric] as number));
    return { current, delta: current - base, peak };
  }
  let quickStats = $derived(selectedHosts.map((h) => ({ host: h, ...hostStats(h) })));

  // ── long range (homelab.db, reached through opti) ──────────────────────────
  const LR_M_KEY = 'trends-lr-metric';
  const LR_D_KEY = 'trends-lr-days';
  const isLrMetric = (v: unknown): v is string => HLDB_METRICS.some((m) => m.key === v);
  const isLrDays = (v: unknown): v is number => (LR_DAYS as readonly number[]).includes(v as number);

  let lrMetric = $state<string>((() => {
    try { const v = localStorage.getItem(LR_M_KEY); if (isLrMetric(v)) return v as string; } catch { /* private mode */ }
    return 'pool_used_pct';
  })());
  let lrDays = $state<number>((() => {
    try { const v = Number(localStorage.getItem(LR_D_KEY)); if (isLrDays(v)) return v; } catch { /* private mode */ }
    return 30;
  })());
  function setLrMetric(m: string) { lrMetric = m; try { localStorage.setItem(LR_M_KEY, m); } catch { /* private mode */ } }
  function setLrDays(d: number) { lrDays = d; try { localStorage.setItem(LR_D_KEY, String(d)); } catch { /* private mode */ } }

  const longRangeQ = createQuery(() => ({
    queryKey: ['hldb-metrics', lrMetric, lrDays],
    queryFn: () => get<HldbResp>(`/api/hldb/metrics?metric=${lrMetric}&days=${lrDays}`, 20_000),
    refetchInterval: 30 * 60_000,
    retry: 0,
  }));

  let lrMeta = $derived(HLDB_METRICS.find((m) => m.key === lrMetric)!);
  let lrErrorMsg = $derived.by(() => {
    if (!longRangeQ.isError) return null;
    const e = longRangeQ.error;
    if (e instanceof ApiError) {
      const hint = e.body && typeof e.body === 'object' && 'hint' in (e.body as object)
        ? String((e.body as Record<string, unknown>).hint) : null;
      return hint ? `${e.message} — ${hint}` : e.message;
    }
    return (e as Error)?.message ?? 'homelab.db unavailable (opti down or not configured)';
  });
  let lrHostPoints = $derived(
    (longRangeQ.data?.series ?? [])
      .filter((s) => selectedHosts.includes(s.host))
      .map((s) => ({
        host: s.host,
        points: s.points
          .map((p) => ({ t: Math.floor(Date.parse(p.at) / 1000), v: p.value }))
          .filter((p) => !Number.isNaN(p.t)),
      }))
      .filter((s) => s.points.length > 1),
  );
  let lrAligned = $derived(alignSeries(lrHostPoints));
  let lrSeries = $derived(lrHostPoints.map((s) => ({
    key: s.host, label: s.host, color: colorForHost(s.host), values: lrAligned.byHost[s.host] ?? [],
  })));

  // ── daily pool/disk (unchanged behaviour, ported as-is) ────────────────────
  const daily = createQuery(() => ({
    queryKey: ['trends', 30],
    queryFn: () => get<TrendsResp>('/api/trends?days=30', 15_000),
    refetchInterval: 10 * 60_000,
  }));
  let diskEntries = $derived(Object.entries(daily.data?.disks ?? {}));
  const dayEpoch = (date: string) => {
    const t = Date.parse(date);
    return Number.isNaN(t) ? null : Math.floor(t / 1000);
  };
</script>

<div class="trends-page">
  <div class="shead">
    <h1>Metrics explorer</h1>
    <span class="meta">live vitals · homelab.db long range · daily doctor snapshots</span>
  </div>

  <div class="chips host-toggles" role="group" aria-label="Hosts">
    {#each HOSTS as h (h)}
      <button type="button" class="chip act" class:active={selectedHosts.includes(h)} onclick={() => toggleHost(h)}>
        <span class="host-dot" style="background:{colorForHost(h)}"></span>{h}
      </button>
    {/each}
  </div>

  <section class="card">
    <div class="divider">Live vitals</div>
    <div class="board-bar">
      <div class="seg wrap" role="group" aria-label="Metric">
        {#each VITALS_METRICS as m (m.key)}
          <button type="button" class="seg-btn" class:active={m.key === metric} onclick={() => setMetric(m.key)}>{m.label}</button>
        {/each}
      </div>
      <span class="spacer"></span>
      <div class="seg" role="group" aria-label="Range">
        {#each VITALS_RANGES as r (r)}
          <button type="button" class="seg-btn" class:active={r === range} onclick={() => setRange(r)}>{r}</button>
        {/each}
      </div>
    </div>

    {#each liveErrors as msg (msg)}
      <p class="err">{msg}</p>
    {/each}
    {#if liveLoading}
      <div class="spin"></div>
    {:else}
      <OverlayChart
        times={liveAligned.times}
        series={liveSeries}
        percent={metricMeta.percent}
        fmt={(v) => fmtVitals(metric, v)}
        focusKey={selectedHosts[0] ?? null}
        longRange={liveLongRange}
        emptyMessage="not enough samples yet — the poller keeps 6h+ at 30s intervals and fills in as it runs"
      />
    {/if}
  </section>

  <section class="card">
    <div class="w-head">
      <span class="w-title">Quick stats</span>
      <span class="w-meta">{metricMeta.label} · {range}</span>
    </div>
    {#if quickStats.length === 0}
      <p class="empty">Toggle a host on to see its stats.</p>
    {:else}
      <div class="tablewrap">
        <table class="t">
          <thead>
            <tr><th>Host</th><th>Current</th><th>1h Δ</th><th>Peak</th></tr>
          </thead>
          <tbody>
            {#each quickStats as s (s.host)}
              <tr>
                <td><span class="host-dot" style="background:{colorForHost(s.host)}"></span>{s.host}</td>
                <td class="num">{fmtVitals(metric, s.current)}</td>
                <td class="num">{fmtDelta(metric, s.delta)}</td>
                <td class="num">{fmtVitals(metric, s.peak)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section class="card">
    <div class="divider">Long range · homelab.db</div>
    <div class="board-bar">
      <div class="seg wrap" role="group" aria-label="Long-range metric">
        {#each HLDB_METRICS as m (m.key)}
          <button type="button" class="seg-btn" class:active={m.key === lrMetric} onclick={() => setLrMetric(m.key)}>{m.label}</button>
        {/each}
      </div>
      <span class="spacer"></span>
      <div class="seg" role="group" aria-label="Days">
        {#each LR_DAYS as d (d)}
          <button type="button" class="seg-btn" class:active={d === lrDays} onclick={() => setLrDays(d)}>{d}d</button>
        {/each}
      </div>
    </div>

    {#if lrErrorMsg}
      <p class="err">{lrErrorMsg}</p>
    {:else if longRangeQ.isLoading}
      <div class="spin"></div>
    {:else}
      <OverlayChart
        times={lrAligned.times}
        series={lrSeries}
        percent={lrMeta.percent}
        fmt={(v) => fmtHldb(lrMeta.unit, v)}
        focusKey={selectedHosts[0] ?? null}
        longRange
        emptyMessage={`No history for ${lrMeta.label} yet.`}
      />
    {/if}
  </section>

  <section class="card">
    <div class="divider">Daily pool / disk</div>
    <div class="w-head">
      <span class="w-title">Storage over time</span>
      <span class="w-meta">{daily.data?.days ?? 0} days of doctor snapshots</span>
    </div>
    {#if daily.isError}
      <p class="err">Cannot reach /api/trends — {(daily.error as Error)?.message ?? 'backend unreachable'}</p>
    {:else if daily.isLoading}
      <div class="spin"></div>
    {:else if (daily.data?.pool.length ?? 0) > 1}
      {@const pool = daily.data!.pool}
      <DailyChart
        series={pool.map((p) => ({ x: p.date, y: p.used_pct }))}
        color="var(--c-storage)"
        unit="%"
        label={`pool ${pool.at(-1)?.pool_name ?? ''}`}
      />
    {:else}
      <p class="empty">No pool history yet.</p>
    {/if}
    <div class="kv-rows">
      {#each diskEntries as [h, rows] (h)}
        <div class="kv-row disk-row">
          <span>{h} disk</span>
          {#if rows.length > 1}
            <span class="disk-spark">
              <Sparkline values={rows.map((r) => r.used_pct)} times={rows.map((r) => dayEpoch(r.date))}
                width={120} height={22} showDay label={`${h} disk used %`} format={(v) => `${v.toFixed(1)}%`} />
            </span>
          {/if}
          <span>{rows.at(-1)?.used_pct ?? '—'}%</span>
        </div>
      {/each}
    </div>
  </section>
</div>

<style>
  .host-toggles { margin-top: -2px; }
  .host-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; flex: none; }
  .chip.act.active { color: var(--ink); background: var(--accent-dim); border-color: var(--accent-muted); }
  .seg.wrap { flex-wrap: wrap; }

  /* per-host disk rows: label · 30-day sparkline · latest used % */
  .disk-row { align-items: center; }
  .disk-spark { flex: 0 0 120px; color: var(--c-storage); }
  .kv-row.disk-row > span:last-child { flex: 0 0 auto; }
</style>
