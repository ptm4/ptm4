<script module lang="ts">
  // Shape of /api/agents/<host>/apt-status, shared with the page that polls it.
  export interface AptStatus {
    running?: boolean;
    result?: string;
    exit_status?: string;
    reboot_required?: boolean;
    finished_at?: string;
    log_tail?: string[];
    already_running?: boolean;
    ok?: boolean;
  }

  export interface TimerRow { unit: string; next: string | null; passed: string | null }

  // Everything one host card needs to render itself. All state and API calls live
  // in the parent page (Cockpit) or in the shared host-actions module — this
  // component and its callbacks are pure presentation.
  export interface HostVM {
    host: string;
    role: string;
    agent?: AgentRow;
    reachable: boolean;
    hasControls: boolean;
    isBusy: boolean;
    watchInfo?: { label: string; secs: number };
    aptState?: AptStatus;
    termUrl: string;
    wakeable: boolean;
    allowedUnits: string[];
    // vitals
    samples: VitalsSample[];
    latest: VitalsSample | null;
    vitalsError?: string | null;
    vitalsLoading: boolean;
    // disks / pool
    diskUsedPct?: number | null;
    pool?: { used_pct?: number; pool_name?: string; size_gb?: number } | null;
    // pending updates
    pkgUpdates?: UpdatePackages;
    updatesMeasuredAt?: string | null;
    imageUpdates: UpdateImage[];
    // containers — whatever the report lists for this host, no assumptions
    containers: ContainerRow[];
    containerBusy: Record<string, boolean>;
    // systemd timers
    timers: TimerRow[];
    // actions
    onReboot: () => void;
    onAptUpgrade: () => void;
    onRestartUnit: (unit: string) => void;
    onWake: () => void;
    onForceSync: () => void;
    onRestartContainer: (name: string) => void;
    onUpdateContainer: (name: string) => void;
  }
</script>

<script lang="ts">
  import Measured from '$lib/components/Measured.svelte';
  // One fleet host, control-center density: live vitals sparklines, disk/pool
  // meters, containers, allowlisted services, timers,
  // the apt log tail, and the full action row. Clicking the header toggles this
  // host's "focus" — the parent decides what that means (full width vs. a
  // one-line summary) and passes `focused`/`collapsed` down.
  import { Terminal, Zap, Power, PackagePlus, RefreshCw, RotateCw, CircleArrowUp, ScrollText, Maximize2, Minimize2 } from '@lucide/svelte';
  import type { AgentRow, ContainerRow, VitalsSample } from '$lib/api/types';
  import type { UpdateImage, UpdatePackages } from '$lib/api/fleet';
  import type { VitalsRange } from '$lib/api/queries';
  import { UNIT_LABELS } from '$lib/impact';
  import { fmtUptime, durSince, fmtBytesPerSec } from '$lib/format';
  import { Sparkline, Vital, Meter } from '$lib/widgets/kit';

  let {
    vm, range, focused, collapsed, onToggleFocus,
  }: {
    vm: HostVM;
    range: VitalsRange;
    focused: boolean;
    collapsed: boolean;
    onToggleFocus: () => void;
  } = $props();

  let times = $derived(vm.samples.map((s) => s.t));
  let showDay = $derived(range === '24h' || range === '48h');

  let statLine = $derived.by(() => {
    const l = vm.latest;
    if (!l) return 'no vitals';
    return [
      l.uptime_s != null ? `up ${fmtUptime(l.uptime_s)}` : null,
      l.load1 != null ? `load ${l.load1.toFixed(2)}` : null,
      l.cpu_pct != null ? `cpu ${Math.round(l.cpu_pct)}%` : null,
      l.mem_pct != null ? `mem ${Math.round(l.mem_pct)}%` : null,
      l.temp_c != null ? `${Math.round(l.temp_c)}°C` : null,
    ].filter(Boolean).join(' · ');
  });

  const containerKey = (name: string) => `${vm.host}/${name}`;

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleFocus(); }
  }
</script>

