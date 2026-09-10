<script lang="ts">
  // The panel beside the map: everything the fleet knows about one host, with the
  // same actions the host tile offers, and the door to the full host page.
  import { ArrowRight, Power, PackagePlus, Terminal } from '@lucide/svelte';
  import type { FleetHost, Dependency, ArchLiveHost } from '$lib/api/fleet';
  import type { VitalsSample } from '$lib/api/types';
  import { fmtUptime, fmtNum, toneFor } from '$lib/format';
  import { createHostActions } from '$lib/host-actions.svelte';
  import Meter from '$lib/widgets/kit/Meter.svelte';

  let { host, vitals, live, containers, updates, depends }: {
    host: FleetHost;
    vitals: VitalsSample | null;
    live: ArchLiveHost | null;
    containers: { up: number; total: number };
    updates: number;
    depends: Dependency[];
  } = $props();

  const actions = createHostActions(() => host.name);
  let dependants = $derived(depends.filter((d) => d.to === host.name));
  let dependsOn = $derived(depends.filter((d) => d.from === host.name));
  let off = $derived(!vitals);
</script>

<div class="insp card">
  <div class="head">
    <span class="name">{host.label}</span>
    <span class="role">{host.role} · {host.ip}</span>
    <span class="up num" data-s={off ? 'off' : 'ok'}>{off ? (host.intermittent ? 'offline' : host.agent ? 'unreachable' : 'no agent') : `up ${fmtUptime(vitals?.uptime_s)}`}</span>
  </div>
  {#if vitals}
    <div class="vitals">
      <div class="vit"><div class="l">CPU load</div><div class="v num">{vitals.load1 == null ? '—' : vitals.load1.toFixed(2)}</div></div>
      <div class="vit"><div class="l">Memory</div><div class="v num">{vitals.mem_pct == null ? '—' : `${Math.round(vitals.mem_pct)}%`}</div></div>
      <div class="vit"><div class="l">Temp</div><div class="v num">{vitals.temp_c == null ? '—' : `${Math.round(vitals.temp_c)}°C`}</div></div>
      <div class="vit"><div class="l">Containers</div><div class="v num">{containers.total ? `${containers.up}/${containers.total}` : '—'}</div></div>
    </div>
  {:else}
    <p class="empty" style="padding: 0">{host.vitals_error ?? (host.intermittent ? 'Intermittently online by design.' : 'No vitals from this host.')}</p>
  {/if}
  {#if live?.pool?.used_pct != null}
    <div class="meterline"><span class="lab">{live.pool.pool_name ?? 'pool'} · zfs</span><div class="bar" data-s={toneFor(live.pool.used_pct)}><i style="width: {live.pool.used_pct}%"></i></div><span class="num">{fmtNum(live.pool.used_pct)}%</span></div>
  {/if}
  {#if live?.disk_used_pct != null}
    <div class="meterline"><span class="lab">os disk</span><div class="bar" data-s={toneFor(live.disk_used_pct)}><i style="width: {live.disk_used_pct}%"></i></div><span class="num">{fmtNum(live.disk_used_pct)}%</span></div>
  {/if}
  <div class="chips">
    {#if host.spof}<span class="chip" data-s="warn">{host.spof} SPOF</span>{/if}
    {#if updates > 0}<span class="chip" data-s="warn">{updates} image update{updates === 1 ? '' : 's'}</span>{/if}
    {#if live?.pending_updates}<span class="chip" data-s="warn">{live.pending_updates} apt</span>{/if}
    {#if live?.doctor_status}<span class="chip" data-s={live.doctor_status === 'ok' ? 'ok' : live.doctor_status === 'warn' ? 'warn' : 'crit'}>doctor {live.doctor_status}</span>{/if}
  </div>
  {#if host.agent}
    <div class="chips">
      <a class="chip act" href={actions.termUrl} target="_blank" rel="noreferrer"><Terminal size={11} aria-hidden="true" /> Terminal</a>
      <button class="chip act" disabled={actions.busy || off} onclick={() => actions.aptUpgrade()}><PackagePlus size={11} aria-hidden="true" /> Apt upgrade</button>
      <button class="chip act danger" disabled={actions.busy || off} onclick={() => actions.reboot()}><Power size={11} aria-hidden="true" /> Reboot…</button>
    </div>
  {/if}
  {#if dependants.length || dependsOn.length}
    <div class="deps">
      {#if dependants.length}<b>{dependants.length} host{dependants.length === 1 ? '' : 's'} depend on this node.</b><br>{dependants.map((d) => `${d.from} ${d.why}`).join(' · ')}{/if}
      {#if dependsOn.length}<div class="faint" style="margin-top: 4px">Depends on {dependsOn.map((d) => `${d.to} (${d.why})`).join(', ')}.</div>{/if}
    </div>
  {/if}
  <a class="hostlink" href="/host/{host.name}">Open host page <ArrowRight size={13} aria-hidden="true" /></a>
</div>

<style>
  .insp { gap: 10px; }
  .head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .head .name { font-size: 17px; font-weight: 650; letter-spacing: -.01em; }
  .head .role { color: var(--ink-3); font-size: 11.5px; }
  .head .up { margin-left: auto; color: var(--ok); font-size: 11px; }
  .head .up[data-s="off"] { color: var(--ink-3); }
  .chip.act { display: inline-flex; align-items: center; gap: 5px; font-family: inherit; }
  .chip.act.danger:hover { color: var(--crit); border-color: var(--crit-muted); }
  .chip.act:disabled { opacity: .5; cursor: default; }
  .deps { border-top: 1px solid var(--border); padding-top: 8px; font-size: 11.5px; color: var(--ink-2); line-height: 1.5; }
  .deps b { color: var(--ink); }
  .hostlink { margin-top: auto; display: flex; align-items: center; justify-content: space-between; font-size: 12px; border-top: 1px solid var(--border); padding-top: 8px; }
</style>
