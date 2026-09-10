<script lang="ts">
  // /host/:name — everything about one machine on one page, composed from read
  // models the dashboard already polls (plus the host-vitals, changes and long-trend
  // widgets, reused as building blocks).
  import { page } from '$app/state';
  import { Power, PackagePlus, Terminal, ExternalLink } from '@lucide/svelte';
  import { useContainers, useTimers, useRunnerReport } from '$lib/api/queries';
  import { useHosts, useArchLive, useUpdates, FALLBACK_FLEET } from '$lib/api/fleet';
  import { createHostActions } from '$lib/host-actions.svelte';
  import { durSince, relTime, fmtUptime, fmtNum, toneFor } from '$lib/format';
  import HostVitals from '$lib/widgets/system/HostVitals.svelte';
  import Changes from '$lib/widgets/hldb/Changes.svelte';
  import LongTrends from '$lib/widgets/hldb/LongTrends.svelte';

  let name = $derived(page.params.name ?? '');
  const hostsQ = useHosts();
  const containers = useContainers();
  const timers = useTimers();
  const live = useArchLive();
  const updates = useUpdates();
  const hardware = useRunnerReport(() => 'hardware-latest');
  const actions = createHostActions(() => name);

  let host = $derived((hostsQ.data ?? FALLBACK_FLEET).hosts.find((h) => h.name === name) ?? null);
  let known = $derived(!!host);
  let cs = $derived(containers.data?.hosts.find((h) => h.host === name)?.containers ?? []);
  let ts = $derived(timers.data?.hosts.find((h) => h.host === name)?.timers ?? []);
  let lv = $derived(live.data?.hosts?.[name] ?? null);
  let images = $derived(updates.data?.images.filter((u) => u.host === name) ?? []);
  let pkgs = $derived(updates.data?.packages.find((p) => p.host === name) ?? null);
  let hw = $derived(hardware.data?.hosts?.find((h) => h.host === name) ?? null);
  let hwMetrics = $derived.by(() => {
    const m = (hw?.metrics ?? {}) as Record<string, unknown>;
    const out: [string, string][] = [];
    for (const [k, v] of Object.entries(m)) {
      if (v == null || typeof v === 'object') continue;
      out.push([k.replace(/_/g, ' '), String(v)]);
    }
    return out.slice(0, 14);
  });
  let hasAgent = $derived(host?.agent ?? false);
</script>