<section class="ck-card glass card" class:ck-focused={focused} class:ck-collapsed={collapsed}
  style:grid-column={(focused || collapsed) ? '1 / -1' : undefined}>
  <header class="ck-head" role="button" tabindex="0" aria-expanded={focused} onclick={onToggleFocus} onkeydown={onKeydown}>
    {#if focused}<Minimize2 size={14} aria-hidden="true" />{:else}<Maximize2 size={14} aria-hidden="true" />{/if}
    <span class="mono ck-host">{vm.host}</span>
    <span class="t-dim">{vm.role}</span>
    <span class="spacer"></span>
    {#if collapsed}<span class="t-dim ck-collapsed-stat">{statLine}</span>{/if}
    <span class="pill" data-s={vm.reachable ? 'ok' : 'crit'}>{vm.reachable ? 'up' : 'unreachable'}</span>
    {#if vm.agent?.agent_version}
      <span class="chip" title="hl-arch-agent version">v{vm.agent.agent_version}</span>
    {/if}
    {#if vm.pkgUpdates?.reboot_required}<span class="chip" data-s="warn">reboot req</span>{/if}
    {#if vm.imageUpdates.length > 0}<span class="chip" data-s="warn">{vm.imageUpdates.length} image{vm.imageUpdates.length > 1 ? 's' : ''}</span>{/if}
  </header>

  {#if !collapsed}
    <div class="ck-body">
      {#if vm.watchInfo}
        <div class="t-dim ck-status">⏳ {vm.watchInfo.label} — down {vm.watchInfo.secs}s…</div>
      {:else if vm.isBusy}
        <div class="t-dim ck-status">⏳ working…</div>
      {/if}

      {#if vm.pkgUpdates && vm.pkgUpdates.pending > 0}
        <div class="ck-chips">
          <span class="chip">
            {vm.pkgUpdates.pending} pkg{#if vm.pkgUpdates.security}<b class="t-crit"> · {vm.pkgUpdates.security} sec</b>{/if}
          </span>
          <!-- Package counts come from a scheduled collector, not from the host on
               demand. Saying when they were measured is what stops this chip from
               quietly lying after you have upgraded something by hand. -->
          <Measured at={vm.updatesMeasuredAt} source="software-inventory" bare />
        </div>
      {/if}

      <!-- ── vitals ──────────────────────────────────────────────────────── -->
      <div class="ck-section">
        <div class="divider">vitals</div>
        {#if vm.vitalsError}
          <div class="err">{vm.vitalsError}</div>
        {:else if vm.vitalsLoading && vm.samples.length === 0}
          <div class="t-dim">loading…</div>
        {/if}
        <div class="ck-spark-grid">
          <div class="ck-spark" style="color: var(--accent)">
            <Vital label="CPU" value={vm.latest?.cpu_pct != null ? `${Math.round(vm.latest.cpu_pct)}%` : '—'}
              pct={vm.latest?.cpu_pct} sub={vm.latest?.load1 != null ? `load ${vm.latest.load1.toFixed(2)}` : undefined} />
            <Sparkline values={vm.samples.map((s) => s.cpu_pct)} {times} height={28} {showDay}
              label={`${vm.host} cpu`} format={(v) => `${v.toFixed(1)}%`} />
          </div>
          <div class="ck-spark" style="color: var(--brand)">
            <Vital label="Memory" value={vm.latest?.mem_pct != null ? `${Math.round(vm.latest.mem_pct)}%` : '—'} pct={vm.latest?.mem_pct} />
            <Sparkline values={vm.samples.map((s) => s.mem_pct)} {times} height={28} {showDay}
              label={`${vm.host} memory`} format={(v) => `${v.toFixed(1)}%`} />
          </div>
          <div class="ck-spark" style="color: var(--c-media, var(--warn))">
            <Vital label="Temp" value={vm.latest?.temp_c != null ? `${Math.round(vm.latest.temp_c)}°C` : '—'} />
            <Sparkline values={vm.samples.map((s) => s.temp_c)} {times} height={28} {showDay}
              label={`${vm.host} temp`} format={(v) => `${v.toFixed(1)}°C`} />
          </div>
          <div class="ck-spark" style="color: var(--c-network, var(--accent))">
            <Vital label="Network">
              <span class="net-pair">↓{fmtBytesPerSec(vm.latest?.rx_bps)} ↑{fmtBytesPerSec(vm.latest?.tx_bps)}</span>
            </Vital>
            <Sparkline values={vm.samples.map((s) => s.rx_bps)} {times} height={28} {showDay}
              label={`${vm.host} net in`} format={(v) => `↓ ${fmtBytesPerSec(v)}`} />
          </div>
        </div>
        <div class="t-dim ck-vitals-foot">{statLine} · last {range}</div>
      </div>

      <!-- ── disks / pool ────────────────────────────────────────────────── -->
      {#if vm.pool || vm.diskUsedPct != null}
        <div class="ck-section">
          <div class="divider">storage</div>
          <div class="disk-rows">
            {#if vm.pool?.used_pct != null}
              <div class="disk-row">
                <span class="disk-label mono">{vm.pool.pool_name ?? 'pool'} <small>zfs</small></span>
                <Meter pct={vm.pool.used_pct} />
                <span class="disk-val">{Math.round(vm.pool.used_pct)}%{#if vm.pool.size_gb}<small> of {Math.round(vm.pool.size_gb / 100) / 10} TB</small>{/if}</span>
              </div>
            {/if}
            {#if vm.diskUsedPct != null}
              <div class="disk-row">
                <span class="disk-label mono">os disk</span>
                <Meter pct={vm.diskUsedPct} />
                <span class="disk-val">{Math.round(vm.diskUsedPct)}%</span>
              </div>
            {/if}
          </div>
        </div>
      {/if}

      <!-- ── containers ──────────────────────────────────────────────────── -->
      <div class="ck-section">
        <div class="divider">containers</div>
        {#if vm.containers.length > 0}
          <div class="ck-cont-rows">
            {#each vm.containers as c (c.name)}
              {@const busy = !!vm.containerBusy[containerKey(c.name)]}
              <div class="ck-cont-row">
                <span class="cdot" data-s={c.up ? 'ok' : 'crit'} title={c.status ?? 'unknown'}></span>
                <span class="mono ck-cont-name">{c.name}</span>
                <span class="t-dim ck-cont-since">{c.status_since ? durSince(c.status_since) : (c.status ?? '—')}</span>
                {#if c.update_available}<span class="chip" data-s="warn">update</span>{/if}
                <span class="spacer"></span>
                <button type="button" class="tb-btn sm" disabled={busy} title={`Restart ${c.name} on ${vm.host}`}
                  onclick={() => vm.onRestartContainer(c.name)}>
                  <RotateCw size={12} aria-hidden="true" /> Restart
                </button>
                {#if c.update_available}
                  <button type="button" class="tb-btn sm" disabled={busy} title="Pull newest image & recreate"
                    onclick={() => vm.onUpdateContainer(c.name)}>
                    <CircleArrowUp size={12} aria-hidden="true" /> Update
                  </button>
                {/if}
                <a class="tb-btn sm" href="/cockpit?tab=logs" title="Logs"><ScrollText size={12} aria-hidden="true" /> Logs</a>
              </div>
            {/each}
          </div>
        {:else}
          <!-- Deliberately no per-host special case. This branch used to say "opti
               runs no Docker — control plane only", which was true until the app
               tier moved there on 2026-09-10 and false the moment it did. An empty
               list is a fact about the report; why it is empty is not ours to
               assert. -->
          <p class="empty">No containers reported.</p>
        {/if}
      </div>

      <!-- ── services (allowlisted systemd units) ───────────────────────── -->
      {#if vm.reachable && vm.hasControls}
        <div class="ck-section">
          <div class="divider">services</div>
          {#if vm.allowedUnits.length > 0}
            <div class="ck-actions">
              {#each vm.allowedUnits as u (u)}
                <button type="button" class="tb-btn sm" disabled={vm.isBusy}
                  title={`systemctl restart ${u}`} onclick={() => vm.onRestartUnit(u)}>
                  ↻ {UNIT_LABELS[u] ?? u}
                </button>
              {/each}
            </div>
          {:else}
            <p class="empty">No allowlisted units.</p>
          {/if}
        </div>
      {/if}

      <!-- ── timers ──────────────────────────────────────────────────────── -->
      {#if vm.timers.length > 0}
        <div class="ck-section">
          <div class="divider">timers</div>
          <div class="kv-rows">
            {#each vm.timers.slice(0, 10) as t (t.unit)}
              <div class="kv-row"><span class="mono">{t.unit.replace('.timer', '')}</span><span>{t.passed ?? t.next ?? '—'}</span></div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- ── apt log tail ────────────────────────────────────────────────── -->
      {#if vm.aptState?.running}
        <div class="t-dim ck-status">
          ⏳ apt running… <span class="mono">{(vm.aptState.log_tail ?? []).slice(-1)[0] ?? ''}</span>
        </div>
      {:else if vm.aptState && ((vm.aptState.log_tail?.length ?? 0) > 0 || vm.aptState.finished_at)}
        <details class="ck-aptlog">
          <summary class="t-dim">apt log · {vm.aptState.finished_at ?? 'last run'}</summary>
          <pre class="mono">{(vm.aptState.log_tail ?? []).join('\n')}</pre>
        </details>
      {/if}

      <!-- ── host actions ────────────────────────────────────────────────── -->
      <div class="ck-actions">
        {#if vm.reachable && vm.hasControls}
          <button type="button" class="tb-btn danger" class:hot={!!vm.pkgUpdates?.reboot_required}
            disabled={vm.isBusy} onclick={vm.onReboot}>
            <Power size={14} aria-hidden="true" /> Reboot
          </button>
          <button type="button" class="tb-btn" disabled={vm.isBusy} onclick={vm.onAptUpgrade}>
            <PackagePlus size={14} aria-hidden="true" /> Apt upgrade
          </button>
          <button type="button" class="tb-btn" disabled={vm.isBusy} onclick={vm.onForceSync} title={`POST /api/agents/${vm.host}/sync`}>
            <RefreshCw size={14} aria-hidden="true" /> Force sync
          </button>
          <a class="tb-btn" href={vm.termUrl} target="_blank" rel="noreferrer"
            title={`Terminal on ${vm.host} via Cockpit (rpi:9090, system login)`}>
            <Terminal size={14} aria-hidden="true" /> Terminal
          </a>
        {:else if vm.reachable}
          <span class="t-dim">controls need agent v0.4.0 — reinstall hl-arch-agent.py on {vm.host}</span>
        {:else if vm.wakeable}
          <button type="button" class="tb-btn" disabled={vm.isBusy} onclick={vm.onWake}>
            <Zap size={14} aria-hidden="true" /> Wake
          </button>
        {:else}
          <span class="t-dim">unreachable — no WoL for this host, physical access needed if it is off</span>
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  /* "reboot required" gets a quiet pulse on the reboot button so it reads as a
     nudge, not just another chip on the card. */
  .hot {
    animation: hot-pulse 2.4s ease-in-out infinite;
  }
  @keyframes hot-pulse {
    0%, 100% { box-shadow: 0 0 0 0 var(--crit-dim); }
    50% { box-shadow: 0 0 0 3px var(--crit-dim); }
  }

  .ck-head { cursor: pointer; }
  .ck-head :global(svg) { flex: none; opacity: .7; }
  .ck-head:hover :global(svg) { opacity: 1; }
  .ck-collapsed-stat { font-size: var(--fs-sm); font-variant-numeric: tabular-nums; }
  .ck-focused { box-shadow: inset 0 0 0 1px var(--accent-muted); }
  .ck-collapsed { padding-top: 10px; padding-bottom: 10px; }

  .ck-body { display: flex; flex-direction: column; gap: var(--s3); }
  .ck-section { display: flex; flex-direction: column; gap: var(--s2); }

  .ck-spark-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--s3); }
  .ck-spark { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .ck-vitals-foot { font-size: var(--fs-sm); font-variant-numeric: tabular-nums; }

  .ck-cont-rows { display: flex; flex-direction: column; gap: 2px; }
  .ck-cont-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 5px 0; border-top: 1px solid var(--border); font-size: 12.5px; }
  .ck-cont-rows .ck-cont-row:first-child { border-top: 0; }
  .ck-cont-name { color: var(--ink); font-weight: 500; }
  .ck-cont-since { color: var(--ink-2); }

  @media (max-width: 640px) {
    .ck-spark-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
