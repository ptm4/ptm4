<script lang="ts">
  // Right-side detail drawer for one container row: identity + ports (clickable
  // when published) + a live Dozzle deep link + a compact embedded log preview +
  // update-available digests (joined from useUpdates()) + the same action buttons
  // as the table row. A simple fixed panel (not bits-ui) so it can go full-screen
  // at 375px without fighting the shared centered .modal sizing.
  import { X, RotateCw, CircleArrowUp, ScrollText, ExternalLink } from '@lucide/svelte';
  import { durSince, localeDateTime } from '$lib/format';
  import { CRITICAL_CONTAINERS, SELF_CONTAINERS } from '$lib/impact';
  import type { UpdateImage } from '$lib/api/fleet';

  export interface DrawerRow {
    key: string;
    host: string;
    name: string;
    image: string | null;
    project: string | null;
    ports: { container_port?: string; host_port?: string; host_ip?: string; proto?: string }[];
    status: string | null;
    since: string | null;
    up: boolean;
    update: boolean;
    id?: string;
    health?: string;
    liveState?: string;
  }

  let {
    row,
    dozzleLive,
    updateInfo,
    busy,
    onclose,
    onrestart,
    onupdate,
    onopenlogs,
  }: {
    row: DrawerRow;
    dozzleLive: boolean;
    updateInfo: UpdateImage | null;
    busy: boolean;
    onclose: () => void;
    onrestart: () => void;
    onupdate: () => void;
    onopenlogs: () => void;
  } = $props();

  const shortDigest = (d: string | null | undefined) => {
    if (!d) return '—';
    const i = d.indexOf(':');
    return i === -1 ? d.slice(0, 14) : `${d.slice(0, i)}:${d.slice(i + 1, i + 13)}`;
  };

  const danger = $derived(CRITICAL_CONTAINERS[row.name]);
  const isSelf = $derived(SELF_CONTAINERS.has(row.name));
</script>

<div class="modal-overlay" role="button" tabindex="-1" aria-label="Close details"
  onclick={onclose} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') onclose(); }}></div>
