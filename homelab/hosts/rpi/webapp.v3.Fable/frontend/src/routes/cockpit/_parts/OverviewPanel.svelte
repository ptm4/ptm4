<script lang="ts">
  // Control center: fleet-wide command bar (FleetBar) plus one dense, focusable
  // card per host (HostCard) — live vitals sparklines, disk/pool meters,
  // containers, allowlisted systemd services, timers, and every host action.
  // Rebuilt from the original Cockpit; every safety gate below is load-bearing
  // and carried over verbatim:
  //   - rebooting rpi kills the connection serving this page; a dropped fetch
  //     there IS success, and the watcher then polls /api/health (parsed as
  //     JSON, since nginx serves a 200 holding page during the boot window).
  //     That logic lives in $lib/host-actions.svelte.ts and is reused as-is.
  //   - restarting/updating a SELF_CONTAINERS container (webapp/nginx-webapp)
  //     can drop or 502/504 the very request that asked for it — that IS
  //     success too, never a red failure toast.
  //   - the timeout ladder: fetches here sit above the backend's caps and below
  //     nginx's 240s on /api/agents.
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { get, post, type ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import {
    useAgents, useContainers, useTimers, useVitals, useVitalsRange,
    VITALS_RANGES, type VitalsRange,
  } from '$lib/api/queries';
  import { useArchLive, useUpdates } from '$lib/api/fleet';
  import { createHostActions, termUrlFor } from '$lib/host-actions.svelte';
  import { CRITICAL_UNITS, HOST_ROLES, UNIT_IMPACT, CRITICAL_CONTAINERS, SELF_CONTAINERS } from '$lib/impact';
  import { HOSTS as NAV_HOSTS } from '$lib/nav';
  import type { AgentRow } from '$lib/api/types';
  import HostCard, { type AptStatus, type HostVM } from './HostCard.svelte';
  import FleetBar from './FleetBar.svelte';

  // The three hosts with an agent — android is status-only and rendered separately.
  const HOST_IDS = NAV_HOSTS.filter((h) => h.name !== 'android').map((h) => h.name);
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const isRange = (v: unknown): v is VitalsRange => VITALS_RANGES.includes(v as VitalsRange);

  const qc = useQueryClient();

  // ── page-level vitals range + focus, persisted across visits ───────────────
  let range = $state<VitalsRange>((() => {
    try { const v = localStorage.getItem('cockpit:range'); return isRange(v) ? v : '3h'; } catch { return '3h'; }
  })());
  $effect(() => {
    try { localStorage.setItem('cockpit:range', range); } catch { /* private mode */ }
  });

  let focus = $state<string | null>((() => {
    try {
      const v = localStorage.getItem('cockpit:focus');
      return v && HOST_IDS.includes(v) ? v : null;
    } catch { return null; }
  })());
  $effect(() => {
    try {
      if (focus) localStorage.setItem('cockpit:focus', focus);
      else localStorage.removeItem('cockpit:focus');
    } catch { /* private mode */ }
  });

  // ── read models — each hook dedupes with every other reader of the same
  // endpoint, so calling useAgents()/useContainers() here and inside widgets
  // elsewhere on the page still makes one request per interval. ──────────────
  const agents = useAgents();
  const vitalsRollup = useVitals();
  const containersQ = useContainers();
  const timersQ = useTimers();
  const archLive = useArchLive();
  const updatesQ = useUpdates();
  const vitalsSeries = Object.fromEntries(HOST_IDS.map((h) => [h, useVitalsRange(() => h, () => range)])) as
    Record<string, ReturnType<typeof useVitalsRange>>;

  // ── reboot / apt: delegated to the shared host-actions module — same typed
  // confirm, ZFS-guard 409 handling, and "a dropped rpi connection IS success". ──
  const hostActions = Object.fromEntries(HOST_IDS.map((h) => [h, createHostActions(() => h)])) as
    Record<string, ReturnType<typeof createHostActions>>;

  // ── apt-status log tail: page-owned. Idles (no poll) until a run is seen in
  // flight, then polls every 5s; a falling running-edge fires the same
  // completion toast v2's pollAptStatus() did. ──
  function useAptStatus(host: string) {
    return createQuery(() => ({
      queryKey: ['apt-status', host],
      queryFn: () => get<AptStatus>(`/api/agents/${host}/apt-status`, 10_000),
      retry: 0,
      refetchInterval: (query) => (query.state.data?.running ? 5000 : false),
    }));
  }
  const aptQueries = Object.fromEntries(HOST_IDS.map((h) => [h, useAptStatus(h)])) as
    Record<string, ReturnType<typeof useAptStatus>>;
  const prevAptRunning: Record<string, boolean> = {};
  $effect(() => {
    for (const host of HOST_IDS) {
      const d = aptQueries[host].data;
      if (d) {
        if (prevAptRunning[host] && !d.running) {
          const good = d.result === 'success' || d.exit_status === '0';
          toast(
            good
              ? `Apt upgrade finished on ${host}${d.reboot_required ? ' — reboot required to finish.' : '.'}`
              : `Apt upgrade on ${host} ended with result "${d.result ?? '?'}" — see the log on its card.`,
            good ? 'ok' : 'crit', { sticky: !good },
          );
          qc.invalidateQueries({ queryKey: ['agents'] });
        }
        prevAptRunning[host] = !!d.running;
      }
    }
  });
  async function doAptUpgrade(host: string) {
    await hostActions[host].aptUpgrade();
    aptQueries[host].refetch();
  }

  // ── restart-service / wake / force-sync: not covered by host-actions.svelte.ts,
  // ported here verbatim from v2 (same busy/"down Xs" watch state). ──
  let localBusy = $state<Set<string>>(new Set());
  let watch = $state<Record<string, { label: string; t0: number; secs: number }>>({});
  const watchToken: Record<string, number> = {};

  function setBusyFor(host: string, on: boolean) {
    const n = new Set(localBusy);
    if (on) n.add(host); else n.delete(host);
    localBusy = n;
  }

  // Poll until the host answers again; drives the "down Xs" line on its card.
  async function watchHostReturn(host: string, label = 'rebooting') {
    const t0 = Date.now();
    watchToken[host] = t0;
    setBusyFor(host, true);
    watch = { ...watch, [host]: { label, t0, secs: 0 } };

    const giveUpMs = 10 * 60 * 1000;
    while (Date.now() - t0 < giveUpMs) {
      await sleep(5000);
      if (watchToken[host] !== t0) return; // superseded by a newer watch
      if (watch[host]) {
        watch = { ...watch, [host]: { ...watch[host], secs: Math.round((Date.now() - t0) / 1000) } };
      }

      let back = false;
      try {
        if (host === 'rpi') {
          // Must parse as JSON, not just res.ok: during the boot window nginx
          // serves the 200 "_restarting" holding page, a false recovery.
          const health = await get<{ status?: string }>('/api/health', 4000);
          back = health?.status === 'ok';
        }
        if (!back) {
          const a = await get<{ hosts: AgentRow[] }>('/api/agents', 8000);
          back = !!a.hosts.find((h) => h.id === host)?.reachable;
          qc.setQueryData(['agents'], a);
        }
      } catch { /* still down — the gap is the honest answer */ }

      if (back) {
        const n = { ...watch }; delete n[host]; watch = n;
        setBusyFor(host, false);
        toast(`${host} is back online after ${Math.round((Date.now() - t0) / 1000)}s.`, 'ok');
        qc.invalidateQueries({ queryKey: ['agents'] });
        qc.invalidateQueries({ queryKey: ['containers'] });
        return;
      }
    }
    const n = { ...watch }; delete n[host]; watch = n;
    setBusyFor(host, false);
    toast(`${host} has not come back after 10 minutes — check it directly.`, 'crit', { sticky: true });
  }

  async function restartUnit(host: string, unit: string) {
    const critical = CRITICAL_UNITS.has(unit);
    let body = `Runs systemctl restart ${unit} on ${host}.`;
    if (unit === 'hl-arch-agent.service') {
      body += '\n\nThis is the agent itself — it responds first and restarts ~2s later.';
    }
    if (unit === 'vpn-stack-heal.service') {
      body += '\n\nvpn-stack-heal is a oneshot: this simply runs the heal check now.';
    }
    const ok = await confirm({
      title: `Restart ${unit}?`,
      tone: critical ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: critical ? unit : null,
      body,
      danger: UNIT_IMPACT[unit],
    });
    if (!ok) return;
    setBusyFor(host, true);
    try {
      // 170s sits above the backend's 160s cap and below nginx's 240s.
      const d = await post<{ ok?: boolean; self_restart?: boolean }>(
        `/api/agents/${host}/restart-service`, { unit }, 170_000);
      setBusyFor(host, false);
      if (d?.self_restart) {
        toast(`Agent on ${host} is restarting itself — its card refreshes shortly.`, 'warn');
        setTimeout(() => qc.invalidateQueries({ queryKey: ['agents'] }), 6000);
      } else {
        toast(`${unit} restarted on ${host}.`, 'ok');
        qc.invalidateQueries({ queryKey: ['containers'] });
      }
    } catch (e) {
      setBusyFor(host, false);
      toast(`Restart of ${unit} on ${host} failed: ${(e as Error).message}`, 'crit', { sticky: true });
    }
  }

  async function wakeHost(host: string) {
    setBusyFor(host, true);
    try {
      const d = await post<{ sent_by?: string }>(`/api/agents/${host}/wake`, undefined, 15_000);
      toast(`Wake packet sent to ${host}${d?.sent_by ? ` by ${d.sent_by}` : ''} — watching for it to return…`, 'warn');
      watchHostReturn(host, 'waking');
    } catch (e) {
      setBusyFor(host, false);
      toast(`Wake failed: ${(e as Error).message}`, 'crit', { sticky: true });
    }
  }

  async function forceSync(host: string) {
    setBusyFor(host, true);
    try {
      await post(`/api/agents/${host}/sync`, undefined, 20_000);
      toast(`${host} synced.`, 'ok');
      qc.invalidateQueries({ queryKey: ['agents'] });
      qc.invalidateQueries({ queryKey: ['vitals'] });
      qc.invalidateQueries({ queryKey: ['vitals-range', host] });
      qc.invalidateQueries({ queryKey: ['containers'] });
      qc.invalidateQueries({ queryKey: ['timers'] });
      qc.invalidateQueries({ queryKey: ['arch-live'] });
    } catch (e) {
      toast(`Sync of ${host} failed: ${(e as Error).message}`, 'crit', { sticky: true });
    } finally {
      setBusyFor(host, false);
    }
  }

  // ── container restart/update: same blast-radius gates as the Containers page —
  // CRITICAL_CONTAINERS typed confirm, and SELF_CONTAINERS treats a dropped
  // connection to webapp/nginx-webapp as success, not a failure. ──
  const containerKey = (host: string, name: string) => `${host}/${name}`;
  let containerBusy = $state<Record<string, boolean>>({});
  function setContainerBusy(key: string, on: boolean) {
    const n = { ...containerBusy };
    if (on) n[key] = true; else delete n[key];
    containerBusy = n;
  }
  const isExpectedDrop = (name: string, err: ApiError) =>
    SELF_CONTAINERS.has(name) && (err.status === 502 || err.status === 504 || err.status === undefined);

  async function restartContainer(host: string, name: string) {
    const danger = CRITICAL_CONTAINERS[name];
    const ok = await confirm({
      title: `Restart ${name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: danger ? name : null,
      body: `Runs \`docker restart ${name}\` on ${host} via its agent (~10–15s for a heavy container).`,
      danger,
    });
    if (!ok) return;
    const key = containerKey(host, name);
    setContainerBusy(key, true);
    try {
      await post(`/api/agents/${host}/restart-container`, { container: name }, 60_000);
      toast(`${name} restarted on ${host}.`, 'ok');
      qc.invalidateQueries({ queryKey: ['containers'] });
    } catch (e) {
      const err = e as ApiError;
      if (isExpectedDrop(name, err)) {
        toast(`Connection dropped — expected when restarting ${name}: it serves this page. It is almost certainly back; reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Restart of ${name} failed: ${err.message}`, 'crit', { sticky: true });
      }
    } finally {
      setContainerBusy(key, false);
    }
  }

  async function updateContainer(host: string, name: string) {
    const danger = CRITICAL_CONTAINERS[name];
    const ok = await confirm({
      title: `Update ${name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate',
      requireTyped: danger ? name : null,
      body: `Pulls the newest image for ${name} on ${host} and recreates just that compose service. A registry pull on the Pi can run for minutes.`,
      danger,
    });
    if (!ok) return;
    const key = containerKey(host, name);
    setContainerBusy(key, true);
    try {
      // 230s sits above the backend's 220s agent cap, below nginx's 240s.
      await post(`/api/agents/${host}/update-container`, { container: name }, 230_000);
      toast(`${name} updated on ${host}.`, 'ok');
      qc.invalidateQueries({ queryKey: ['containers'] });
      qc.invalidateQueries({ queryKey: ['updates'] });
    } catch (e) {
      const err = e as ApiError;
      if (isExpectedDrop(name, err)) {
        toast(`Connection dropped — expected when updating ${name}: it serves this page. Reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Update of ${name} failed: ${err.message}`, 'crit', { sticky: true });
      }
    } finally {
      setContainerBusy(key, false);
    }
  }

  // 30s refresh while this page is mounted, matching v2's self-clearing timer.
  $effect(() => {
    const id = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      qc.invalidateQueries({ queryKey: ['vitals'] });
    }, 30_000);
    return () => clearInterval(id);
  });

  // android: status-only, no agent — a quick unauthenticated ping, once on mount.
  let androidUp = $state<boolean | null>(null);
  $effect(() => {
    let alive = true;
    get('/api/llama/status', 5000)
      .then(() => { if (alive) androidUp = true; })
      .catch(() => { if (alive) androidUp = false; });
    return () => { alive = false; };
  });

  let agentById = $derived.by(() => {
    const m: Record<string, AgentRow> = {};
    for (const h of agents.data?.hosts ?? []) m[h.id] = h;
    return m;
  });

  let cards = $derived.by((): HostVM[] => HOST_IDS.map((host) => {
    const a = agentById[host];
    const reachable = !!a?.reachable;
    const rollup = vitalsRollup.data?.hosts[host];
    const series = vitalsSeries[host];
    const live = archLive.data?.hosts?.[host];
    const pkg = updatesQ.data?.packages.find((p) => p.host === host);
    const images = updatesQ.data?.images.filter((u) => u.host === host) ?? [];
    const containers = containersQ.data?.hosts.find((h) => h.host === host)?.containers ?? [];
    const timers = timersQ.data?.hosts.find((h) => h.host === host)?.timers ?? [];
    const wakeable = (agents.data?.hosts ?? []).some((h) => h.reachable && (h.wake_targets ?? []).includes(host));
    return {
      host,
      role: HOST_ROLES[host] ?? '',
      agent: a,
      reachable,
      hasControls: Array.isArray(a?.allowed_units),
      isBusy: hostActions[host].busy || localBusy.has(host),
      watchInfo: watch[host],
      aptState: aptQueries[host].data,
      termUrl: termUrlFor(host),
      wakeable,
      allowedUnits: a?.allowed_units ?? [],
      samples: series.data?.samples ?? [],
      latest: rollup?.latest ?? null,
      vitalsError: rollup?.error,
      vitalsLoading: series.isLoading,
      diskUsedPct: live?.disk_used_pct ?? null,
      pool: live?.pool ?? null,
      pkgUpdates: pkg,
      imageUpdates: images,
      containers,
      containerBusy,
      timers,
      onReboot: () => hostActions[host].reboot(),
      onAptUpgrade: () => doAptUpgrade(host),
      onRestartUnit: (unit: string) => restartUnit(host, unit),
      onWake: () => wakeHost(host),
      onForceSync: () => forceSync(host),
      onRestartContainer: (name: string) => restartContainer(host, name),
      onUpdateContainer: (name: string) => updateContainer(host, name),
    };
  }));
</script>

<div class="cockpit-page">
  <FleetBar />

  <div class="board-bar">
    <span class="t-dim faint">Vitals range</span>
    <div class="seg" role="group" aria-label="Vitals range">
      {#each VITALS_RANGES as r (r)}
        <button type="button" class="seg-btn" class:active={range === r} onclick={() => (range = r)}>{r}</button>
      {/each}
    </div>
    <span class="spacer"></span>
  </div>

  <div class="cockpit-grid">
    {#each cards as c (c.host)}
      <HostCard vm={c} {range} focused={focus === c.host} collapsed={!!focus && focus !== c.host}
        onToggleFocus={() => (focus = focus === c.host ? null : c.host)} />
    {/each}

    <section class="ck-card glass card">
      <header class="ck-head">
        <span class="mono ck-host">android</span>
        <span class="t-dim">{HOST_ROLES.android}</span>
        <span class="spacer"></span>
        <span class="pill" data-s={androidUp ? 'ok' : 'warn'}>{androidUp == null ? '…' : androidUp ? 'up' : 'offline'}</span>
      </header>
      <div class="t-dim">
        Status display only — no agent on this host, and it is often offline by
        design (it is a phone).
      </div>
    </section>
  </div>
</div>
