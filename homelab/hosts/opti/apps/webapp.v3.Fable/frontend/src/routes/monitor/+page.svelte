<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import Panel from '$lib/features/tui/Panel.svelte';
  import ProcessTable from './ProcessTable.svelte';
  import { brailleSpark, meter } from '$lib/features/tui/glyphs';
  import { monitorLive } from '$lib/api/monitor.svelte';
  import { post } from '$lib/api/client';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { fmtBytesPerSec, fmtPct, fmtUptime } from '$lib/format';
  import type { MonitorProcess, MonitorSample } from '$lib/api/types';

  type View = 'overview' | 'cpu' | 'memory' | 'disks' | 'network' | 'gpu' | 'processes';
  type Layout = 'balanced' | 'processes' | 'io';
  const HOSTS = ['opti', 'rpi', 'noblenumbat'];
  const VIEWS: View[] = ['overview', 'cpu', 'memory', 'disks', 'network', 'gpu', 'processes'];

  let host = $state<'fleet' | string>('fleet');
  let view = $state<View>('overview');
  let layout = $state<Layout>('balanced');
  let search = $state('');
  let sort = $state<'cpu_pct' | 'memory_bytes' | 'pid' | 'program'>('cpu_pct');
  let descending = $state(true);
  let tree = $state(false);
  let paused = $state(false);
  let frozenRows = $state<(MonitorProcess & { monitorHost?: string })[]>([]);
  let selected = $state<MonitorProcess | null>(null);
  let menuOpen = $state(false);
  let optionsOpen = $state(false);
  let helpOpen = $state(false);
  let fontSize = $state(13);
  let graph = $state<'braille' | 'block' | 'ascii'>('braille');
  let netFixed = $state(false);
  let hidden = $state<Set<string>>(new Set());
  let panelArea: HTMLElement;
  let panelWidth = $state(900);

  const current = $derived(host === 'fleet' ? null : monitorLive.snapshot?.hosts[host]?.latest ?? null);
  const samplesFor = (name: string) => monitorLive.histories[name] ?? [];
  const currentAge = (sample: MonitorSample | null | undefined) => {
    if (!sample?.measured_at) return '—';
    const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(sample.measured_at)) / 1000));
    return seconds < 2 ? 'now' : `${seconds}s`;
  };
  const latest = (name: string) => monitorLive.snapshot?.hosts[name]?.latest ?? null;
  const width = $derived(Math.max(12, Math.floor(panelWidth / (fontSize * .63)) - 18));
  const graphOf = (values: (number | null | undefined)[], percentage = false) => {
    if (graph === 'ascii') return values.slice(-width).map((v) => v == null ? ' ' : v > 66 ? '#' : v > 33 ? '+' : '.').join('').padEnd(width);
    return brailleSpark(values, width, percentage ? [0, 100] : undefined);
  };
  const processRows = $derived.by(() => {
    const rows = host === 'fleet'
      ? HOSTS.flatMap((name) => (latest(name)?.processes ?? []).map((p) => ({ ...p, monitorHost: name })))
      : (current?.processes ?? []).map((p) => ({ ...p, monitorHost: host }));
    const terms = search.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const filtered = rows.filter((p) => terms.every((term) => `${p.pid} ${p.program} ${p.user} ${p.command}`.toLowerCase().includes(term)));
    return filtered.sort((a, b) => {
      const av = a[sort], bv = b[sort];
      const result = typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv) : Number(av ?? 0) - Number(bv ?? 0);
      return (descending ? -1 : 1) * (result || (a.pid - b.pid));
    });
  });
  const processDisplay = $derived(paused ? frozenRows : processRows);
  const allHidden = (name: string) => hidden.has(name);

  function updateRoute(nextHost = host, nextView = view) {
    const url = new URL(window.location.href);
    if (nextHost === 'fleet') url.searchParams.delete('host'); else url.searchParams.set('host', nextHost);
    if (nextView === 'overview') url.searchParams.delete('view'); else url.searchParams.set('view', nextView);
    window.history.pushState({}, '', `${url.pathname}${url.search}`);
  }
  function chooseHost(name: string) { host = name; view = 'overview'; selected = null; updateRoute(); }
  function chooseView(next: View) { view = next; updateRoute(); }
  function togglePanel(name: string) { const next = new Set(hidden); next.has(name) ? next.delete(name) : next.add(name); hidden = next; }
  function sortBy(next: typeof sort) { if (sort === next) descending = !descending; else { sort = next; descending = next !== 'program' && next !== 'pid'; } }
  function color(value: number | null | undefined, warn = 75, critical = 90) { return value == null ? 'dim' : value >= critical ? 'crit' : value >= warn ? 'warn' : 'ok'; }
  function fmtBytes(value: number | null | undefined) {
    if (value == null) return '—';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let n = value; let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
  }
  function selectProcess(process: MonitorProcess) { selected = process; }
  function togglePause() {
    if (paused) { paused = false; return; }
    frozenRows = processRows.map((row) => ({ ...row }));
    paused = true;
  }
  async function signalProcess(signalName: string) {
    if (!selected) return;
    const targetHost = (selected as MonitorProcess & { monitorHost?: string }).monitorHost ?? host;
    const latestSample = latest(targetHost);
    const dangerous = signalName === 'SIGKILL' || selected.user === 'root';
    const ok = await confirm({ title: `${signalName} ${selected.program}`, body: `Send ${signalName} to PID ${selected.pid} on ${targetHost}?`, danger: 'The target is validated again by host boot ID and process start time before delivery.', tone: signalName === 'SIGKILL' ? 'crit' : 'warn', confirmLabel: `Send ${signalName}`, requireTyped: dangerous ? `${targetHost}:${selected.pid}` : undefined });
    if (!ok || !latestSample) return;
    try {
      await post(`/api/monitor/${targetHost}/process/${selected.pid}/signal`, { boot_id: latestSample.boot_id, start_ticks: selected.start_ticks, signal_name: signalName, request_id: crypto.randomUUID() }, 4000);
    } catch { /* Job drawer preserves the server response; selection stays inspectable. */ }
  }
  function fullscreen() { if (document.fullscreenElement) void document.exitFullscreen(); else void panelArea?.requestFullscreen(); }

  onMount(() => {
    const restore = () => {
      const selectedHost = page.url.searchParams.get('host'); const selectedView = page.url.searchParams.get('view');
      host = selectedHost && HOSTS.includes(selectedHost) ? selectedHost : 'fleet';
      view = selectedView && VIEWS.includes(selectedView as View) ? selectedView as View : 'overview';
      try { const saved = JSON.parse(localStorage.getItem('monitor:v1') || '{}'); layout = saved.layout ?? layout; fontSize = saved.fontSize ?? fontSize; graph = saved.graph ?? graph; }
      catch { /* malformed preferences use defaults */ }
    };
    restore(); monitorLive.start(); window.addEventListener('popstate', restore);
    const key = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement; if (/INPUT|TEXTAREA|SELECT/.test(element?.tagName)) return;
      if (event.key === '0') { host = 'fleet'; view = 'overview'; updateRoute(); }
      if (/^[1-6]$/.test(event.key)) { const match = VIEWS[Number(event.key)]; if (match) chooseView(match); }
      if (event.key === '[' || event.key === ']') { const index = Math.max(0, HOSTS.indexOf(host)); chooseHost(HOSTS[(index + (event.key === ']' ? 1 : HOSTS.length - 1)) % HOSTS.length]); }
      if (event.key === '/') { event.preventDefault(); document.getElementById('monitor-search')?.focus(); }
      if (event.key === 't') tree = !tree;
      if (event.key === ' ') { event.preventDefault(); togglePause(); }
      if (event.key === 'm') menuOpen = !menuOpen;
      if (event.key === 'o') optionsOpen = !optionsOpen;
      if (event.key === '?') helpOpen = !helpOpen;
      if (event.key === 'Escape') { menuOpen = false; optionsOpen = false; helpOpen = false; }
    };
    window.addEventListener('keydown', key);
    const observer = new ResizeObserver(([entry]) => panelWidth = entry.contentRect.width);
    if (panelArea) observer.observe(panelArea);
    return () => { monitorLive.stop(); window.removeEventListener('popstate', restore); window.removeEventListener('keydown', key); observer.disconnect(); };
  });
  $effect(() => { try { localStorage.setItem('monitor:v1', JSON.stringify({ layout, fontSize, graph })); } catch { /* private mode */ } });
