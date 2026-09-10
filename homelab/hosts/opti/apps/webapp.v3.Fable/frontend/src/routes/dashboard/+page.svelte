<script lang="ts">
  // Monitor — the homelab as one btop screen. Every graph here is text: block and
  // braille glyphs in a monospace grid, not SVG. One panel per metric, hosts as rows
  // inside it, so the outlier on any dimension is the row that looks different.
  //
  // Nothing new is collected. This is the vitals ring buffer, the architecture
  // fragments, the container list and the alert rules — the same reads the rest of
  // the app makes — rendered the way a terminal would.
  import { onMount } from 'svelte';
  import Panel from '$lib/features/tui/Panel.svelte';
  import { spark, brailleSpark, meter, pad, padEnd, rate, uptime, toneFor, loadTone, autoDomain, peak } from '$lib/features/tui/glyphs';
  import { useVitals, useVitalsRange, useContainers, useTimers, VITALS_RANGES, type VitalsRange } from '$lib/api/queries';
  import { useArchLive, useUpdates, useHosts, FALLBACK_FLEET } from '$lib/api/fleet';
  import { useRules } from '$lib/api/rules';
  import { useIncidents } from '$lib/api/incidents';
  import { sse } from '$lib/api/sse.svelte';
  import { relTime } from '$lib/format';

  // The three agent hosts. android has no agent (no vitals), tux is a workstation —
  // both appear in the fleet line but not in the per-metric graphs.
  const HOSTS = ['opti', 'rpi', 'noblenumbat'] as const;
  const SHORT: Record<string, string> = { opti: 'opti', rpi: 'rpi', noblenumbat: 'nn' };

  let range = $state<VitalsRange>('3h');
  // Graph width is measured, not guessed: a hidden ruler gives the real advance of
  // this monospace face, and the grid gives the real panel width, so the glyph runs
  // always fit their box instead of spawning a scrollbar.
  let gridW = $state(900);
  let viewW = $state(1280);
  let rulerW = $state(72);          // width of 10 '0' glyphs
  let charW = $derived(rulerW / 10 || 7.2);
  // Must track the CSS breakpoint below, not the grid width: at 1280px viewport the
  // grid is two columns even though the grid element itself is only ~1018px.
  let wide = $derived(viewW >= 1100);
  let panelW = $derived(wide ? (gridW - 12) / 2 : gridW);
  /** cells left for a graph after its label/value columns (`reserve`), the panel
   *  padding, and the flex gaps between columns (~6 cells). */
  const cells = (reserve: number) => Math.max(10, Math.floor((panelW - 24) / charW) - reserve - 6);
  let width = $derived(cells(16));

  const vitals = useVitals();
  const live = useArchLive();
  const containers = useContainers();
  const updates = useUpdates();
  const timers = useTimers();
  const rules = useRules();
  const incidents = useIncidents();
  const hostsQ = useHosts();

  // One ranged series per host — fixed accessors, so three stable queries.
  const sOpti = useVitalsRange(() => 'opti', () => range);
  const sRpi = useVitalsRange(() => 'rpi', () => range);
  const sNn = useVitalsRange(() => 'noblenumbat', () => range);
  const series: Record<string, typeof sOpti> = { opti: sOpti, rpi: sRpi, noblenumbat: sNn };

  onMount(() => {
    try {
      const r = localStorage.getItem('tui-range');
      if (r && (VITALS_RANGES as readonly string[]).includes(r)) range = r as VitalsRange;
    } catch { /* private mode */ }
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el?.tagName === 'INPUT' || el?.tagName === 'SELECT' || el?.tagName === 'TEXTAREA') return;
      const i = VITALS_RANGES.indexOf(range);
      if (e.key === '+' || e.key === '=') setRange(VITALS_RANGES[Math.min(VITALS_RANGES.length - 1, i + 1)]);
      if (e.key === '-' || e.key === '_') setRange(VITALS_RANGES[Math.max(0, i - 1)]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  function setRange(r: VitalsRange) {
    range = r;
    try { localStorage.setItem('tui-range', r); } catch { /* private mode */ }
  }

  const samplesOf = (h: string) => series[h]?.data?.samples ?? [];
  const latestOf = (h: string) => vitals.data?.hosts?.[h]?.latest ?? null;
  const errOf = (h: string) => vitals.data?.hosts?.[h]?.error ?? null;
  const liveOf = (h: string) => live.data?.hosts?.[h] ?? null;

  let fleet = $derived.by(() => {
    const rows = (containers.data?.hosts ?? []).flatMap((x) => x.containers);
    const cpu = HOSTS.map((h) => latestOf(h)?.cpu_pct).filter((v): v is number => v != null);
    const mem = HOSTS.map((h) => latestOf(h)?.mem_pct).filter((v): v is number => v != null);
    return {
      up: rows.filter((c) => c.up).length,
      total: rows.length,
      updates: rows.filter((c) => c.update_available).length,
      cpu: cpu.length ? cpu.reduce((a, b) => a + b, 0) / cpu.length : null,
      mem: mem.length ? mem.reduce((a, b) => a + b, 0) / mem.length : null,
      rx: HOSTS.reduce((n, h) => n + (latestOf(h)?.rx_bps ?? 0), 0),
      tx: HOSTS.reduce((n, h) => n + (latestOf(h)?.tx_bps ?? 0), 0),
      hostsUp: HOSTS.filter((h) => latestOf(h) && !errOf(h)).length,
    };
  });

  // Storage rows come from the daily/30-min collector reports, not the vitals ring.
  let disks = $derived.by(() => {
    const out: { host: string; label: string; pct: number | null }[] = [];
    for (const h of HOSTS) {
      const lv = liveOf(h);
      if (lv?.pool?.used_pct != null) out.push({ host: h, label: lv.pool.pool_name ?? 'pool', pct: lv.pool.used_pct });
      if (lv?.disk_used_pct != null) out.push({ host: h, label: 'root', pct: lv.disk_used_pct });
    }
    return out;
  });

  let containersByHost = $derived.by(() =>
    (containers.data?.hosts ?? []).map((x) => ({
      host: x.host,
      up: x.containers.filter((c) => c.up).length,
      total: x.containers.length,
      down: x.containers.filter((c) => !c.up).map((c) => c.name),
      upd: x.containers.filter((c) => c.update_available).map((c) => c.name),
    })));

  let alerts = $derived([
    ...(rules.data?.hits ?? []).map((h) => ({ sev: h.severity, host: h.host, text: h.message, when: h.since })),
    ...(incidents.data?.incidents ?? []).filter((i) => i.status === 'open')
      .map((i) => ({ sev: i.severity === 'crit' ? 'critical' : 'warn', host: i.host, text: i.title, when: i.last_seen })),
  ].slice(0, 8));

  let nextTimers = $derived((timers.data?.hosts ?? [])
    .flatMap((h) => h.timers.map((t) => ({ host: h.host, unit: t.unit.replace('.timer', ''), passed: t.passed })))
    .slice(0, 6));

  let anyLoading = $derived(vitals.isLoading && containers.isLoading);
  const NAME_W = 5;
</script>

<svelte:window bind:innerWidth={viewW} />

<div class="tui">
  <!-- btop's top bar: what the box is, and how fresh this all is. -->
  <header class="bar">
    <span class="brand">pocket<span class="dim">@homelab</span></span>
    <span class="sep">│</span>
    <span class="stat" data-t={fleet.hostsUp === HOSTS.length ? 'ok' : 'crit'}>hosts {fleet.hostsUp}/{HOSTS.length}</span>
    <span class="stat" data-t={fleet.total && fleet.up === fleet.total ? 'ok' : 'warn'}>ctr {fleet.up}/{fleet.total || '—'}</span>
    <span class="stat" data-t={fleet.updates ? 'warn' : 'dim'}>upd {fleet.updates}</span>
    <span class="stat" data-t={alerts.length ? 'crit' : 'dim'}>alrt {alerts.length}</span>
    <span class="sep">│</span>
    <span class="stat dim">cpu {fleet.cpu == null ? '—' : `${fleet.cpu.toFixed(0)}%`}</span>
    <span class="stat dim">mem {fleet.mem == null ? '—' : `${fleet.mem.toFixed(0)}%`}</span>
    <span class="stat dim">↓{rate(fleet.rx).trim()} ↑{rate(fleet.tx).trim()}</span>
    <span class="spacer"></span>
    <span class="stat" data-t={sse.live ? 'ok' : 'dim'}>{sse.live ? '● live' : '○ poll'}</span>
    <span class="ranges">
      {#each VITALS_RANGES as r (r)}
        <button class:on={r === range} onclick={() => setRange(r)}>{r}</button>
      {/each}
    </span>
  </header>

  {#if anyLoading}
    <p class="loading">collecting…</p>
  {/if}

  <span class="ruler" bind:clientWidth={rulerW} aria-hidden="true">0000000000</span>

  <div class="grid" bind:clientWidth={gridW}>
    <Panel title="cpu" meta={`${range} · % busy · ⌈ scale peak · load1`}>
      {#each HOSTS as h (h)}
        {@const s = samplesOf(h)}
        {@const l = latestOf(h)}
        {@const dom = autoDomain(s.map((x) => x.cpu_pct), 0, 10)}
        <div class="row" data-t={loadTone(l?.cpu_pct)}>
          <span class="nm">{padEnd(SHORT[h], NAME_W)}</span>
          <span class="graph">{brailleSpark(s.map((x) => x.cpu_pct), cells(20), dom)}</span>
          <span class="val">{l?.cpu_pct == null ? '   —' : pad(l.cpu_pct.toFixed(0), 3) + '%'}</span>
          <span class="sub">{pad(dom[1].toFixed(0), 3)}%⌈</span>
          <span class="sub">{l?.load1 == null ? '  —  ' : pad(l.load1.toFixed(2), 5)}</span>
        </div>
      {/each}
      {#each HOSTS.filter((h) => errOf(h)) as h (h)}
        <div class="row err"><span class="nm">{padEnd(SHORT[h], NAME_W)}</span><span>{errOf(h)}</span></div>
      {/each}
    </Panel>

    <Panel title="memory" meta="% used">
      {#each HOSTS as h (h)}
        {@const l = latestOf(h)}
        <div class="row" data-t={loadTone(l?.mem_pct)}>
          <span class="nm">{padEnd(SHORT[h], NAME_W)}</span>
          <span class="graph">{meter(l?.mem_pct, cells(12))}</span>
          <span class="val">{l?.mem_pct == null ? '   —' : pad(l.mem_pct.toFixed(0), 3) + '%'}</span>
        </div>
      {/each}
      <div class="row spacer-row"></div>
      {#each HOSTS as h (h)}
        {@const s = samplesOf(h)}
        {@const pk = peak(s.map((x) => x.mem_pct))}
        <div class="row dim">
          <span class="nm">{padEnd(SHORT[h], NAME_W)}</span>
          <span class="graph">{spark(s.map((x) => x.mem_pct), cells(16), autoDomain(s.map((x) => x.mem_pct), 0, 5))}</span>
          <span class="sub">{pk == null ? '  —' : pad(pk.toFixed(0), 3) + '%⌈'}</span>
          <span class="sub">{range}</span>
        </div>
      {/each}
    </Panel>

    <Panel title="network" meta="rx ▲ / tx ▼ per host">
      {#each HOSTS as h (h)}
        {@const s = samplesOf(h)}
        {@const l = latestOf(h)}
        {@const dom = autoDomain([...s.map((x) => x.rx_bps), ...s.map((x) => x.tx_bps)], 0, 1024)}
        <div class="row">
          <span class="nm">{padEnd(SHORT[h], NAME_W)}</span>
          <span class="graph net-rx">{brailleSpark(s.map((x) => x.rx_bps), cells(14), dom)}</span>
          <span class="val">↓{rate(l?.rx_bps)}</span>
        </div>
        <div class="row dim">
          <span class="nm"></span>
          <span class="graph net-tx">{brailleSpark(s.map((x) => x.tx_bps), cells(14), dom)}</span>
          <span class="val">↑{rate(l?.tx_bps)}</span>
        </div>
        <div class="row dim scaleline"><span class="nm"></span><span class="sub">peak {rate(peak([...s.map((x) => x.rx_bps), ...s.map((x) => x.tx_bps)]))}/s shared scale</span></div>
      {/each}
    </Panel>

    <Panel title="temperature" meta="°C">
      {#each HOSTS as h (h)}
        {@const s = samplesOf(h)}
        {@const l = latestOf(h)}
        <div class="row" data-t={loadTone(l?.temp_c, 60, 72)}>
          <span class="nm">{padEnd(SHORT[h], NAME_W)}</span>
          <span class="graph">{brailleSpark(s.map((x) => x.temp_c), cells(16), autoDomain(s.map((x) => x.temp_c), 999, 6))}</span>
          <span class="val">{l?.temp_c == null ? '   —' : pad(l.temp_c.toFixed(0), 3) + '°'}</span>
          <span class="sub">{pad((peak(s.map((x) => x.temp_c)) ?? 0).toFixed(0), 3)}°⌈</span>
        </div>
      {/each}
      <div class="note dim">each row is scaled to its own range (⌈ = peak over {range}), so shapes are comparable but heights are not</div>
    </Panel>

    <Panel title="storage" meta={live.data?.run_at ? `doctor ${relTime(live.data.run_at)}` : 'from collectors'}>
      {#each disks as d (d.host + d.label)}
        <div class="row" data-t={loadTone(d.pct)}>
          <span class="nm">{padEnd(SHORT[d.host], NAME_W)}</span>
          <span class="lbl">{padEnd(d.label, 6)}</span>
          <span class="graph">{meter(d.pct, cells(20))}</span>
          <span class="val">{d.pct == null ? '   —' : pad(d.pct.toFixed(0), 3) + '%'}</span>
        </div>
      {/each}
      {#if disks.length === 0}<div class="row dim">no collector report yet</div>{/if}
    </Panel>

    <Panel title="containers" meta={`${fleet.up}/${fleet.total} up`} tone={fleet.total && fleet.up < fleet.total ? 'crit' : 'ok'}>
      {#each containersByHost as c (c.host)}
        <div class="row" data-t={c.total ? loadTone(100 - (c.up / c.total) * 100, 1, 34) : 'dim'}>
          <span class="nm">{padEnd(SHORT[c.host] ?? c.host, NAME_W)}</span>
          <span class="graph">{meter(c.total ? (c.up / c.total) * 100 : null, cells(20))}</span>
          <span class="val">{pad(`${c.up}/${c.total}`, 6)}</span>
          <span class="sub">{c.upd.length ? `${c.upd.length} upd` : ''}</span>
        </div>
        {#if c.down.length}
          <div class="row crit"><span class="nm"></span><span class="wrap">down: {c.down.join(' ')}</span></div>
        {/if}
      {/each}
      {#if containersByHost.length === 0}<div class="row dim">no container report</div>{/if}
    </Panel>

    <Panel title="alerts" meta={rules.data?.evaluated_at ? `rules ${relTime(rules.data.evaluated_at)}` : ''} tone={alerts.length ? 'crit' : 'dim'}>
      {#each alerts as a, i (i)}
        <div class="row" data-t={a.sev === 'critical' ? 'crit' : 'warn'}>
          <span class="nm">{padEnd(a.host ? (SHORT[a.host] ?? a.host) : '—', NAME_W)}</span>
          <span class="wrap">{a.text}</span>
          <span class="sub">{a.when ? relTime(a.when) : ''}</span>
        </div>
      {/each}
      {#if alerts.length === 0}<div class="row ok">nothing firing</div>{/if}
      {#if rules.isError}<div class="row dim">rules engine unavailable on this backend</div>{/if}
    </Panel>

    <Panel title="hosts" meta="uptime · agent">
      {#each (hostsQ.data ?? FALLBACK_FLEET).hosts as h (h.name)}
        {@const l = latestOf(h.name)}
        <div class="row" data-t={l ? 'ok' : h.intermittent ? 'dim' : 'crit'}>
          <span class="nm">{padEnd(SHORT[h.name] ?? h.name.slice(0, 5), NAME_W)}</span>
          <span class="lbl">{padEnd(h.ip.split('.').slice(-1)[0].padStart(3, ' '), 4)}</span>
          <span class="wrap">{h.role}</span>
          <span class="sub">{l ? uptime(l.uptime_s) : h.intermittent ? 'offline' : h.agent ? 'unreachable' : 'no agent'}</span>
        </div>
      {/each}
    </Panel>

    <Panel title="upkeep" meta={updates.data ? `${updates.data.counts.images} img · ${updates.data.counts.packages} pkg` : ''}>
      {#each updates.data?.packages ?? [] as p (p.host)}
        <div class="row" data-t={p.security ? 'crit' : p.pending ? 'warn' : 'ok'}>
          <span class="nm">{padEnd(SHORT[p.host] ?? p.host, NAME_W)}</span>
          <span class="wrap">{p.pending} pkg{p.security ? ` · ${p.security} security` : ''}{p.reboot_required ? ' · reboot required' : ''}</span>
        </div>
      {/each}
      {#each nextTimers as t, i (i)}
        <div class="row dim"><span class="nm">{padEnd(SHORT[t.host] ?? t.host, NAME_W)}</span><span class="wrap">{t.unit}</span><span class="sub">{t.passed ?? ''}</span></div>
      {/each}
      {#if !(updates.data?.packages?.length) && nextTimers.length === 0}<div class="row dim">nothing pending</div>{/if}
    </Panel>
  </div>

  <footer class="bar foot">
    <span class="dim">±</span><span class="dim">range</span>
    <span class="sep">│</span>
    <a href="/cockpit">controls</a>
    <a href="/feed">activity</a>
    <a href="/topology">topology</a>
    <span class="spacer"></span>
    <span class="dim">vitals {vitals.data ? `${vitals.data.interval_s}s` : '—'} · read-only view</span>
  </footer>
</div>

<style>
  /* This page deliberately leaves Fable's card chrome behind: it is a terminal.
     Monospace throughout, near-black ground, hairline boxes, block glyphs. */
  .tui {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--ink-2);
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: -4px 0 0;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 6px 10px;
    border: 1px solid var(--border-2);
    border-radius: 2px;
    background: var(--bg-inset);
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
  }
  .brand { color: var(--accent); font-weight: 700; letter-spacing: .04em; }
  .brand .dim { font-weight: 400; }
  .sep { color: var(--border-2); }
  .stat[data-t="ok"] { color: var(--ok); }
  .stat[data-t="warn"] { color: var(--warn); }
  .stat[data-t="crit"] { color: var(--crit); }
  .stat[data-t="dim"], .dim { color: var(--ink-3); }
  .spacer { flex: 1; }
  .ranges { display: inline-flex; gap: 1px; }
  .ranges button {
    border: 1px solid var(--border); background: none; color: var(--ink-3);
    font: inherit; font-size: 11px; padding: 1px 6px; cursor: pointer; border-radius: 2px;
  }
  .ranges button.on { color: var(--bg); background: var(--accent); border-color: var(--accent); font-weight: 700; }
  .foot a { color: var(--ink-2); text-decoration: none; }
  .foot a:hover { color: var(--accent); text-decoration: underline; }
  .loading { color: var(--ink-3); margin: 0; }

  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 12px; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
  /* Measures the real advance width of the monospace face, so glyph runs are sized
     in actual cells rather than an assumed 7px. */
  .ruler { position: absolute; visibility: hidden; pointer-events: none; font-family: var(--mono); font-size: 12px; white-space: pre; }
  .scaleline { font-size: 10.5px; }

  .row { display: flex; align-items: baseline; gap: 8px; white-space: pre; }
  .nm { color: var(--ink); flex: none; }
  .lbl { color: var(--ink-3); flex: none; }
  .graph { color: var(--accent); flex: none; letter-spacing: 0; }
  .val { color: var(--ink); flex: none; }
  .sub { color: var(--ink-3); flex: none; }
  .wrap { white-space: normal; overflow-wrap: anywhere; flex: 1; min-width: 0; }
  .spacer-row { height: 6px; }
  .note { font-size: 10.5px; margin-top: 4px; white-space: normal; }

  /* The load ramp: magnitude, not alarm. Thirds of the scale, cool to hot.
     `low` is deliberately the interactive blue rather than a grey — on this page
     a busy-but-fine box should still read as *data*, not as absence. */
  .row[data-t="low"]  .graph { color: var(--accent); }
  .row[data-t="mod"]  .graph { color: var(--brand); }
  .row[data-t="high"] .graph { color: var(--crit); }
  .row[data-t="mod"]  .val   { color: var(--brand); }
  .row[data-t="high"] .val   { color: var(--crit); }

  /* Row tone drives the graph, not the label — btop colours the data. */
  .row[data-t="ok"] .graph { color: var(--ok); }
  .row[data-t="warn"] .graph { color: var(--warn); }
  .row[data-t="crit"] .graph { color: var(--crit); }
  .row[data-t="dim"] .graph, .row.dim .graph { color: var(--ink-3); }
  .row[data-t="warn"] .val { color: var(--warn); }
  .row[data-t="crit"] .val { color: var(--crit); }
  .row.dim { color: var(--ink-3); }
  .row.crit, .row.err { color: var(--crit); }
  .row.ok { color: var(--ok); }
  .net-rx { color: var(--c-network); }
  .net-tx { color: var(--c-apps); }

  @media (max-width: 860px) {
    .tui { font-size: 11px; }
    /* The status bar wraps rather than scrolls: on a phone the range buttons take
       their own full-width line instead of pushing a scrollbar into the header. */
    .bar { gap: 6px 8px; font-size: 11px; }
    .bar .spacer { display: none; }
    .ranges { flex: 1 0 100%; flex-wrap: wrap; }
    .ranges button { flex: 1; min-width: 40px; }
  }
</style>
