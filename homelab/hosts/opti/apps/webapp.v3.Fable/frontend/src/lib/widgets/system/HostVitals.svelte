<script lang="ts">
  // Host vitals: CPU / memory / temp / network for one host, every drive and pool,
  // the container strip, pending updates and live actions. Direct port of the v2
  // HostVitalsWidget — same endpoints, same cadence, same hover popovers.
  import { Power, PackagePlus, Terminal, SlidersHorizontal } from '@lucide/svelte';
  import { getWidgetContext, opt, type WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Vital, Sparkline, Pill, Meter } from '$lib/widgets/kit';
  import {
    useVitals, useVitalsRange, useRunnerReport, useAgents, VITALS_RANGES, type VitalsRange,
  } from '$lib/api/queries';
  import { createHostActions } from '$lib/host-actions.svelte';
  import { fmtBytesPerSec } from '$lib/format';
  import { HOST_ROLES } from '$lib/impact';

  let { options = {} }: WidgetProps = $props();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  type Metrics = Record<string, any>;
  type Pool = { used_pct: number; pool_name?: string; size_gb?: number; avail_gb?: number };
  type Disk = { mount?: string; used_pct?: number; used_gb?: number; size_gb?: number };
  type Smart = { health?: string; reallocated?: number; pending?: number; power_on_hours?: number; temp_c?: number };
  type Thermal = { sensor?: string; temp_c?: number };
  type Cont = { name: string; status?: string };
  type Vpn = { status?: string; forwarded_port?: number; public_ip?: string };

  // v2's uptime phrasing ("29d 4h" / "3h 12m") — kept verbatim for this tile.
  function fmtUptime(s: number | null | undefined): string {
    if (s == null) return '—';
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    if (d > 0) return `${d}d ${h}h`;
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  }

  // Interfaces worth showing a human: the physical ones, not docker's veth forest.
  const isPhysicalIface = (i: string) => !/^(veth|br-|docker0|lo$)/.test(i);
  const isUp = (status?: string | null) => /^up/i.test(status || '');
  const nbsp = (s: string) => s.replace(' ', ' ');
  const isRange = (v: unknown): v is VitalsRange => VITALS_RANGES.includes(v as VitalsRange);

  let host = $derived(opt(options, 'host', 'rpi'));
  let optRange = $derived(opt<string>(options, 'range', '3h'));

  // Clicking a graph caption cycles the range AND saves it: on a board the choice
  // is written into this widget's options (server-side, follows the board to any
  // device); rendered outside a board it falls back to localStorage.
  const ctx = getWidgetContext();
  // Keyed by the host the widget was mounted with (v2 read it once at mount too).
  // svelte-ignore state_referenced_locally
  const lsKey = `vitals-range:${opt(options, 'host', 'rpi')}`;
  let localRange = $state<VitalsRange | null>((() => {
    try {
      const v = localStorage.getItem(lsKey);
      return isRange(v) ? v : null;
    } catch { return null; }
  })());
  let range = $derived.by((): VitalsRange => {
    const fromOpt: VitalsRange = isRange(optRange) ? optRange : '3h';
    return ctx ? fromOpt : (localRange ?? fromOpt);
  });
  function cycleRange() {
    const next = VITALS_RANGES[(VITALS_RANGES.indexOf(range) + 1) % VITALS_RANGES.length];
    if (ctx) {
      ctx.updateOptions({ ...options, range: next });
    } else {
      localRange = next;
      try { localStorage.setItem(lsKey, next); } catch { /* private mode */ }
    }
  }

  const vitals = useVitals();
  const series = useVitalsRange(() => host, () => range);
  const hardware = useRunnerReport(() => 'hardware-latest');
  const doctor = useRunnerReport(() => 'homelab-doctor-latest');
  const software = useRunnerReport(() => 'software-latest');
  const agents = useAgents();
  const actions = createHostActions(() => host);

  let live = $derived(vitals.data?.hosts[host]);
  let hw = $derived(hardware.data?.hosts?.find((h) => h.host === host));
  let doc = $derived(doctor.data?.hosts?.find((h) => h.host === host));
  let status = $derived(doc?.status || hw?.status || 'unknown');
  let metrics = $derived((hw?.metrics ?? {}) as Metrics);
  let dm = $derived((doc?.metrics ?? {}) as Metrics);
  let swm = $derived((software.data?.hosts?.find((h) => h.host === host)?.metrics ?? {}) as Metrics);
  let agent = $derived(agents.data?.hosts.find((a) => a.id === host));
  let controllable = $derived(!!agent?.reachable && Array.isArray(agent?.allowed_units));

  // ── everything the reports know about this host ───────────────────────────
  let pool = $derived(dm.pool as Pool | undefined);
  let disks = $derived((metrics.disks ?? []) as Disk[]);
  let smart = $derived((metrics.smart ?? {}) as Record<string, Smart>);
  let thermals = $derived((metrics.thermals ?? []) as Thermal[]);
  let containers = $derived((dm.containers ?? []) as Cont[]);
  let down = $derived(containers.filter((c) => !isUp(c.status)).length);
  let vpn = $derived(dm.vpn as Vpn | undefined);
  let ifaces = $derived(((metrics.interfaces ?? []) as string[]).filter(isPhysicalIface));
  let gpus = $derived((metrics.gpus ?? []) as string[]);

  let samples = $derived(series.data?.samples ?? []);
  let times = $derived(samples.map((s) => s.t));
  let cpu = $derived(live?.latest?.cpu_pct ?? null);
  let mem = $derived(live?.latest?.mem_pct ?? null);
  let temp = $derived(live?.latest?.temp_c ?? null);
  let rx = $derived(live?.latest?.rx_bps ?? null);
  let tx = $derived(live?.latest?.tx_bps ?? null);

  let memTotal = $derived(metrics.memory_gib?.MemTotal as number | undefined);
  let memUsed = $derived(metrics.mem_used_gib as number | undefined);
  let memAvail = $derived(metrics.memory_gib?.MemAvailable as number | undefined);
  let swapTotal = $derived(metrics.memory_gib?.SwapTotal as number | undefined);
  let swapUsed = $derived(metrics.swap_used_gib as number | undefined);
  let loadArr = $derived(Array.isArray(metrics.load) && metrics.load.length ? (metrics.load as (number | string)[]) : null);
  let cpuInfo = $derived((metrics.cpu ?? {}) as Record<string, string>);
  let cores = $derived(parseInt(cpuInfo['CPU(s)'], 10) || null);

  let uptimeText = $derived.by(() => {
    const u = fmtUptime(live?.latest?.uptime_s);
    return u === '—' ? (metrics.uptime ?? '—') : u;
  });
  let statusTone = $derived(status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : 'crit');
  let showDay = $derived(range === '24h' || range === '48h');
  let sampleNote = $derived(range === '1h' || range === '3h' ? '30s samples' : '5min averages');

  // SMART rows are shared by every storage popover — physical drives back all mounts.
  let smartRows = $derived(Object.entries(smart));
  let poolRows = $derived.by((): [string, string][] => {
    if (!pool) return [];
    const rows: [string, string][] = [[`pool ${pool.pool_name ?? ''}`, `${pool.used_pct}% of ${Math.round(pool.size_gb ?? 0)} GB`]];
    if (pool.avail_gb != null) rows.push(['free', `${Math.round(pool.avail_gb)} GB`]);
    return rows;
  });
  function diskRows(d: Disk, i: number): [string, string][] {
    const rows: [string, string][] = [[
      d.mount ?? `disk ${i + 1}`,
      `${d.used_pct ?? '—'}%${d.used_gb != null && d.size_gb != null ? ` · ${Math.round(d.used_gb)} of ${Math.round(d.size_gb)} GB` : ''}`,
    ]];
    if (d.size_gb != null && d.used_gb != null) rows.push(['free', `${Math.round(d.size_gb - d.used_gb)} GB`]);
    return rows;
  }

  // ── hover popover: just the row highlights, the popover is portaled to <body>
  // (the tile clips overflow and the glass backdrop-filter would trap position:fixed).
  let hovered = $state<string | null>(null);
  let hoverRect = $state<DOMRect | null>(null);
  function enter(id: string, e: PointerEvent) {
    hoverRect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    hovered = id;
  }
  function leave() { hovered = null; }
  let hoveredDisk = $derived.by(() => {
    if (!hovered?.startsWith('disk-')) return null;
    const i = parseInt(hovered.slice(5), 10);
    return disks[i] ? { d: disks[i], i } : null;
  });
  let popStyle = $derived.by(() => {
    const r = hoverRect;
    if (!r) return '';
    const left = Math.min(r.left, window.innerWidth - 300);
    const overflows = r.bottom + 8 + 260 > window.innerHeight;
    return overflows
      ? `left:${left}px; bottom:${window.innerHeight - r.top + 8}px`
      : `left:${left}px; top:${r.bottom + 8}px`;
  });
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { node.remove(); } };
  }