</script>

<svelte:head><title>Monitor · Pert’s Pocket</title></svelte:head>

<main class="monitor" bind:this={panelArea} style={`font-size:${fontSize}px`}>
  <header class="toolbar">
    <div class="switches" role="group" aria-label="Monitor target">
      <button class:on={host === 'fleet'} onclick={() => chooseHost('fleet')}>fleet</button>
      {#each HOSTS as name}<button class:on={host === name} onclick={() => chooseHost(name)}>{name}</button>{/each}
    </div>
    <span class="sep">│</span>
    <div class="switches views" role="group" aria-label="Monitor screen">
      {#each VIEWS as name}<button class:on={view === name} onclick={() => chooseView(name)}>{name === 'overview' ? 'home' : name}</button>{/each}
    </div>
    <span class="fill"></span>
    <span class:live={monitorLive.state === 'live'} class="stream">{monitorLive.state === 'live' ? '● LIVE 2s' : monitorLive.state === 'reconnecting' ? '◌ RECONNECTING' : '○ CONNECTING'}</span>
    <button onclick={() => menuOpen = !menuOpen}>layout</button><button onclick={() => optionsOpen = !optionsOpen}>options</button><button onclick={() => helpOpen = !helpOpen}>?</button><button onclick={fullscreen}>⛶</button>
  </header>

  <nav class="host-strip" aria-label="Host status">
    {#each HOSTS as name}
      {@const sample = latest(name)}
      <button class:on={host === name} data-state={color(sample?.cpu.total_pct)} onclick={() => chooseHost(name)}>
        <strong>{name}</strong><span>{sample ? `${fmtPct(sample.cpu.total_pct)} cpu · ${fmtPct(sample.memory.total_bytes && sample.memory.used_bytes != null ? sample.memory.used_bytes / sample.memory.total_bytes * 100 : null)} mem` : 'warming up'}</span><small>{sample?.uptime_s == null ? currentAge(sample) : fmtUptime(sample.uptime_s)}</small>
      </button>
    {/each}
  </nav>

  {#if menuOpen}
    <section class="overlay menu"><strong>layouts</strong><div>{#each ['balanced', 'processes', 'io'] as option}<button class:on={layout === option} onclick={() => { layout = option as Layout; menuOpen = false; }}>{option}</button>{/each}</div><strong>panels</strong>{#each ['cpu', 'memory', 'disks', 'network', 'gpu', 'processes', 'upkeep'] as name}<label><input type="checkbox" checked={!allHidden(name)} onchange={() => togglePanel(name)} /> {name}</label>{/each}</section>
  {/if}
  {#if optionsOpen}
    <section class="overlay options"><strong>options</strong><label>Font <select bind:value={fontSize}>{#each [12, 13, 14, 16] as size}<option value={size}>{size}px</option>{/each}</select></label><label>Graphs <select bind:value={graph}><option value="braille">braille</option><option value="block">block</option><option value="ascii">ASCII</option></select></label><label><input type="checkbox" bind:checked={netFixed} /> fixed network scale</label><button onclick={() => { localStorage.removeItem('monitor:v1'); layout = 'balanced'; fontSize = 13; graph = 'braille'; }}>reset monitor</button></section>
  {/if}
  {#if helpOpen}
    <section class="overlay help"><strong>Monitor keys</strong><p><kbd>0</kbd> fleet · <kbd>1–6</kbd> resource screen · <kbd>[</kbd>/<kbd>]</kbd> host · <kbd>/</kbd> search · <kbd>t</kbd> tree · <kbd>space</kbd> pause · <kbd>m</kbd> layout · <kbd>o</kbd> options · <kbd>Esc</kbd> close</p></section>
  {/if}

  {#if host === 'fleet'}
    <section class="fleet-grid" class:processLayout={layout === 'processes'} class:ioLayout={layout === 'io'}>
      {#if !allHidden('cpu')}<Panel title="fleet cpu" meta="live total · load" ><div class="host-rows">{#each HOSTS as name}{@const sample = latest(name)}<button class="metric-row" onclick={() => { chooseHost(name); chooseView('cpu'); }}><b>{name}</b><span class="graph">{graphOf(samplesFor(name).map((item) => item.cpu.total_pct), true)}</span><strong data-tone={color(sample?.cpu.total_pct)}>{fmtPct(sample?.cpu.total_pct)}</strong><small>{sample?.cpu.load?.map((item) => item?.toFixed(2) ?? '—').join(' ')}</small></button>{/each}</div></Panel>{/if}
      {#if !allHidden('memory')}<Panel title="memory" meta="used / available"><div class="host-rows">{#each HOSTS as name}{@const sample = latest(name)}<button class="metric-row" onclick={() => { chooseHost(name); chooseView('memory'); }}><b>{name}</b><span class="graph">{meter(sample?.memory.total_bytes && sample.memory.used_bytes != null ? sample.memory.used_bytes / sample.memory.total_bytes * 100 : null, 24)}</span><strong>{fmtBytes(sample?.memory.used_bytes)} / {fmtBytes(sample?.memory.total_bytes)}</strong></button>{/each}</div></Panel>{/if}
      {#if !allHidden('disks')}<Panel title="storage" meta="capacity + I/O"><div class="host-rows">{#each HOSTS as name}{@const sample = latest(name)}<button class="metric-row" onclick={() => { chooseHost(name); chooseView('disks'); }}><b>{name}</b><span>{#each sample?.mounts ?? [] as mount}<span class="mount">{mount.mount} {fmtPct((mount.total_bytes - mount.available_bytes) / mount.total_bytes * 100)}</span>{/each}</span></button>{/each}</div></Panel>{/if}
      {#if !allHidden('network')}<Panel title="network" meta="combined host traffic"><div class="host-rows">{#each HOSTS as name}{@const sample = latest(name)}{@const rates = Object.values(sample?.network ?? {}).reduce((sum, row) => ({ rx: sum.rx + (row.rx_bps ?? 0), tx: sum.tx + (row.tx_bps ?? 0) }), { rx: 0, tx: 0 })}<button class="metric-row" onclick={() => { chooseHost(name); chooseView('network'); }}><b>{name}</b><span class="graph">{graphOf(samplesFor(name).map((item) => Object.values(item.network).reduce((sum, row) => sum + (row.rx_bps ?? 0), 0)))}</span><strong>↓ {fmtBytesPerSec(rates.rx)} ↑ {fmtBytesPerSec(rates.tx)}</strong></button>{/each}</div></Panel>{/if}
      {#if !allHidden('upkeep')}<Panel title="upkeep" meta="collector data"><p class="faint">Existing alerts, container health, updates and timers remain available in Control center and Activity. Monitor shows their live resource context without pretending scheduled reports are two-second data.</p></Panel>{/if}
      {#if !allHidden('processes')}<section class="process-panel"><ProcessTable rows={processDisplay} {search} {sort} {descending} {tree} {paused} {selected} onsearch={(value) => search = value} onsort={sortBy} ontree={() => tree = !tree} onpause={togglePause} onselect={selectProcess} /></section>{/if}
    </section>
  {:else}
    <section class="host-grid" class:processLayout={layout === 'processes'} class:ioLayout={layout === 'io'}>
      {#if view === 'overview' || view === 'cpu'}{#if !allHidden('cpu')}<Panel title="cpu" meta={`${currentAge(current)} · ${current?.cpu.load?.map((item) => item?.toFixed(2) ?? '—').join(' / ') ?? 'warming up'}`}><div class="cpu-main"><div><span class="big-graph">{graphOf(samplesFor(host).map((item) => item.cpu.total_pct), true)}</span><strong data-tone={color(current?.cpu.total_pct)}>{fmtPct(current?.cpu.total_pct)}</strong><p class="faint">{#each current?.temperatures ?? [] as temp}{temp.label} {temp.celsius.toFixed(1)}°C · {/each}{#each current?.power ?? [] as power}{power.name} {power.watts == null ? '—' : `${power.watts.toFixed(1)}W`}{/each}</p></div><div class="cores">{#each Object.entries(current?.cpu.core_pct ?? {}) as [name, value]}<span>{name} <i>{meter(value, 10)}</i> {fmtPct(value)}</span>{/each}</div></div></Panel>{/if}{/if}
      {#if view === 'overview' || view === 'gpu'}{#if !allHidden('gpu')}<Panel title="gpu" meta="capability-aware">{#if current?.gpu?.length}{#each current.gpu as gpu}<div class="gpu"><b>{gpu.id} · {gpu.driver}</b><span>{gpu.utilization_status === 'supported' ? `${fmtPct(gpu.busy_pct)} busy` : 'utilization unsupported'}</span><span>{gpu.clock_current_mhz ?? '—'} MHz · {gpu.memory_kind ?? '—'} memory</span></div>{/each}{:else}<p class="faint">GPU monitoring is unavailable on this host.</p>{/if}</Panel>{/if}{/if}
      {#if view === 'overview' || view === 'memory'}{#if !allHidden('memory')}<Panel title="memory" meta="used / available"><div class="memory"><strong>{fmtBytes(current?.memory.used_bytes)} / {fmtBytes(current?.memory.total_bytes)}</strong><span>{meter(current?.memory.total_bytes && current.memory.used_bytes != null ? current.memory.used_bytes / current.memory.total_bytes * 100 : null, 30)}</span><span>available {fmtBytes(current?.memory.available_bytes)} · swap {fmtBytes(current?.memory.swap_free_bytes)} / {fmtBytes(current?.memory.swap_total_bytes)}</span></div></Panel>{/if}{/if}
      {#if view === 'overview' || view === 'disks'}{#if !allHidden('disks')}<Panel title="disks" meta="read / write · IOPS"><div class="data-table">{#each Object.entries(current?.disks ?? {}) as [name, disk]}<div><b>{name}</b><span>↓ {fmtBytesPerSec(disk.read_bps)} · ↑ {fmtBytesPerSec(disk.write_bps)}</span><span>{disk.read_iops?.toFixed(0) ?? '—'} / {disk.write_iops?.toFixed(0) ?? '—'} IOPS · {fmtPct(disk.busy_pct)}</span></div>{/each}</div><div class="mounts">{#each current?.mounts ?? [] as mount}<span>{mount.mount} {fmtBytes(mount.total_bytes - mount.available_bytes)} / {fmtBytes(mount.total_bytes)}</span>{/each}</div></Panel>{/if}{/if}
      {#if view === 'overview' || view === 'network'}{#if !allHidden('network')}<Panel title="network" meta={netFixed ? 'fixed scale' : 'automatic scale'}><div class="data-table">{#each Object.entries(current?.network ?? {}) as [name, network]}<div><b>{name}</b><span>↓ {fmtBytesPerSec(network.rx_bps)} · ↑ {fmtBytesPerSec(network.tx_bps)}</span><span>{network.rx_errors + network.tx_errors} errors · {network.rx_drops + network.tx_drops} drops</span></div>{/each}</div></Panel>{/if}{/if}
      {#if view === 'overview' || view === 'processes'}{#if !allHidden('processes')}<section class="process-panel"><ProcessTable rows={processDisplay} {search} {sort} {descending} {tree} {paused} {selected} onsearch={(value) => search = value} onsort={sortBy} ontree={() => tree = !tree} onpause={togglePause} onselect={selectProcess} /></section>{/if}{/if}
    </section>
  {/if}

  {#if selected}<aside class="inspector"><div><b>{selected.program}</b> <span class="faint">PID {selected.pid} · {selected.user} · {selected.state} · {selected.threads} threads</span><p>{selected.command}</p><span>CPU {fmtPct(selected.cpu_pct)} · Memory {fmtBytes(selected.memory_bytes)} · I/O ↓ {fmtBytesPerSec(selected.read_bps)} ↑ {fmtBytesPerSec(selected.write_bps)}</span></div><div class="actions"><button onclick={() => signalProcess('SIGTERM')}>terminate</button><button onclick={() => signalProcess('SIGSTOP')}>stop</button><button onclick={() => signalProcess('SIGCONT')}>continue</button><button class="danger" onclick={() => signalProcess('SIGKILL')}>kill</button></div></aside>{/if}
  <footer><span>{monitorLive.state === 'live' ? 'fresh collection every 2s' : monitorLive.lastError ?? 'opening live feed'}</span><span>detail retained in this tab for up to 15m · scheduled history belongs in Metrics</span></footer>
</main>

<style>
  .monitor{--m-gap:8px;font-family:var(--mono);font-variant-numeric:tabular-nums;display:flex;flex-direction:column;gap:var(--m-gap);min-height:calc(100vh - 76px);margin:-18px -20px -48px;padding:12px;position:relative;background:var(--bg);overflow-x:hidden}.toolbar,.host-strip,footer,.inspector{border:1px solid var(--border-2);background:var(--bg-inset);display:flex;align-items:center;gap:6px;padding:6px 8px}.toolbar button,.host-strip button,.overlay button,.actions button{font:inherit;font-size:.86em;color:var(--ink-2);background:transparent;border:1px solid var(--border);padding:3px 7px;cursor:pointer}.toolbar button.on,.host-strip button.on,.overlay button.on{color:var(--bg);background:var(--accent);border-color:var(--accent);font-weight:700}.switches{display:flex;gap:2px;flex-wrap:wrap}.sep,.faint,footer{color:var(--ink-3)}.fill{flex:1}.stream{font-size:.85em;color:var(--warn)}.stream.live{color:var(--ok)}.host-strip{padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.host-strip button{border:0;border-right:1px solid var(--border);padding:8px;text-align:left;display:grid;grid-template-columns:auto 1fr auto;gap:7px;align-items:center}.host-strip small{color:var(--ink-3)}.host-strip [data-state="warn"] strong{color:var(--warn)}.host-strip [data-state="crit"] strong{color:var(--crit)}.fleet-grid,.host-grid{display:grid;gap:var(--m-gap);min-height:0;flex:1}.fleet-grid{grid-template-columns:repeat(12,minmax(0,1fr));grid-template-rows:minmax(150px,30fr) minmax(150px,30fr) minmax(170px,40fr)}.fleet-grid>:nth-child(1){grid-column:1/9}.fleet-grid>:nth-child(2){grid-column:1/5}.fleet-grid>:nth-child(3){grid-column:5/9}.fleet-grid>:nth-child(4){grid-column:1/5}.fleet-grid>:nth-child(5){grid-column:5/9}.fleet-grid .process-panel{grid-column:9/13;grid-row:1/4}.host-grid{grid-template-columns:repeat(12,minmax(0,1fr));grid-template-rows:minmax(170px,30fr) minmax(170px,35fr) minmax(170px,35fr)}.host-grid>:nth-child(1){grid-column:1/10}.host-grid>:nth-child(2){grid-column:10/13}.host-grid>:nth-child(3){grid-column:1/5}.host-grid>:nth-child(4){grid-column:5/10}.host-grid>:nth-child(5){grid-column:1/10}.host-grid .process-panel{grid-column:10/13;grid-row:2/4}.processLayout .process-panel{grid-column:1/13!important;grid-row:2/4!important}.ioLayout .process-panel{grid-column:1/7!important;grid-row:3/4!important}.ioLayout>:nth-child(4){grid-column:1/7}.ioLayout>:nth-child(5){grid-column:7/13}.host-rows,.data-table{display:flex;flex-direction:column;gap:3px}.metric-row{display:grid;grid-template-columns:58px minmax(60px,1fr) auto auto;gap:8px;align-items:center;text-align:left;border:0;background:transparent;color:inherit;font:inherit;padding:3px;cursor:pointer}.graph,.big-graph{color:var(--accent);white-space:pre;overflow:hidden}.metric-row small{color:var(--ink-3)}[data-tone="warn"]{color:var(--warn)}[data-tone="crit"]{color:var(--crit)}.mount{display:inline-block;margin-right:7px;color:var(--ink-3)}.cpu-main{display:grid;grid-template-columns:2fr 1fr;gap:12px}.big-graph{display:block;max-width:100%;font-size:1.3em}.cores{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px}.cores i{color:var(--accent);font-style:normal}.memory,.gpu{display:flex;flex-direction:column;gap:7px}.data-table>div{display:grid;grid-template-columns:90px 1fr auto;gap:8px;padding:4px 0;border-bottom:1px solid var(--border)}.mounts{display:flex;gap:8px;flex-wrap:wrap;color:var(--ink-3);font-size:.9em;margin-top:7px}.process-panel{min-height:0;height:100%;border:1px solid var(--border-2);background:var(--bg);display:flex;flex-direction:column}.inspector{justify-content:space-between;align-items:flex-start}.inspector p{margin:4px 0;max-width:80ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.actions{display:flex;gap:4px}.actions .danger{color:var(--crit);border-color:var(--crit)}footer{justify-content:space-between;font-size:.82em}.overlay{position:absolute;z-index:10;right:12px;top:50px;width:min(320px,calc(100vw - 24px));padding:10px;border:1px solid var(--accent);background:var(--bg-inset);box-shadow:0 12px 30px #0009;display:flex;gap:7px;flex-direction:column}.overlay label{display:flex;justify-content:space-between;gap:8px}.help p{line-height:1.8}.help kbd{border:1px solid var(--border);padding:2px 4px}@media(max-width:1199px){.monitor{margin:-18px -20px -48px}.fleet-grid{grid-template-columns:repeat(20,minmax(0,1fr));grid-template-rows:auto}.fleet-grid>:nth-child(n){grid-column:span 9}.fleet-grid .process-panel{grid-column:10/21;grid-row:1/4}.host-grid{grid-template-columns:repeat(20,minmax(0,1fr))}.host-grid>:nth-child(1){grid-column:1/21}.host-grid>:nth-child(2),.host-grid>:nth-child(3),.host-grid>:nth-child(4),.host-grid>:nth-child(5){grid-column:span 9}.host-grid .process-panel{grid-column:10/21;grid-row:2/5}}@media(max-width:760px){.monitor{margin:-12px -12px -40px;padding:8px;min-height:calc(100vh - 60px)}.toolbar{position:sticky;top:0;z-index:5;flex-wrap:wrap}.views{order:3;flex-basis:100%;overflow:auto;flex-wrap:nowrap}.views button{min-height:36px}.host-strip{position:sticky;top:48px;z-index:4}.host-strip button{grid-template-columns:1fr;padding:6px;font-size:.8em}.host-strip span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fleet-grid,.host-grid{display:flex;flex-direction:column}.fleet-grid>:nth-child(n),.host-grid>:nth-child(n),.fleet-grid .process-panel,.host-grid .process-panel{min-height:180px}.process-panel{min-height:360px!important}.metric-row{grid-template-columns:50px 1fr auto}.metric-row small{display:none}.cpu-main{grid-template-columns:1fr}.data-table>div{grid-template-columns:70px 1fr}.data-table>div span:last-child{display:none}.inspector{display:block}.actions{margin-top:8px;flex-wrap:wrap}footer{display:block;line-height:1.6}}
</style>