{#if !known}
  <div class="card"><p class="err">Unknown host “{name}”.</p><a class="tbtn" href="/topology">Topology</a></div>
{:else if host}
  <div class="host-page">
    <div class="shead hero">
      <div>
        <h1>{host.label}</h1>
        <div class="sub dim">{host.role} · {host.ip}{host.os ? ` · ${host.os}` : ''}{host.vitals?.uptime_s != null ? ` · up ${fmtUptime(host.vitals.uptime_s)}` : ''}{lv?.doctor_status ? ` · doctor ${lv.doctor_status}` : ''}</div>
      </div>
      <div class="right">
        {#if host.spof}<span class="chip" data-s="warn">{host.spof} SPOF</span>{/if}
        {#if hasAgent}
          <a class="tbtn" href={actions.termUrl} target="_blank" rel="noreferrer"><Terminal /> Terminal</a>
          <button class="tbtn" disabled={actions.busy} onclick={() => actions.aptUpgrade()}><PackagePlus /> Apt upgrade</button>
          <button class="tbtn danger" disabled={actions.busy} onclick={() => actions.reboot()}><Power /> Reboot…</button>
        {:else if host.name === 'android'}
          <a class="tbtn" href="/llm">Local LLM →</a>
        {/if}
      </div>
    </div>

    <div class="grid">
      {#if hasAgent}
        <div class="c6 vitals-slot"><HostVitals options={{ host: name, range: '3h' }} /></div>
      {:else}
        <section class="card c6"><div class="chead"><h3>Vitals</h3></div><p class="empty">{host.intermittent ? 'This device is online only when it wants to be — no agent, no vitals.' : 'No hl-arch-agent on this host.'}</p></section>
      {/if}

      <section class="card c6">
        <div class="chead"><h3>Containers</h3><span class="meta">{cs.length ? `${cs.filter((c) => c.up).length}/${cs.length} up` : 'none'}</span></div>
        {#if containers.isLoading}<div class="spin"></div>{/if}
        {#if cs.length}
          <div class="tablewrap">
            <table class="t">
              <thead><tr><th></th><th>Name</th><th>Since</th><th>Image</th><th></th></tr></thead>
              <tbody>
                {#each cs as c (c.name)}
                  <tr>
                    <td><span class="cdot" data-s={c.up ? 'ok' : 'crit'}></span></td>
                    <td>{c.name}</td>
                    <td class="num">{c.status_since ? durSince(c.status_since) : (c.status ?? '—')}</td>
                    <td class="mono faint" style="max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{c.image ?? '—'}</td>
                    <td>{#if c.update_available}<span class="chip" data-s="warn">update</span>{/if}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          <a class="faint" style="font-size: 11.5px" href="/cockpit?tab=containers">Manage on the Containers page →</a>
        {:else if !containers.isLoading}
          <p class="empty">No containers reported for {host.name}.</p>
        {/if}
      </section>

      <section class="card c4">
        <div class="chead"><h3>Pending updates</h3><span class="meta">{updates.data?.collected_at ? relTime(updates.data.collected_at) : ''}</span></div>
        {#if pkgs}
          <div class="stat"><span class="v num" data-s={pkgs.security ? 'crit' : 'warn'}>{pkgs.pending}<small>packages</small></span><span class="l">{pkgs.security} security{pkgs.reboot_required ? ' · reboot required' : ''}</span></div>
        {/if}
        <div class="rows">
          {#each images as u (u.container)}
            <div class="row"><span class="who">{u.container}</span><span class="what mono">{u.image ?? ''}</span><span class="chip" data-s={u.self ? 'crit' : 'warn'}>{u.self ? 'self' : 'image'}</span></div>
          {/each}
        </div>
        {#if !pkgs && images.length === 0}<p class="empty">Nothing pending.</p>{/if}
        <a class="faint" style="font-size: 11.5px" href="/cockpit?tab=updates">Updates queue →</a>
      </section>

      <section class="card c4">
        <div class="chead"><h3>Timers</h3><span class="meta">{ts.length} units</span></div>
        <div class="rows">
          {#each ts.slice(0, 12) as t (t.unit)}
            <div class="row"><span class="who mono" style="min-width: 0; overflow: hidden; text-overflow: ellipsis">{t.unit.replace('.timer', '')}</span><span class="what"></span><span class="num faint">{t.passed ?? '—'}</span></div>
          {/each}
          {#if ts.length === 0}<p class="empty">No systemd timers reported{host.agent ? '' : ' (no agent)'}.</p>{/if}
        </div>
      </section>

      <section class="card c4">
        <div class="chead"><h3>Hardware</h3><span class="meta">{hardware.data?.run_at ? relTime(hardware.data.run_at) : 'daily'}</span></div>
        {#if lv?.pool?.used_pct != null}
          <div class="meterline"><span class="lab">{lv.pool.pool_name ?? 'pool'}</span><div class="bar" data-s={toneFor(lv.pool.used_pct)}><i style="width: {lv.pool.used_pct}%"></i></div><span class="num">{fmtNum(lv.pool.used_pct)}%</span></div>
        {/if}
        {#if lv?.disk_used_pct != null}
          <div class="meterline"><span class="lab">os disk</span><div class="bar" data-s={toneFor(lv.disk_used_pct)}><i style="width: {lv.disk_used_pct}%"></i></div><span class="num">{fmtNum(lv.disk_used_pct)}%</span></div>
        {/if}
        <div class="kv-rows">
          {#each hwMetrics as [k, v] (k)}
            <div class="kv-row"><span>{k}</span><span class="num">{v}</span></div>
          {/each}
          {#if hwMetrics.length === 0}<p class="empty">No hardware report for this host.</p>{/if}
        </div>
        {#if hw?.summary}<p class="faint" style="font-size: 11.5px; margin: 0">{hw.summary}</p>{/if}
      </section>

      <div class="c6 widget-slot"><Changes options={{ days: 14, host: name }} /></div>
      <div class="c6 widget-slot"><LongTrends options={{ metric: 'disk_used_pct', days: 30, host: name }} /></div>
    </div>

    <p class="faint" style="font-size: 11.5px; margin: 0">
      <ExternalLink size={11} aria-hidden="true" style="vertical-align: -1px" />
      More on this host: <a href="/architecture/">architecture map</a> · <a href="/data?tab=query">query homelab.db</a> · <a href="/cockpit">cockpit</a>
    </p>
  </div>
{/if}

<style>
  .host-page { display: flex; flex-direction: column; gap: 18px; }
  .hero { align-items: flex-end; flex-wrap: wrap; row-gap: 8px; }
  .hero .sub { font-size: 12.5px; margin-top: 2px; }
  .vitals-slot { min-height: 460px; }
  .widget-slot { min-height: 280px; }
  .vitals-slot > :global(.w-card), .widget-slot > :global(.w-card) { height: 100%; }
  .stat .v[data-s="warn"] { color: var(--warn); }
  .stat .v[data-s="crit"] { color: var(--crit); }
</style>
