<script lang="ts">
  // Update queue — every pending container image and apt package across the fleet as
  // one work queue: tick the ones you want, review one confirm() that summarises the
  // whole batch, then watch them apply one at a time with per-item progress. Per-row
  // quick actions still exist for a single item. Load-bearing behaviours carried over
  // verbatim from the read-only version (and from Containers/Cockpit, which share the
  // same gates):
  //   - CRITICAL_CONTAINERS gets a typed confirm; SELF_CONTAINERS (webapp,
  //     nginx-webapp) serve this very page, so a dropped connection or bare 502/504
  //     updating one of them IS success, not a failure — and they run last in a batch
  //     so losing the connection doesn't strand the rest of the queue.
  //   - apt: POST apt-upgrade only kicks the job off; the real status comes from
  //     polling apt-status every 5s, same shape/cadence as Cockpit's HostCard.
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { CircleArrowUp, ExternalLink, RefreshCw, Square } from '@lucide/svelte';
  import { get, post, type ApiError } from '$lib/api/client';
  import { useUpdates, type UpdateImage, type UpdatePackages } from '$lib/api/fleet';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { createHostActions } from '$lib/host-actions.svelte';
  import { relTime } from '$lib/format';
  import { CRITICAL_CONTAINERS, SELF_CONTAINERS, agentTooOld } from '$lib/impact';
  import { HOSTS as NAV_HOSTS } from '$lib/nav';

  // Shape of /api/agents/<host>/apt-status — same contract Cockpit's HostCard polls.
  // Redefined locally rather than imported from that component so this page doesn't
  // depend on a file that may be mid-rewrite elsewhere.
  interface AptStatus {
    running?: boolean;
    result?: string;
    exit_status?: string;
    reboot_required?: boolean;
    finished_at?: string;
    log_tail?: string[];
    already_running?: boolean;
    ok?: boolean;
  }

  interface HostGroup { host: string; images: UpdateImage[]; apt?: UpdatePackages }

  interface QueueItem {
    key: string;
    kind: 'image' | 'apt';
    host: string;
    container?: string;
    label: string;
    status: 'queued' | 'running' | 'done' | 'failed';
    error?: string;
    logTail?: string[];
  }

  interface HistoryEntry {
    at: string;
    host: string;
    item: string;
    result: 'ok' | 'warn' | 'failed';
    detail?: string;
  }

  const HISTORY_KEY = 'updates-history-v1';
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const imgKey = (r: UpdateImage) => `${r.host}::${r.container}`;

  function loadHistory(): HistoryEntry[] {
    try {
      const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]');
      return Array.isArray(raw) ? raw : [];
    } catch { return []; }
  }

  const qc = useQueryClient();
  const q = useUpdates();

  // Reboot/typed-gate handling for "reboot required" rows — same module Cockpit uses,
  // created up front (during component init, as it needs the query-client context)
  // for every host that carries an agent.
  const HOST_IDS = NAV_HOSTS.filter((h) => h.name !== 'android').map((h) => h.name);
  const hostActions = Object.fromEntries(HOST_IDS.map((h) => [h, createHostActions(() => h)])) as
    Record<string, ReturnType<typeof createHostActions>>;

  let selectedImages = $state<Set<string>>(new Set());
  let selectedApt = $state<Set<string>>(new Set());
  let progress = $state<QueueItem[]>([]);
  let running = $state(false);
  let aborted = $state(false);
  let historyLog = $state<HistoryEntry[]>(loadHistory());

  function pushHistory(e: HistoryEntry) {
    const next = [e, ...historyLog].slice(0, 20);
    historyLog = next;
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* private mode */ }
  }

  let hostGroups = $derived.by((): HostGroup[] => {
    const map = new Map<string, HostGroup>();
    for (const img of q.data?.images ?? []) {
      if (!map.has(img.host)) map.set(img.host, { host: img.host, images: [] });
      map.get(img.host)!.images.push(img);
    }
    for (const pkg of q.data?.packages ?? []) {
      if (!map.has(pkg.host)) map.set(pkg.host, { host: pkg.host, images: [] });
      map.get(pkg.host)!.apt = pkg;
    }
    return [...map.values()].sort((a, b) => a.host.localeCompare(b.host));
  });

  let counts = $derived(q.data?.counts);
  let selectedCount = $derived(selectedImages.size + selectedApt.size);
  let nothingPending = $derived(!!q.data && (counts?.images ?? 0) === 0 && (counts?.packages ?? 0) === 0);

  function toggleImage(r: UpdateImage) {
    if (running) return;
    const n = new Set(selectedImages);
    const k = imgKey(r);
    if (n.has(k)) n.delete(k); else n.add(k);
    selectedImages = n;
  }
  function toggleApt(host: string) {
    if (running) return;
    const n = new Set(selectedApt);
    if (n.has(host)) n.delete(host); else n.add(host);
    selectedApt = n;
  }
  function hostAllSelected(g: HostGroup): boolean {
    if (g.images.length === 0 && !g.apt) return false;
    const imgsOk = g.images.length === 0 || g.images.every((r) => selectedImages.has(imgKey(r)));
    const aptOk = !g.apt || selectedApt.has(g.host);
    return imgsOk && aptOk;
  }
  function toggleHostAll(g: HostGroup) {
    if (running) return;
    const turnOn = !hostAllSelected(g);
    const ni = new Set(selectedImages);
    const na = new Set(selectedApt);
    for (const r of g.images) { const k = imgKey(r); if (turnOn) ni.add(k); else ni.delete(k); }
    if (g.apt) { if (turnOn) na.add(g.host); else na.delete(g.host); }
    selectedImages = ni;
    selectedApt = na;
  }
  function selectAllPending() {
    if (running) return;
    const ni = new Set<string>();
    const na = new Set<string>();
    for (const g of hostGroups) {
      for (const r of g.images) ni.add(imgKey(r));
      if (g.apt) na.add(g.host);
    }
    selectedImages = ni;
    selectedApt = na;
  }
  function clearSelection() {
    if (running) return;
    selectedImages = new Set();
    selectedApt = new Set();
  }

  function shortSha(d: string | null | undefined): string {
    if (!d) return '—';
    const hex = d.replace(/^sha256:/, '');
    return hex.length > 12 ? hex.slice(0, 12) : hex;
  }
  function digestTitle(row: UpdateImage): string {
    return `current   ${shortSha(row.current_digest)}\navailable ${shortSha(row.available_digest)}`;
  }
  function rebootPkgsTitle(p: UpdatePackages): string {
    if (!p.reboot_pkgs) return '';
    return Array.isArray(p.reboot_pkgs) ? p.reboot_pkgs.join(', ') : p.reboot_pkgs;
  }

  // ── per-row quick apply — the confirm gate + mutation the read-only page already
  // had, kept as-is (typed gate on the container's own name, 230s timeout: above the
  // backend's 220s agent cap for a single pull, below nginx's 240s). ──
  const updateOne = createMutation(() => ({
    mutationFn: ({ host, container }: { host: string; container: string }) =>
      post(`/api/agents/${host}/update-container`, { container }, 230_000),
    onSuccess: (_d: unknown, v: { host: string; container: string }) => {
      toast(`${v.container} updated on ${v.host}`, 'ok');
      qc.invalidateQueries({ queryKey: ['updates'] });
      qc.invalidateQueries({ queryKey: ['containers'] });
      pushHistory({ at: new Date().toISOString(), host: v.host, item: v.container, result: 'ok' });
    },
    onError: (e: Error, v: { host: string; container: string }) => {
      if (SELF_CONTAINERS.has(v.container)) {
        toast(`Connection dropped — expected when updating ${v.container}: it serves this page. It is almost certainly back; reload in a few seconds to confirm.`,
          'warn', { sticky: true });
        pushHistory({ at: new Date().toISOString(), host: v.host, item: v.container, result: 'warn', detail: 'connection dropped (expected)' });
      } else {
        toast(`Update of ${v.container} failed: ${e.message}`, 'crit', { sticky: true });
        pushHistory({ at: new Date().toISOString(), host: v.host, item: v.container, result: 'failed', detail: e.message });
      }
    },
  }));

  async function applyOne(row: UpdateImage) {
    const danger = CRITICAL_CONTAINERS[row.container];
    const ok = await confirm({
      title: `Update ${row.container}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate',
      requireTyped: danger ? row.container : null,
      body: `Pulls the newest image for ${row.container} on ${row.host} and recreates just that compose service.`,
      danger,
      note: 'A registry pull on the Pi can run for minutes; the request waits up to ~4 minutes.',
    });
    if (!ok) return;
    updateOne.mutate({ host: row.host, container: row.container });
  }

  // ── batch apply: one confirm for the whole set, then a flat sequential queue.
  // SELF_CONTAINERS images are pushed to the end of the queue regardless of where
  // they sort by host, so a dropped connection updating webapp/nginx-webapp never
  // strands other hosts' items behind it. ──
  function buildQueue(): QueueItem[] {
    const head: QueueItem[] = [];
    const tail: QueueItem[] = [];
    for (const g of hostGroups) {
      for (const r of g.images) {
        if (!selectedImages.has(imgKey(r))) continue;
        const item: QueueItem = {
          key: `img:${imgKey(r)}`, kind: 'image', host: r.host, container: r.container,
          label: `${r.container} (${r.host})`, status: 'queued',
        };
        (SELF_CONTAINERS.has(r.container) ? tail : head).push(item);
      }
      if (g.apt && selectedApt.has(g.host)) {
        head.push({ key: `apt:${g.host}`, kind: 'apt', host: g.host, label: `apt upgrade (${g.host})`, status: 'queued' });
      }
    }
    return [...head, ...tail];
  }

  async function runImageItem(item: QueueItem) {
    const container = item.container!;
    try {
      // 180s per the batch contract — a single pull's timeout inside a longer queue.
      await post(`/api/agents/${item.host}/update-container`, { container }, 180_000);
      item.status = 'done';
      qc.invalidateQueries({ queryKey: ['containers'] });
      pushHistory({ at: new Date().toISOString(), host: item.host, item: container, result: 'ok' });
    } catch (e) {
      const err = e as ApiError;
      if (SELF_CONTAINERS.has(container)) {
        item.status = 'done';
        item.error = 'connection dropped (expected — reload in a few seconds)';
        toast(`Connection dropped — expected when updating ${container}: it serves this page. It is almost certainly back; reload in a few seconds to confirm.`,
          'warn', { sticky: true });
        pushHistory({ at: new Date().toISOString(), host: item.host, item: container, result: 'warn', detail: 'connection dropped (expected)' });
      } else {
        item.status = 'failed';
        item.error = err.message ?? String(e);
        pushHistory({ at: new Date().toISOString(), host: item.host, item: container, result: 'failed', detail: item.error });
      }
    }
  }

  async function runAptItem(item: QueueItem) {
    try {
      const d = await post<{ ok?: boolean; already_running?: boolean }>(`/api/agents/${item.host}/apt-upgrade`, undefined, 15_000);
      if (!d?.ok) {
        item.status = 'failed';
        item.error = 'apt upgrade did not take';
        pushHistory({ at: new Date().toISOString(), host: item.host, item: 'apt upgrade', result: 'failed', detail: item.error });
        return;
      }
    } catch (e) {
      const err = e as ApiError;
      item.status = 'failed';
      item.error = err.status === 404 ? agentTooOld(item.host, 'apt upgrades') : err.message;
      pushHistory({ at: new Date().toISOString(), host: item.host, item: 'apt upgrade', result: 'failed', detail: item.error });
      return;
    }
    const t0 = Date.now();
    const giveUpMs = 20 * 60_000;
    while (true) {
      await sleep(5000);
      let d: AptStatus | null = null;
      try { d = await get<AptStatus>(`/api/agents/${item.host}/apt-status`, 10_000); } catch { /* transient — keep polling */ }
      if (d?.log_tail) item.logTail = d.log_tail;
      if (d && !d.running) {
        const good = d.result === 'success' || d.exit_status === '0';
        item.status = good ? 'done' : 'failed';
        if (!good) item.error = `ended with result "${d.result ?? d.exit_status ?? '?'}"`;
        if (d.reboot_required) toast(`Apt upgrade finished on ${item.host} — reboot required to finish.`, 'warn');
        pushHistory({ at: new Date().toISOString(), host: item.host, item: 'apt upgrade', result: good ? 'ok' : 'failed', detail: item.error });
        return;
      }
      if (Date.now() - t0 > giveUpMs) {
        item.status = 'failed';
        item.error = 'apt-status polling timed out after 20 minutes';
        pushHistory({ at: new Date().toISOString(), host: item.host, item: 'apt upgrade', result: 'failed', detail: item.error });
        return;
      }
    }
  }

  async function applySelected() {
    if (running) return;
    const queue = buildQueue();
    if (queue.length === 0) return;

    const criticalNames = [...new Set(
      queue.filter((i) => i.kind === 'image' && i.container && CRITICAL_CONTAINERS[i.container]).map((i) => i.container!),
    )];
    const hasSelf = queue.some((i) => i.kind === 'image' && i.container && SELF_CONTAINERS.has(i.container));
    const dangerLines = criticalNames.map((c) => `${c}: ${CRITICAL_CONTAINERS[c]}`).join('\n');
    let noteLine = 'Applied sequentially, one item at a time — Abort stops after the current item finishes.';
    if (hasSelf) {
      noteLine += ' webapp/nginx-webapp serve this dashboard and are applied last; a dropped connection for them is expected — reload in a few seconds.';
    }

    const ok = await confirm({
      title: `Apply ${queue.length} update${queue.length === 1 ? '' : 's'}?`,
      tone: criticalNames.length ? 'crit' : 'warn',
      confirmLabel: 'Apply selected',
      requireTyped: criticalNames.length ? 'update' : null,
      body: `This runs, one at a time:\n${queue.map((i) => `${i.host}: ${i.kind === 'apt' ? 'apt upgrade' : i.container}`).join('\n')}`,
      danger: dangerLines || undefined,
      note: noteLine,
    });
    if (!ok) return;

    progress = queue;
    running = true;
    aborted = false;
    for (const item of progress) {
      if (aborted) break;
      item.status = 'running';
      if (item.kind === 'image') await runImageItem(item);
      else await runAptItem(item);
    }
    running = false;
    selectedImages = new Set();
    selectedApt = new Set();
    qc.invalidateQueries({ queryKey: ['updates'] });
  }

  function abortQueue() {
    aborted = true;
  }
  function dismissProgress() {
    if (running) return;
    progress = [];
  }
</script>

<div class="updates-page">
  <div class="board-bar board-head">
    <div class="board-head-text">
      <h1 class="board-title">Update queue</h1>
      <div class="board-sub t-dim">
        {#if counts}
          {counts.images} image{counts.images === 1 ? '' : 's'} · {counts.packages} package{counts.packages === 1 ? '' : 's'}
          {#if counts.security}<span class="t-crit"> · {counts.security} security</span>{/if}
          {#if counts.reboots}<span class="t-warn"> · {counts.reboots} reboot pending</span>{/if}
        {:else if q.isLoading}
          loading…
        {/if}
        {' · '}collected {relTime(q.data?.collected_at)}
      </div>
    </div>
    <span class="spacer"></span>
    <button class="tbtn sm" onclick={() => qc.invalidateQueries({ queryKey: ['updates'] })} title="Refetch /api/updates now">
      <RefreshCw size={13} aria-hidden="true" /> Refresh
    </button>
    <button class="tbtn sm" disabled={running} onclick={selectAllPending}>Select all</button>
    <button class="tbtn sm" disabled={running || selectedCount === 0} onclick={clearSelection}>Clear</button>
    {#if running}
      <button class="tbtn sm danger" disabled={aborted} onclick={abortQueue}>
        <Square size={13} aria-hidden="true" /> {aborted ? 'Stopping…' : 'Abort'}
      </button>
    {:else}
      <button class="tbtn primary" disabled={selectedCount === 0} onclick={applySelected}>
        Apply selected{selectedCount ? ` (${selectedCount})` : ''}
      </button>
    {/if}
  </div>

  {#if q.isError}
    <div class="card t-crit">Cannot reach /api/updates{q.error ? ` — ${(q.error as Error).message}` : ''}. Is the backend running?</div>
  {/if}

  {#if q.isLoading}<div class="spin"></div>{/if}

  {#if nothingPending}
    <div class="card empty">Nothing pending. Last collected {relTime(q.data?.collected_at)}.</div>
  {/if}

  {#if progress.length > 0}
    <section class="glass card">
      <div class="w-head">
        <span class="w-title">Progress</span>
        <span class="w-meta">{progress.filter((i) => i.status === 'done').length}/{progress.length} done</span>
        {#if !running}<button class="tbtn sm" onclick={dismissProgress}>Dismiss</button>{/if}
      </div>
      <div class="uq-queue">
        {#each progress as item (item.key)}
          <div class="uq-queue-row">
            <span class="chip" data-s={item.status === 'done' ? 'ok' : item.status === 'failed' ? 'crit' : item.status === 'running' ? 'info' : 'mute'}>
              {item.status}
            </span>
            <span class="mono">{item.label}</span>
            {#if item.error}<span class="t-crit uq-err">{item.error}</span>{/if}
          </div>
          {#if item.kind === 'apt' && item.status === 'running' && (item.logTail?.length ?? 0) > 0}
            <pre class="log-tail">{item.logTail!.join('\n')}</pre>
          {/if}
        {/each}
      </div>
    </section>
  {/if}

  {#each hostGroups as g (g.host)}
    <section class="glass card">
      <div class="w-head">
        <span class="w-title">{g.host}</span>
        <span class="w-meta">
          {g.images.length} image{g.images.length === 1 ? '' : 's'}{#if g.apt} · {g.apt.pending} pkg{/if}
        </span>
        <span class="spacer"></span>
        <label class="uq-selectall">
          <input type="checkbox" checked={hostAllSelected(g)} disabled={running}
            onchange={() => toggleHostAll(g)} aria-label={`Select all pending on ${g.host}`} />
          select all
        </label>
      </div>

      {#if g.images.length > 0}
        <div class="tablewrap">
          <table class="detail-table updates-table">
            <thead><tr><th></th><th>Container</th><th>Image</th><th>State</th><th></th></tr></thead>
            <tbody>
              {#each g.images as row (imgKey(row))}
                <tr>
                  <td>
                    <input type="checkbox" checked={selectedImages.has(imgKey(row))} disabled={running}
                      onchange={() => toggleImage(row)} aria-label={`Select ${row.container}`} />
                  </td>
                  <td class="mono" title={digestTitle(row)}>
                    {row.container}
                    {#if row.self}<span class="badge badge-stale">serves this page</span>{/if}
                  </td>
                  <td class="mono t-dim" title={row.image ?? ''}>{row.image ?? '—'}</td>
                  <td>{#if row.running}running{:else}<span class="t-warn">stopped</span>{/if}</td>
                  <td class="uq-actions">
                    <button class="tbtn sm" disabled={running || updateOne.isPending} title="Pull newest image & recreate now" onclick={() => applyOne(row)}>
                      <CircleArrowUp size={12} aria-hidden="true" /> Apply
                    </button>
                    <a class="tbtn sm" href="/cockpit?tab=containers" title="Open {row.container} on the Containers page">
                      <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

      {#if g.apt}
        <div class="uq-apt-row">
          <input type="checkbox" checked={selectedApt.has(g.host)} disabled={running}
            onchange={() => toggleApt(g.host)} aria-label={`Select apt upgrade for ${g.host}`} />
          <span class="uq-apt-text">
            {g.apt.pending} package{g.apt.pending === 1 ? '' : 's'} pending
            {#if g.apt.security > 0}<span class="t-crit"> · {g.apt.security} security</span>{/if}
            {#if g.apt.reboot_required}<span class="t-warn" title={rebootPkgsTitle(g.apt)}> · reboot required</span>{/if}
          </span>
          <span class="spacer"></span>
          {#if g.apt.reboot_required && hostActions[g.host]}
            <button class="tbtn sm danger" onclick={() => hostActions[g.host].reboot()}>Reboot</button>
          {/if}
        </div>
      {/if}
    </section>
  {/each}

  <details class="glass card uq-history">
    <summary class="w-title">Recent ({historyLog.length})</summary>
    {#if historyLog.length === 0}
      <p class="t-dim">No applied updates yet.</p>
    {:else}
      <div class="kv-rows">
        {#each historyLog as h (h.at + h.host + h.item)}
          <div class="kv-row">
            <span title={h.at}>{relTime(h.at)}</span>
            <span class="mono">{h.host}</span>
            <span>{h.item}</span>
            <span class:t-ok={h.result === 'ok'} class:t-warn={h.result === 'warn'} class:t-crit={h.result === 'failed'} title={h.detail ?? ''}>
              {h.result}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  </details>
</div>

<style>
  /* Page-only additions layered on the shared vocabulary (.card/.chip/.tbtn/.kv-rows/
     .log-tail) — CSS variables only. */
  .uq-selectall { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-xs); color: var(--ink-3); white-space: nowrap; cursor: pointer; }
  .uq-actions { white-space: nowrap; }
  .uq-actions .tbtn { margin-right: var(--s1); }
  .uq-apt-row { display: flex; align-items: center; gap: var(--s2); padding-top: var(--s2); border-top: 1px solid var(--border); font-size: 12.5px; }
  .uq-apt-text { color: var(--ink-2); }
  .uq-queue { display: flex; flex-direction: column; gap: 4px; }
  .uq-queue-row { display: flex; align-items: center; gap: var(--s2); font-size: 12.5px; padding: 3px 0; }
  .uq-err { color: var(--crit); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .uq-history summary { cursor: pointer; list-style: none; }
  .uq-history summary::-webkit-details-marker { display: none; }
  .uq-history .kv-row { display: grid; grid-template-columns: 64px 90px 1fr auto; gap: var(--s2); align-items: baseline; }
  .uq-history .kv-row > span:last-child { margin-left: 0; text-align: right; text-transform: uppercase; font-size: var(--fs-xs); font-weight: 600; }

  @media (max-width: 480px) {
    .uq-history .kv-row { grid-template-columns: 1fr auto; grid-template-areas: "time result" "host host" "item item"; }
  }
</style>