<div class="dr-panel" role="dialog" aria-modal="true" aria-label="{row.name} details">
  <div class="modal-head">
    <div class="dr-head-text">
      <span class="dr-name mono">{row.name}</span>
      <span class="chip act">{row.host}</span>
      {#if row.health === 'unhealthy'}<span class="badge badge-alert">UNHEALTHY</span>{/if}
      {#if row.update}<span class="badge badge-stale">update</span>{/if}
    </div>
    <button class="tbtn icon" aria-label="Close" onclick={onclose}><X /></button>
  </div>

  <div class="modal-body dr-body">
    <section class="dr-block">
      <h3>Identity</h3>
      <div class="dr-kv"><span class="faint">image</span><span class="mono">{row.image ?? '—'}</span></div>
      <div class="dr-kv"><span class="faint">compose project</span><span>{row.project ?? '—'}</span></div>
      <div class="dr-kv"><span class="faint">state</span>
        <span class:t-ok={row.up} class:t-crit={!row.up}>{row.liveState ?? row.status ?? (row.up ? 'running' : 'down')}</span>
      </div>
      <div class="dr-kv"><span class="faint">since</span>
        <span title={localeDateTime(row.since)}>{row.since ? `${durSince(row.since)} ago` : '—'}</span>
      </div>
      {#if isSelf}
        <p class="faint">Serves this dashboard — restarting or updating it will drop this page's own connection; that is expected.</p>
      {/if}
      {#if danger}
        <p class="t-warn">{danger}</p>
      {/if}
    </section>

    <section class="dr-block">
      <h3>Ports</h3>
      {#if row.ports.length}
        {#each row.ports as p}
          <div class="dr-port-row mono">
            <span>{p.container_port ?? '?'}/{p.proto ?? 'tcp'}</span>
            {#if p.host_port}
              <span class="faint">→</span>
              <a href="http://{row.host}.lan:{p.host_port}" target="_blank" rel="noopener noreferrer">
                http://{row.host}.lan:{p.host_port} <ExternalLink size={11} aria-hidden="true" />
              </a>
            {:else}
              <span class="faint">not published</span>
            {/if}
          </div>
        {/each}
      {:else}
        <p class="faint">No published ports.</p>
      {/if}
    </section>

    {#if row.update}
      <section class="dr-block">
        <h3>Update available</h3>
        {#if updateInfo}
          <div class="dr-kv"><span class="faint">current digest</span><span class="mono">{shortDigest(updateInfo.current_digest)}</span></div>
          <div class="dr-kv"><span class="faint">available digest</span><span class="mono">{shortDigest(updateInfo.available_digest)}</span></div>
        {:else}
          <p class="faint">Digest details unavailable — the fleet update report has not seen this container yet.</p>
        {/if}
      </section>
    {/if}

    <section class="dr-block">
      <h3>Logs</h3>
      {#if row.id}
        <iframe class="dr-logs-frame" src="/dozzle/container/{row.id}" title="{row.name} logs"></iframe>
        <a class="tbtn sm" href="/dozzle/container/{row.id}" target="_blank" rel="noopener noreferrer">
          <ScrollText size={13} aria-hidden="true" /> Open in Dozzle
        </a>
      {:else}
        <p class="faint">
          No live id yet{dozzleLive ? '' : ' — Dozzle stream is offline'}.
        </p>
        <button class="tbtn sm" onclick={onopenlogs}><ScrollText size={13} aria-hidden="true" /> Open Logs page</button>
      {/if}
    </section>
  </div>

  <div class="dr-actions">
    <button class="tbtn" disabled={busy} onclick={onrestart}><RotateCw aria-hidden="true" /> Restart</button>
    {#if row.update}
      <button class="tbtn primary" disabled={busy} onclick={onupdate}><CircleArrowUp aria-hidden="true" /> Update</button>
    {/if}
    {#if row.id}
      <button class="tbtn" onclick={onopenlogs}><ScrollText aria-hidden="true" /> Open full logs</button>
    {/if}
  </div>
</div>

<style>
  /* A right-side drawer built on the shared .modal-overlay/.modal-head/.modal-body
     vocabulary but repositioned — full-height, docked right, full-screen under
     480px. Colors/spacing come from the shared tokens (CSS variables only). */
  .dr-panel {
    position: fixed;
    z-index: 95;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(440px, 100vw);
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-left: 1px solid var(--border-2);
    box-shadow: var(--sh-2);
    outline: none;
  }
  .dr-head-text { display: flex; align-items: center; gap: var(--s2); flex: 1; flex-wrap: wrap; }
  .dr-name { font-size: 14px; font-weight: 600; color: var(--ink); }
  .dr-body { flex: 1; display: flex; flex-direction: column; gap: var(--s4); }
  .dr-block h3 { margin: 0 0 var(--s2); font-size: var(--fs-xs); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3); }
  .dr-kv { display: flex; justify-content: space-between; gap: var(--s3); padding: 3px 0; font-size: 12.5px; border-bottom: 1px solid var(--border); }
  .dr-kv:last-child { border-bottom: 0; }
  .dr-port-row { display: flex; align-items: center; gap: var(--s2); padding: 3px 0; font-size: 12px; flex-wrap: wrap; }
  .dr-port-row a { display: inline-flex; align-items: center; gap: 4px; }
  .dr-logs-frame { width: 100%; height: 220px; border: 0; border-radius: var(--r); background: var(--bg-inset); margin-bottom: var(--s2); }
  .dr-actions { display: flex; gap: var(--s2); padding: var(--s3) var(--s4); border-top: 1px solid var(--border); flex-wrap: wrap; }
  @media (max-width: 480px) {
    .dr-panel { width: 100vw; }
  }
</style>