</script>

{#snippet kv(k: string, v: string)}
  <div class="kv-row"><span>{k}</span><span>{v}</span></div>
{/snippet}

{#snippet sparkNote()}
  <div class="t-dim vital-pop-note">last {range}, {sampleNote} · daily details from the hardware report</div>
{/snippet}

{#snippet cpuPop()}
  <div class="vital-pop-head">CPU — {host}</div>
  <div class="kv-rows">
    {@render kv('now', cpu != null ? `${cpu.toFixed(1)}%` : '—')}
    {@render kv('load 1/5/15', loadArr ? loadArr.join(' / ') : (live?.latest?.load1?.toFixed(2) ?? '—'))}
    {#if cores}{@render kv('cores', String(cores))}{/if}
    {#if cpuInfo['Model name']}
      <div class="kv-row"><span>model</span><span class="vital-pop-clip">{cpuInfo['Model name']}</span></div>
    {/if}
    {#if gpus.length > 0}
      <div class="kv-row"><span>gpu</span><span class="vital-pop-clip">{gpus[0]}</span></div>
    {/if}
    {@render kv('containers', `${containers.length - down} running${down ? `, ${down} down` : ''}`)}
  </div>
  <div class="vital-pop-spark" style="color: var(--accent)">
    <Sparkline values={samples.map((s) => s.cpu_pct)} {times} height={36}
      label="cpu history" format={(v) => `${v.toFixed(1)}%`} />
  </div>
  {@render sparkNote()}
{/snippet}

{#snippet memPop()}
  <div class="vital-pop-head">Memory — {host}</div>
  <div class="kv-rows">
    {@render kv('now', mem != null ? `${mem.toFixed(1)}%` : '—')}
    {#if memUsed != null && memTotal != null}{@render kv('used', `${memUsed.toFixed(1)} of ${memTotal} GiB`)}{/if}
    {#if memAvail != null}{@render kv('available', `${memAvail.toFixed(1)} GiB`)}{/if}
    {#if swapTotal != null && swapTotal > 0}
      {@render kv('swap', `${(swapUsed ?? 0).toFixed(1)} of ${swapTotal} GiB${(swapUsed ?? 0) > swapTotal * 0.5 ? ' — heavy' : ''}`)}
    {/if}
    {@render kv('containers', `${containers.length} sharing it`)}
  </div>
  <div class="vital-pop-spark" style="color: var(--brand)">
    <Sparkline values={samples.map((s) => s.mem_pct)} {times} height={36}
      label="memory history" format={(v) => `${v.toFixed(1)}%`} />
  </div>
  {@render sparkNote()}
{/snippet}

{#snippet tempPop()}
  <div class="vital-pop-head">Temperature — {host}</div>
  <div class="kv-rows">
    {#if temp != null}{@render kv('primary', `${temp.toFixed(1)}°C`)}{/if}
    {#each thermals.slice(0, 8) as t, i (t.sensor ?? i)}
      {@render kv(t.sensor ?? `sensor ${i + 1}`, t.temp_c != null ? `${t.temp_c}°C` : '—')}
    {/each}
    {#if thermals.length === 0}{@render kv('sensors', 'none reported')}{/if}
  </div>
  {#if temp != null}
    <div class="vital-pop-spark" style="color: var(--c-media)">
      <Sparkline values={samples.map((s) => s.temp_c)} {times} height={36}
        label="temp history" format={(v) => `${v.toFixed(1)}°C`} />
    </div>
  {/if}
  {@render sparkNote()}
{/snippet}

{#snippet netPop()}
  <div class="vital-pop-head">Network — {host}</div>
  <div class="kv-rows">
    {@render kv('in', fmtBytesPerSec(rx))}
    {@render kv('out', fmtBytesPerSec(tx))}
    {#if ifaces.length > 0}{@render kv('interfaces', ifaces.join(', '))}{/if}
    {#if vpn?.status}
      {@render kv('vpn', `${vpn.status}${vpn.forwarded_port ? ` · port ${vpn.forwarded_port}` : ''}${vpn.public_ip ? ` · ${vpn.public_ip}` : ''}`)}
    {/if}
  </div>
  <div class="vital-pop-spark" style="color: var(--c-network)">
    <Sparkline values={samples.map((s) => s.rx_bps)} {times} height={36}
      label="net in history" format={(v) => `↓ ${fmtBytesPerSec(v)}`} />
  </div>
  {@render sparkNote()}
{/snippet}

{#snippet storagePop(rows: [string, string][])}
  <div class="vital-pop-head">Storage — {host}</div>
  <div class="kv-rows">
    {#each rows as [k, v] (k)}{@render kv(k, v)}{/each}
  </div>
  {#if smartRows.length > 0}
    <div class="vital-pop-sub">physical drives (SMART)</div>
    <div class="kv-rows">
      {#each smartRows as [dev, s] (dev)}
        <div class="kv-row">
          <span>{dev}</span>
          <span>
            <span class={s.health === 'PASSED' ? 't-ok' : 't-crit'}>{s.health ?? '?'}</span>
            {#if s.reallocated}<span class={s.reallocated > 50 ? 't-crit' : 't-warn'}> · {s.reallocated} realloc</span>{/if}
            {#if s.pending}<span class="t-warn"> · {s.pending} pending</span>{/if}
            {#if s.temp_c} · {s.temp_c}°C{/if}
            {#if s.power_on_hours} · {Math.round(s.power_on_hours / 24 / 365 * 10) / 10}y on{/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}
  <div class="t-dim vital-pop-note">daily hardware report{pool ? ' + doctor pool check' : ''}</div>
{/snippet}

<WidgetFrame>
  {#snippet head()}
    <span class="w-title host-name">{host}</span>
    <span class="w-meta host-meta">
      <span class="t-dim">up {uptimeText}</span>
      <Pill tone={statusTone}>{status}</Pill>
    </span>
  {/snippet}

  <div class="host-role">{HOST_ROLES[host] ?? ''}</div>
  {#if live?.error}
    <WidgetError message={live.error} />
  {:else if vitals.isError}
    <WidgetError message={`vitals unavailable — ${(vitals.error as Error)?.message ?? 'backend unreachable'}`} />
  {/if}

  {#if vitals.isLoading}
    <WidgetLoading />
  {:else}
    <div class="vitals">
      <div class="vital-hit" class:active={hovered === 'cpu'} role="presentation"
        onpointerenter={(e) => enter('cpu', e)} onpointerleave={leave}>
        <Vital label="CPU" value={cpu != null ? `${Math.round(cpu)}%` : '—'}
          sub={loadArr ? ` load ${loadArr[0]}` : live?.latest?.load1 != null ? ` load ${live.latest.load1.toFixed(2)}` : undefined}
          pct={cpu} />
      </div>
      <div class="vital-hit" class:active={hovered === 'mem'} role="presentation"
        onpointerenter={(e) => enter('mem', e)} onpointerleave={leave}>
        <Vital label="Memory" value={mem != null ? `${Math.round(mem)}%` : '—'}
          sub={memTotal ? ` of ${memTotal} GiB` : undefined} pct={mem} />
      </div>
      <div class="vital-hit" class:active={hovered === 'temp'} role="presentation"
        onpointerenter={(e) => enter('temp', e)} onpointerleave={leave}>
        <Vital label="Temp" value={temp != null ? `${Math.round(temp)}°C` : '—'}
          sub={thermals.length > 1 ? ` ${thermals.length} sensors` : undefined} />
      </div>
      <div class="vital-hit" class:active={hovered === 'net'} role="presentation"
        onpointerenter={(e) => enter('net', e)} onpointerleave={leave}>
        <Vital label="Network" sub={vpn?.status ? ` vpn ${vpn.status}` : undefined}>
          <span class="net-pair">↓{nbsp(fmtBytesPerSec(rx))} ↑{nbsp(fmtBytesPerSec(tx))}</span>
        </Vital>
      </div>
    </div>
  {/if}

  <!-- every drive, partition and pool this host has — not just the first -->
  {#if pool || disks.length > 0}
    <div class="disk-rows">
      {#if pool}
        <div class="vital-hit" class:active={hovered === 'pool'} role="presentation"
          onpointerenter={(e) => enter('pool', e)} onpointerleave={leave}>
          <div class="disk-row">
            <span class="disk-label mono">{pool.pool_name ?? 'pool'} <small>zfs</small></span>
            <Meter pct={pool.used_pct} />
            <span class="disk-val">{Math.round(pool.used_pct)}%<small> of {Math.round((pool.size_gb ?? 0) / 100) / 10} TB</small></span>
          </div>
        </div>
      {/if}
      {#each disks as d, i (d.mount ?? i)}
        {@const id = `disk-${i}`}
        <div class="vital-hit" class:active={hovered === id} role="presentation"
          onpointerenter={(e) => enter(id, e)} onpointerleave={leave}>
          <div class="disk-row">
            <span class="disk-label mono">{d.mount ?? `disk ${i + 1}`}</span>
            <Meter pct={d.used_pct ?? null} />
            <span class="disk-val">{d.used_pct ?? '—'}%<small>{d.size_gb ? ` of ${Math.round(d.size_gb)} GB` : ''}</small></span>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if samples.length > 1}
    <div class="sparks">
      <span class="spark-wrap" style="color: var(--c-network)">
        <button type="button" class="spark-cap spark-cap-btn" onclick={cycleRange}
          title="Click to cycle the range">CPU % · {range}</button>
        <Sparkline values={samples.map((s) => s.cpu_pct)} {times} {showDay}
          label={`${host} CPU`} format={(v) => `cpu ${v.toFixed(1)}%`} />
      </span>
      <span class="spark-wrap" style="color: var(--brand)">
        <button type="button" class="spark-cap spark-cap-btn" onclick={cycleRange}
          title="Click to cycle the range">MEM % · {range}</button>
        <Sparkline values={samples.map((s) => s.mem_pct)} {times} {showDay}
          label={`${host} memory`} format={(v) => `mem ${v.toFixed(1)}%`} />
      </span>
    </div>
  {/if}

  <div class="w-foot">
    {#if containers.length > 0}
      <span>{containers.length - down}/{containers.length} containers</span>
      <span class="cstrip">
        {#each containers as c (c.name)}
          <span class="cdot" data-s={isUp(c.status) ? 'ok' : 'crit'} title={`${c.name} — ${c.status || 'unknown'}`}></span>
        {/each}
      </span>
      {#if down > 0}<span class="t-crit">{down} down</span>{/if}
    {/if}
    {#if swm.pending_count}
      <span class="chip" title={swm.reboot_pkgs ?? ''}>
        {swm.pending_count} pkg{#if swm.security_count}<b class="t-crit"> · {swm.security_count} sec</b>{/if}
      </span>
    {/if}
    {#if swm.reboot_required}<span class="chip" data-s="warn">reboot req</span>{/if}
    {#if swm.image_update_count}
      <span class="chip">{swm.image_update_count} image{swm.image_update_count > 1 ? 's' : ''}</span>
    {/if}
  </div>

  <div class="w-actions host-actions">
    {#if controllable}
      <button type="button" class="tb-btn sm danger" disabled={actions.busy} onclick={actions.reboot}
        title={`Reboot ${host} (typed confirm)`}><Power size={12} aria-hidden="true" /> Reboot</button>
      <button type="button" class="tb-btn sm" disabled={actions.busy} onclick={actions.aptUpgrade}
        title={`Run homelab-autoupdate on ${host} now`}><PackagePlus size={12} aria-hidden="true" /> Apt</button>
    {:else}
      <span class="t-dim host-actions-note">
        {agent?.reachable === false ? 'agent unreachable' : 'controls need agent v0.4.0'}
      </span>
    {/if}
    <a class="tb-btn sm" href={actions.termUrl} target="_blank" rel="noreferrer"
      title={`Terminal on ${host} via Cockpit (rpi:9090, system login)`}><Terminal size={12} aria-hidden="true" /> Term</a>
    <a class="tb-btn sm" href="/cockpit" title="All host controls"><SlidersHorizontal size={12} aria-hidden="true" /> More</a>
  </div>
</WidgetFrame>

{#if hovered && hoverRect}
  <div class="vital-pop glass-strong" style={popStyle} use:portal>
    {#if hovered === 'cpu'}{@render cpuPop()}
    {:else if hovered === 'mem'}{@render memPop()}
    {:else if hovered === 'temp'}{@render tempPop()}
    {:else if hovered === 'net'}{@render netPop()}
    {:else if hovered === 'pool'}{@render storagePop(poolRows)}
    {:else if hoveredDisk}{@render storagePop(diskRows(hoveredDisk.d, hoveredDisk.i))}
    {/if}
  </div>
{/if}

<style>
  /* graph captions double as the range cycler — text-styled so they read as labels */
  .spark-cap-btn {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0 0 2px;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--fs-xs);
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--ink-3);
    cursor: pointer;
  }
  .spark-cap-btn:hover { color: var(--ink-2); }
  .spark-cap-btn:focus-visible { outline: 1px solid var(--accent-muted); outline-offset: 2px; border-radius: 3px; }
</style>
