<script lang="ts">
  // The container control room: every container across the fleet as one live console —
  // current docker ps (report data joined with Dozzle's live SSE feed), three views
  // (by host / by compose project / problems first), filter chips with counts, bulk
  // restart/update with the same blast-radius gates the Cockpit uses, a detail drawer
  // per container, and a fleet summary strip up top.
  //
  // opti intentionally never appears here: it runs no docker (control plane only).
  import { onMount } from 'svelte';
  import { useQueryClient } from '@tanstack/svelte-query';
  import { RefreshCw, ScrollText, RotateCw, CircleArrowUp } from '@lucide/svelte';
  import { useContainers } from '$lib/api/queries';
  import { useUpdates, type UpdateImage } from '$lib/api/fleet';
  import { createDozzle } from '$lib/dozzle.svelte';
  import { post, type ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { durSince } from '$lib/format';
  import { CRITICAL_CONTAINERS, SELF_CONTAINERS } from '$lib/impact';
  import LogsModal from './_parts/LogsModal.svelte';
  import DetailDrawer from './_parts/DetailDrawer.svelte';

  type RawPort = { container_port?: string; host_port?: string; host_ip?: string; proto?: string };

  interface Row {
    key: string;
    host: string;
    name: string;
    image: string | null;
    project: string | null;
    ports: RawPort[];       // raw — the drawer needs host_port/proto to build links
    portsFmt: string[];     // formatted "host→container/proto" for the table cell
    status: string | null;
    since: string | null;
    up: boolean;
    update: boolean;
    id?: string;
    health?: string;
    liveState?: string;
  }

  type ViewMode = 'host' | 'project' | 'problems';
  type StateFacet = 'up' | 'down';

  const VIEW_KEY = 'containers-view';
  const FILTERS_KEY = 'containers-filters';
  const RECENT_RESTART_MIN = 15;

  const containers = useContainers();
  const updates = useUpdates();
  const dozzle = createDozzle();
  const qc = useQueryClient();

  // ── view + filters, persisted ──────────────────────────────────────────────
  function loadView(): ViewMode {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      return v === 'host' || v === 'project' || v === 'problems' ? v : 'host';
    } catch { return 'host'; }
  }
  interface FiltersState { hosts: string[]; states: StateFacet[]; updateOnly: boolean; search: string }
  function loadFilters(): FiltersState {
    const empty: FiltersState = { hosts: [], states: [], updateOnly: false, search: '' };
    try {
      const raw = localStorage.getItem(FILTERS_KEY);
      if (!raw) return empty;
      const p = JSON.parse(raw);
      return {
        hosts: Array.isArray(p.hosts) ? p.hosts.filter((h: unknown) => typeof h === 'string') : [],
        states: Array.isArray(p.states) ? p.states.filter((s: unknown) => s === 'up' || s === 'down') : [],
        updateOnly: !!p.updateOnly,
        search: typeof p.search === 'string' ? p.search : '',
      };
    } catch { return empty; }
  }
  const initFilters = loadFilters();

  let view = $state<ViewMode>(loadView());
  let search = $state(initFilters.search);
  let hostFilter = $state<Set<string>>(new Set(initFilters.hosts));
  let stateFilter = $state<Set<StateFacet>>(new Set(initFilters.states));
  let updateOnly = $state(initFilters.updateOnly);

  function setView(v: ViewMode) {
    view = v;
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* private mode */ }
  }
  $effect(() => {
    const payload: FiltersState = { hosts: [...hostFilter], states: [...stateFilter], updateOnly, search };
    try { localStorage.setItem(FILTERS_KEY, JSON.stringify(payload)); } catch { /* private mode */ }
  });
  function toggleHost(h: string) {
    const next = new Set(hostFilter);
    next.has(h) ? next.delete(h) : next.add(h);
    hostFilter = next;
  }
  function toggleState(s: StateFacet) {
    const next = new Set(stateFilter);
    next.has(s) ? next.delete(s) : next.add(s);
    stateFilter = next;
  }
  function clearFilters() {
    hostFilter = new Set();
    stateFilter = new Set();
    updateOnly = false;
    search = '';
  }

  // ── row model ───────────────────────────────────────────────────────────────
  let allRows = $derived.by<Row[]>(() => {
    const out: Row[] = [];
    for (const h of containers.data?.hosts ?? []) {
      for (const c of h.containers) {
        const dz = dozzle.byName[c.name];
        const ports = c.ports ?? [];
        out.push({
          key: `${h.host}/${c.name}`,
          host: h.host,
          name: c.name,
          image: c.image ?? null,
          project: c.compose_project ?? null,
          ports,
          portsFmt: [...new Set(ports.map((p) =>
            p.host_port === p.container_port
              ? `${p.host_port}/${p.proto ?? 'tcp'}`
              : `${p.host_port ?? '?'}→${p.container_port ?? '?'}/${p.proto ?? 'tcp'}`))],
          status: c.status ?? null,
          since: c.status_since ?? null,
          up: dz ? dz.state === 'running' : c.up,
          update: c.update_available,
          id: dz?.id,
          health: dz?.health,
          liveState: dz?.state,
        });
      }
    }
    return out;
  });

  const matchesSearch = (r: Row, f: string) =>
    !f || r.name.toLowerCase().includes(f) || (r.image ?? '').toLowerCase().includes(f) || (r.project ?? '').toLowerCase().includes(f);

  let searchedRows = $derived.by(() => {
    const f = search.trim().toLowerCase();
    return allRows.filter((r) => matchesSearch(r, f));
  });

  let hostsAll = $derived([...new Set(allRows.map((r) => r.host))].sort());
  let hostCounts = $derived.by(() => {
    const m = new Map<string, number>();
    for (const r of searchedRows) m.set(r.host, (m.get(r.host) ?? 0) + 1);
    return m;
  });
  let runningCount = $derived(searchedRows.filter((r) => r.up).length);
  let downCount = $derived(searchedRows.filter((r) => !r.up).length);
  let updateCount = $derived(searchedRows.filter((r) => r.update).length);

  let visibleRows = $derived.by<Row[]>(() => {
    let list = searchedRows;
    if (hostFilter.size) list = list.filter((r) => hostFilter.has(r.host));
    if (stateFilter.size) list = list.filter((r) => stateFilter.has(r.up ? 'up' : 'down'));
    if (updateOnly) list = list.filter((r) => r.update);
    return list;
  });

  // Fleet-wide summary strip counts — deliberately from allRows, not the filtered view.
  let totalAll = $derived(allRows.length);
  let upAll = $derived(allRows.filter((r) => r.up).length);
  let updatesAll = $derived(allRows.filter((r) => r.update).length);
  let hostSummary = $derived.by(() => {
    const m = new Map<string, { up: number; total: number }>();
    for (const r of allRows) {
      const e = m.get(r.host) ?? { up: 0, total: 0 };
      e.total++;
      if (r.up) e.up++;
      m.set(r.host, e);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  });

  // ── grouping per view ────────────────────────────────────────────────────────
  interface Group { label: string; rows: Row[] }
  function minutesSince(iso: string | null): number | null {
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 60000));
  }
  function isProblem(r: Row): boolean {
    if (!r.up || r.update) return true;
    const m = minutesSince(r.since);
    return m !== null && m < RECENT_RESTART_MIN;
  }
  const sortRows = (list: Row[]) =>
    [...list].sort((a, b) => Number(a.up) - Number(b.up) || a.host.localeCompare(b.host) || a.name.localeCompare(b.name));

  let groups = $derived.by<Group[]>(() => {
    if (view === 'host') {
      const by = new Map<string, Row[]>();
      for (const r of visibleRows) (by.get(r.host) ?? by.set(r.host, []).get(r.host)!).push(r);
      return [...by.keys()].sort().map((h) => ({ label: h, rows: sortRows(by.get(h)!) }));
    }
    if (view === 'project') {
      const by = new Map<string, Row[]>();
      for (const r of visibleRows) {
        const p = r.project ?? '(no project)';
        (by.get(p) ?? by.set(p, []).get(p)!).push(r);
      }
      const keys = [...by.keys()].sort((a, b) => Number(a === '(no project)') - Number(b === '(no project)') || a.localeCompare(b));
      return keys.map((p) => ({ label: p, rows: sortRows(by.get(p)!) }));
    }
    const problems = sortRows(visibleRows.filter(isProblem));
    const healthy = sortRows(visibleRows.filter((r) => !isProblem(r)));
    const out: Group[] = [];
    if (problems.length) out.push({ label: `Needs attention (${problems.length})`, rows: problems });
    if (healthy.length) out.push({ label: `Healthy (${healthy.length})`, rows: healthy });
    return out;
  });

  // ── selection + bulk actions ─────────────────────────────────────────────────
  let selected = $state<Set<string>>(new Set());
  let bulkBusy = $state(false);
  let busy = $state<Record<string, boolean>>({});
  const setBusyFor = (key: string, on: boolean) => {
    if (on) busy[key] = true;
    else delete busy[key];
  };

  // Looked up from allRows (not the filtered view) so a mid-flight filter change
  // never orphans an in-progress selection.
  let selectedRows = $derived(allRows.filter((r) => selected.has(r.key)));
  let allVisibleSelected = $derived(visibleRows.length > 0 && visibleRows.every((r) => selected.has(r.key)));

  function toggleSelect(key: string) {
    const next = new Set(selected);
    next.has(key) ? next.delete(key) : next.add(key);
    selected = next;
  }
  function toggleSelectAll() {
    const next = new Set(selected);
    if (allVisibleSelected) for (const r of visibleRows) next.delete(r.key);
    else for (const r of visibleRows) next.add(r.key);
    selected = next;
  }

  const isExpectedDrop = (row: Row, err: ApiError) =>
    SELF_CONTAINERS.has(row.name) && (err.status === 502 || err.status === 504 || err.status === undefined);

  async function doRestart(row: Row): Promise<boolean> {
    setBusyFor(row.key, true);
    try {
      await post(`/api/agents/${row.host}/restart-container`, { container: row.name }, 60_000);
      toast(`${row.name} restarted on ${row.host}`, 'ok');
      return true;
    } catch (e) {
      // Restarting the container serving this page kills the very response we're
      // waiting on — a dropped fetch or bare 502/504 IS the restart working.
      const err = e as ApiError;
      if (isExpectedDrop(row, err)) {
        toast(`Connection dropped — expected when restarting ${row.name}: it serves this page. It is almost certainly back; reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Restart of ${row.name} failed: ${err.message}`, 'crit', { sticky: true });
      }
      return false;
    } finally {
      setBusyFor(row.key, false);
    }
  }

  async function doUpdate(row: Row, timeoutMs: number): Promise<boolean> {
    setBusyFor(row.key, true);
    try {
      await post(`/api/agents/${row.host}/update-container`, { container: row.name }, timeoutMs);
      toast(`${row.name} updated on ${row.host}`, 'ok');
      return true;
    } catch (e) {
      const err = e as ApiError;
      if (isExpectedDrop(row, err)) {
        toast(`Connection dropped — expected when updating ${row.name}: it serves this page. Reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Update of ${row.name} failed: ${err.message}`, 'crit', { sticky: true });
      }
      return false;
    } finally {
      setBusyFor(row.key, false);
    }
  }

  async function restart(row: Row) {
    const danger = CRITICAL_CONTAINERS[row.name];
    const ok = await confirm({
      title: `Restart ${row.name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: danger ? row.name : null,
      body: `Runs \`docker restart ${row.name}\` on ${row.host} via its agent (~10–15s for a heavy container).`,
      danger,
    });
    if (!ok) return;
    await doRestart(row);
    qc.invalidateQueries({ queryKey: ['containers'] });
  }

  async function update(row: Row) {
    const danger = CRITICAL_CONTAINERS[row.name];
    const ok = await confirm({
      title: `Update ${row.name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate',
      requireTyped: danger ? row.name : null,
      body: `Pulls the newest image for ${row.name} on ${row.host} and recreates just that compose service. A registry pull on the Pi can run for minutes.`,
      danger,
    });
    if (!ok) return;
    // 230s sits above the backend's 220s agent cap, below nginx's 240s.
    await doUpdate(row, 230_000);
    qc.invalidateQueries({ queryKey: ['containers'] });
    qc.invalidateQueries({ queryKey: ['updates'] });
  }

  const summarizeTargets = (rows: Row[]) => {
    const by = new Map<string, string[]>();
    for (const r of rows) (by.get(r.host) ?? by.set(r.host, []).get(r.host)!).push(r.name);
    return [...by.entries()].map(([h, names]) => `${h}: ${names.join(', ')}`).join('\n');
  };

  async function bulkRestart() {
    const targets = selectedRows;
    if (!targets.length) return;
    const criticalNames = [...new Set(targets.filter((r) => CRITICAL_CONTAINERS[r.name]).map((r) => r.name))];
    const ok = await confirm({
      title: `Restart ${targets.length} container${targets.length === 1 ? '' : 's'}?`,
      tone: criticalNames.length ? 'crit' : 'warn',
      confirmLabel: 'Restart selected',
      requireTyped: criticalNames.length ? criticalNames.join(', ') : null,
      body: `Runs \`docker restart\` on each, one host-agent call at a time:\n${summarizeTargets(targets)}`,
      danger: criticalNames.length ? criticalNames.map((n) => `${n}: ${CRITICAL_CONTAINERS[n]}`).join('\n') : undefined,
      note: 'Applied sequentially — a failure on one does not stop the rest; each gets its own toast.',
    });
    if (!ok) return;
    bulkBusy = true;
    for (const row of targets) await doRestart(row);
    bulkBusy = false;
    qc.invalidateQueries({ queryKey: ['containers'] });
    selected = new Set();
  }

  async function bulkUpdate() {
    const targets = selectedRows;
    if (!targets.length) return;
    const criticalNames = [...new Set(targets.filter((r) => CRITICAL_CONTAINERS[r.name]).map((r) => r.name))];
    const ok = await confirm({
      title: `Update ${targets.length} container${targets.length === 1 ? '' : 's'}?`,
      tone: criticalNames.length ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate selected',
      requireTyped: criticalNames.length ? criticalNames.join(', ') : null,
      body: `Pulls the newest image and recreates each compose service, one host-agent call at a time:\n${summarizeTargets(targets)}`,
      danger: criticalNames.length ? criticalNames.map((n) => `${n}: ${CRITICAL_CONTAINERS[n]}`).join('\n') : undefined,
      note: 'Applied sequentially; registry pulls on the Pi can run for minutes each. Each item gets its own toast.',
    });
    if (!ok) return;
    bulkBusy = true;
    for (const row of targets) await doUpdate(row, 180_000);
    bulkBusy = false;
    qc.invalidateQueries({ queryKey: ['containers'] });
    qc.invalidateQueries({ queryKey: ['updates'] });
    selected = new Set();
  }

  // ── detail drawer ─────────────────────────────────────────────────────────
  let drawerRow = $state<Row | null>(null);
  const openDrawer = (row: Row) => (drawerRow = row);
  const closeDrawer = () => (drawerRow = null);
  let drawerUpdateInfo = $derived.by<UpdateImage | null>(() => {
    if (!drawerRow) return null;
    return updates.data?.images.find((i) => i.host === drawerRow!.host && i.container === drawerRow!.name) ?? null;
  });

  // ── logs modal ────────────────────────────────────────────────────────────
  let logs = $state<Row | null>(null);
  function openLogs(row: Row) {
    if (row.id) logs = row;
    else window.location.assign('/logs');
  }

  // ── keyboard: "/" focuses search, Escape closes the drawer ──────────────────
  let searchEl: HTMLInputElement | undefined = $state();
  onMount(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === 'INPUT' || tag === 'TEXTAREA';
      if (e.key === '/' && !typing) {
        e.preventDefault();
        searchEl?.focus();
      } else if (e.key === 'Escape' && drawerRow) {
        drawerRow = null;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

<div class="containers-page">
  <div class="board-bar board-head">
    <div class="board-head-text">
      <h1 class="board-title">Containers</h1>
      <div class="board-sub t-dim">
        {upAll}/{totalAll} up{updatesAll ? ` · ${updatesAll} update${updatesAll > 1 ? 's' : ''} available` : ''}
        {' · '}
        <span class:t-ok={dozzle.live}>{dozzle.live ? 'live via dozzle' : 'report data (dozzle stream offline)'}</span>
      </div>
    </div>
    <span class="spacer"></span>
    <div class="seg" role="group" aria-label="View">
      <button class="seg-btn" class:active={view === 'host'} onclick={() => setView('host')}>By host</button>
      <button class="seg-btn" class:active={view === 'project'} onclick={() => setView('project')}>By project</button>
      <button class="seg-btn" class:active={view === 'problems'} onclick={() => setView('problems')}>Problems first</button>
    </div>
    <input class="input ct-filter" placeholder="Filter name / image / project… (/)" aria-label="Filter containers"
      bind:value={search} bind:this={searchEl} />
    <button class="tbtn" title="Refetch the container list now" onclick={() => qc.invalidateQueries({ queryKey: ['containers'] })}>
      <RefreshCw aria-hidden="true" /> Refresh
    </button>
  </div>

  <div class="chips ct-hostpills">
    {#each hostSummary as [h, s] (h)}
      <span class="chip" data-s={s.up < s.total ? 'crit' : 'ok'}>{h} {s.up}/{s.total}</span>
    {/each}
  </div>

  {#if containers.isError}
    <div class="card t-crit">Cannot reach /api/containers{containers.error ? ` — ${(containers.error as Error).message}` : ''}. Is the backend running?</div>
  {/if}

  <div class="chips ct-chipbar">
    <span class="faint">Host</span>
    {#each hostsAll as h (h)}
      <button class="chip act" class:on={hostFilter.has(h)} onclick={() => toggleHost(h)}>
        {h} <span class="num">{hostCounts.get(h) ?? 0}</span>
      </button>
    {/each}
    <span class="faint">State</span>
    <button class="chip act" class:on={stateFilter.has('up')} onclick={() => toggleState('up')}>
      running <span class="num">{runningCount}</span>
    </button>
    <button class="chip act" class:on={stateFilter.has('down')} onclick={() => toggleState('down')}>
      down <span class="num">{downCount}</span>
    </button>
    <button class="chip act" class:on={updateOnly} onclick={() => (updateOnly = !updateOnly)}>
      update available <span class="num">{updateCount}</span>
    </button>
    {#if hostFilter.size || stateFilter.size || updateOnly || search}
      <button class="tbtn sm" onclick={clearFilters}>Clear filters</button>
    {/if}
  </div>

  <section class="card ct-table-card">
    {#if containers.isLoading}<div class="spin"></div>{/if}
    <div class="tablewrap">
      <table class="detail-table ct-table">
        <thead>
          <tr>
            <th>
              <input type="checkbox" checked={allVisibleSelected} disabled={visibleRows.length === 0}
                onclick={(e) => { e.stopPropagation(); toggleSelectAll(); }} aria-label="Select all visible" />
            </th>
            <th></th><th>Name</th><th>Host</th><th>Image</th><th>Project</th><th>Ports</th><th>Up</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each groups as g (g.label)}
            <tr class="ct-group-row"><td colspan="9">{g.label}</td></tr>
            {#each g.rows as r (r.key)}
              {@const isBusy = !!busy[r.key]}
              <tr data-down={!r.up || undefined} class="ct-row" onclick={() => openDrawer(r)}>
                <td onclick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(r.key)} onchange={() => toggleSelect(r.key)} aria-label="Select {r.name}" />
                </td>
                <td>
                  <span class="cdot" data-s={r.up ? (r.health === 'unhealthy' ? 'warn' : 'ok') : 'crit'}
                    title={r.liveState ?? r.status ?? 'unknown'}></span>
                </td>
                <td class="mono ct-name">
                  {r.name}
                  {#if r.health === 'unhealthy'}<span class="badge badge-alert">UNHEALTHY</span>{/if}
                  {#if r.update}<span class="badge badge-stale">update</span>{/if}
                </td>
                <td>{r.host}</td>
                <td class="mono t-dim ct-image" title={r.image ?? ''}>{r.image ?? '—'}</td>
                <td class="t-dim">{r.project ?? '—'}</td>
                <td class="mono t-dim ct-ports" title={r.portsFmt.join(', ')}>
                  {r.portsFmt.length ? r.portsFmt.slice(0, 2).join(', ') + (r.portsFmt.length > 2 ? '…' : '') : '—'}
                </td>
                <td class="t-dim">{r.since ? durSince(r.since) : (r.status ?? '—')}</td>
                <td class="ct-actions" onclick={(e) => e.stopPropagation()}>
                  <button class="tbtn sm" title={r.id ? 'Live logs (Dozzle)' : 'Open the Logs page — no live id for this container yet'}
                    onclick={() => openLogs(r)}>
                    <ScrollText aria-hidden="true" /> Logs
                  </button>
                  <button class="tbtn sm" disabled={isBusy} title="Restart on {r.host}" onclick={() => restart(r)}>
                    <RotateCw aria-hidden="true" /> Restart
                  </button>
                  {#if r.update}
                    <button class="tbtn sm" disabled={isBusy} title="Pull newest image & recreate" onclick={() => update(r)}>
                      <CircleArrowUp aria-hidden="true" /> Update
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          {/each}
          {#if visibleRows.length === 0 && !containers.isLoading}
            <tr><td colspan="9" class="t-dim">Nothing matches.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </section>

  {#if selected.size > 0}
    <div class="card ct-bulkbar">
      <span>{selected.size} selected</span>
      <span class="spacer"></span>
      <button class="tbtn sm" disabled={bulkBusy} onclick={() => (selected = new Set())}>Clear</button>
      <button class="tbtn sm" disabled={bulkBusy} onclick={bulkRestart}><RotateCw aria-hidden="true" /> Restart selected</button>
      <button class="tbtn sm primary" disabled={bulkBusy} onclick={bulkUpdate}><CircleArrowUp aria-hidden="true" /> Update selected</button>
    </div>
  {/if}

  {#if logs && logs.id}
    <LogsModal id={logs.id} name={logs.name} host={logs.host} onclose={() => (logs = null)} />
  {/if}

  {#if drawerRow}
    <DetailDrawer
      row={drawerRow}
      dozzleLive={dozzle.live}
      updateInfo={drawerUpdateInfo}
      busy={!!busy[drawerRow.key]}
      onclose={closeDrawer}
      onrestart={() => restart(drawerRow!)}
      onupdate={() => update(drawerRow!)}
      onopenlogs={() => openLogs(drawerRow!)}
    />
  {/if}
</div>

<style>
  /* Page-only additions layered on the shared .chip/.seg/.tbtn vocabulary — CSS
     variables only, nothing hardcoded. */
  .ct-hostpills { margin-top: calc(-1 * var(--s2)); }
  .ct-chipbar { padding: var(--s2) 0; border-bottom: 1px solid var(--border); }
  .ct-chipbar .faint { font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; margin-right: 2px; }
  .ct-chipbar .chip.act.on { background: var(--accent-dim); color: var(--accent); border-color: var(--accent-muted); }
  .ct-chipbar .chip.act .num { margin-left: 4px; opacity: .75; }
  .ct-row { cursor: pointer; }
  .ct-group-row td { padding: var(--s2) var(--s2) var(--s1) 0; font-size: var(--fs-xs); font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3); border-bottom: 1px solid var(--border-2); background: var(--bg-inset); }
  .ct-bulkbar { position: sticky; bottom: var(--s3); display: flex; align-items: center; gap: var(--s3); padding: var(--s3) var(--s4); z-index: 10; }
</style>
