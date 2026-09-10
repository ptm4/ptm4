<script lang="ts">
  // The pinned "Now" column beside the feed: hosts, incidents, storage, Pi-hole.
  // Everything here is a read-model the app already polls.
  import { useVitals, usePihole } from '$lib/api/queries';
  import { useArchLive, FALLBACK_FLEET, useHosts } from '$lib/api/fleet';
  import { useIncidents } from '$lib/api/incidents';
  import { fmtUptime, fmtNum, toneFor, clockHM } from '$lib/format';
  import { onMount } from 'svelte';

  const vitals = useVitals();
  const pihole = usePihole();
  const live = useArchLive();
  const hostsQ = useHosts();
  const incidents = useIncidents();

  let hosts = $derived((hostsQ.data ?? FALLBACK_FLEET).hosts);
  let now = $state(clockHM());
  onMount(() => { const t = setInterval(() => (now = clockHM()), 30_000); return () => clearInterval(t); });
  let date = $derived(new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }));
  let open = $derived((incidents.data?.incidents ?? []).filter((i) => i.status === 'open').slice(0, 4));
</script>

<aside class="now">
  <div class="ncard">
    <h3>Now <span class="meta num">{now} · {date}</span></h3>
    {#each hosts as h (h.name)}
      {@const v = vitals.data?.hosts?.[h.name]?.latest}
      <div class="nrow">
        <span class="grow"><a href="/host/{h.name}"><b>{h.label}</b></a>{v?.uptime_s != null ? ` · up ${fmtUptime(v.uptime_s)}` : h.intermittent ? ' · ' + h.role : ''}</span>
        {#if v}
          <span class="num">{v.load1?.toFixed(2) ?? '—'} · {v.mem_pct != null ? Math.round(v.mem_pct) + '%' : '—'} · {v.temp_c != null ? Math.round(v.temp_c) + '°' : '—'}</span>
        {:else}
          <span class="num faint">{h.intermittent ? 'offline' : vitals.isLoading ? '…' : 'no data'}</span>
        {/if}
      </div>
    {/each}
  </div>

  <div class="ncard">
    <h3>Incidents <span class="meta" class:t-warn={(incidents.data?.open ?? 0) > 0}>{incidents.data ? `${incidents.data.open} open · ${incidents.data.muted} muted` : incidents.isError ? 'unavailable' : '…'}</span></h3>
    {#each open as i (i.id)}
      <a class="inc" href="/feed?view=incidents#{i.id}"><span class="sev" data-s={i.severity}></span><span class="grow">{i.title}</span><span class="num faint">{i.host ?? 'fleet'}</span></a>
    {/each}
    {#if incidents.data && open.length === 0}<div class="nrow"><span class="grow faint">Nothing open.</span></div>{/if}
    {#if incidents.isError}<div class="nrow"><span class="grow faint">This backend has no /api/incidents yet.</span></div>{/if}
  </div>

  <div class="ncard">
    <h3>Storage</h3>
    {#each Object.values(live.data?.hosts ?? {}) as h (h.host)}
      {#if h.pool?.used_pct != null}
        <div class="meterline"><span class="lab">{h.pool.pool_name ?? 'pool'} · zfs</span><div class="bar" data-s={toneFor(h.pool.used_pct)}><i style="width: {h.pool.used_pct}%"></i></div><span class="num">{fmtNum(h.pool.used_pct)}%</span></div>
      {/if}
      {#if h.disk_used_pct != null}
        <div class="meterline"><span class="lab">{h.host} os</span><div class="bar" data-s={toneFor(h.disk_used_pct)}><i style="width: {h.disk_used_pct}%"></i></div><span class="num">{fmtNum(h.disk_used_pct)}%</span></div>
      {/if}
    {/each}
    {#if live.isError}<div class="nrow"><span class="grow faint">no reports</span></div>{/if}
  </div>

  <div class="ncard">
    <h3>Pi-hole <span class="meta" class:t-ok={pihole.data?.blocking?.enabled}>{pihole.data ? (pihole.data.blocking?.enabled ? 'blocking' : 'paused') : pihole.isError ? 'unreachable' : '…'}</span></h3>
    {#if pihole.data}
      <div class="nrow"><span class="grow">{pihole.data.ads_percentage_today != null ? `${pihole.data.ads_percentage_today.toFixed(1)}% blocked` : '—'}</span><span class="num faint">{fmtNum(pihole.data.ads_blocked_today)} / {fmtNum(pihole.data.dns_queries_today)}</span></div>
      <div class="nrow"><span class="grow faint">gravity {fmtNum(pihole.data.gravity_domains)} · <a href="/cockpit?tab=pihole">manage</a></span></div>
    {/if}
  </div>
</aside>

<style>
  .now { display: flex; flex-direction: column; gap: 10px; position: sticky; top: 56px; min-width: 0; }
  .ncard { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 10px 13px; }
  .ncard h3 { font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-3); margin: 0 0 6px; display: flex; font-weight: 600; }
  .ncard h3 .meta { margin-left: auto; font-weight: 400; letter-spacing: 0; text-transform: none; }
  .nrow { display: flex; gap: 8px; align-items: baseline; padding: 2px 0; font-size: 12.5px; }
  .nrow .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
  .nrow .grow b { color: var(--ink); font-weight: 550; }
  .nrow .grow a { color: inherit; }
  .nrow .num { font-size: 11.5px; }
  .inc { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12.5px; border-top: 1px solid var(--border); color: inherit; text-decoration: none; }
  .inc:first-of-type { border-top: 0; }
  .inc:hover .grow { color: var(--accent); }
  .inc .sev { width: 8px; height: 8px; border-radius: 2px; flex: none; background: var(--ink-3); }
  .inc .sev[data-s="crit"] { background: var(--crit); } .inc .sev[data-s="warn"] { background: var(--warn); }
  .inc .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 1080px) { .now { position: static; } }
</style>
