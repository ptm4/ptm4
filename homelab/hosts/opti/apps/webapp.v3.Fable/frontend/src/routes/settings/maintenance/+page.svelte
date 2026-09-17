<script lang="ts">
  // Settings → Maintenance. Host-level switches, starting with nightly unattended apt.
  //
  // Why this exists: on 2026-09-17 homelab-autoupdate upgraded docker-ce on opti at 02:03,
  // which restarts dockerd — and every container on opti with it (dashboard, vault, bots).
  // Holding updates per host is the lever.
  //
  // What "Disabled · guaranteed" means: the host has a hold flag that its update script
  // checks before doing anything, so it holds even if a deploy re-enables the timer. The
  // state shown is re-read from the host, never remembered by this page, and each toggle
  // is a stepped job whose last step independently re-reads the host — so the audit
  // table below only says "ok" when the change was observed, not just requested.
  import { useQueryClient } from '@tanstack/svelte-query';
  import { RefreshCw, ShieldCheck, ShieldAlert, History, ExternalLink } from '@lucide/svelte';
  import { useAutoupdate, useAutoupdateAudit, setAutoupdate, AUTOUPDATE_KEY, AUTOUPDATE_AUDIT_KEY, type AutoupdateHost } from '$lib/api/maintenance';
  import { jobStore, type Job } from '$lib/stores/jobs.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { ApiError } from '$lib/api/client';
  import { relTime } from '$lib/format';

  const qc = useQueryClient();
  const au = useAutoupdate();
  const audit = useAutoupdateAudit();

  let reason = $state('');
  let busy = $state<Record<string, boolean>>({});

  function refresh() {
    qc.invalidateQueries({ queryKey: AUTOUPDATE_KEY });
    qc.invalidateQueries({ queryKey: AUTOUPDATE_AUDIT_KEY });
  }

  // When an autoupdate job settles (SSE — possibly started from another tab), re-read
  // hosts and the trail once per newly settled job.
  let seenSettled = '';
  $effect(() => {
    const settled = jobStore.all.filter((j) => j.kind === 'autoupdate' && j.status !== 'running').map((j) => j.id).join();
    if (settled && settled !== seenSettled) { seenSettled = settled; refresh(); }
  });

  function status(h: AutoupdateHost): { label: string; tone: string; title: string } {
    if (!h.reachable || !h.supported) return { label: 'Unknown', tone: 'mute', title: h.error ?? 'no state' };
    if (!h.installed) return { label: 'Not installed', tone: 'mute', title: 'homelab-autoupdate.timer is not on this host' };
    if (h.mode === 'enabled') return { label: 'Auto-updating', tone: 'info', title: 'The 02:00 timer will run apt upgrade' };
    if (h.guaranteed) return { label: 'Disabled · guaranteed', tone: 'ok', title: 'Hold flag present and honored by the script' };
    return { label: 'Off · not guaranteed', tone: 'warn', title: h.problems.join('\n') || 'Timer is off but no hold flag' };
  }

  async function toggle(h: AutoupdateHost, enabled: boolean) {
    const ok = await confirm({
      title: `${enabled ? 'Enable' : 'Disable'} auto-updates on ${h.host}?`,
      tone: 'warn',
      confirmLabel: enabled ? 'Enable' : 'Disable',
      body: enabled
        ? `Removes the hold and re-enables the nightly 02:00 apt upgrade on ${h.host}.`
        : `Stops the nightly 02:00 apt upgrade on ${h.host} until you re-enable it. Manual "Upgrade now" in Control center still works.`,
      danger: enabled && h.host === 'opti'
        ? 'A docker-ce upgrade restarts every container on opti — dashboard, vault and bots.'
        : !enabled ? 'Security updates stop arriving on this host while it is held.' : undefined,
      note: reason.trim() ? `Reason logged: ${reason.trim()}` : 'Add a reason above and it is written to the audit log.',
    });
    if (!ok) return;
    busy = { ...busy, [h.host]: true };
    try {
      const r = await setAutoupdate(h.host, enabled, reason.trim());
      if (r.job) jobStore.push(r.job);
      toast(`Auto-updates ${enabled ? 'enabled' : 'disabled'} on ${h.host} — verified`, 'ok');
    } catch (e) {
      const err = e as ApiError;
      const job = (err.body as { job?: Job } | null)?.job;
      if (job) jobStore.push(job);
      toast(`Could not ${enabled ? 'enable' : 'disable'} auto-updates on ${h.host}: ${err.message}`, 'crit', { sticky: true });
    } finally {
      busy = { ...busy, [h.host]: false };
      refresh();
    }
  }

  async function all(enabled: boolean) {
    for (const h of au.data?.hosts ?? []) {
      if (h.supported && h.installed && h.mode !== (enabled ? 'enabled' : 'disabled')) await toggle(h, enabled);
    }
  }

  const verifyLine = (steps: { key: string; output: string | null }[]) =>
    steps.find((s) => s.key === 'verify')?.output?.split('\n').pop() ?? '';
  const reasonOf = (steps: { key: string; output: string | null }[]) =>
    steps.find((s) => s.key === 'apply')?.output?.split('\n').find((l) => l.startsWith('reason: '))?.slice(8) ?? '';
</script>

<div class="grid">
  <section class="card c12">
    <div class="chead">
      <h3>Automatic updates</h3>
      <span class="meta">
        {#if au.data}
          {au.data.summary.enabled} on · {au.data.summary.disabled} off{au.data.summary.unknown ? ` · ${au.data.summary.unknown} unknown` : ''} · checked {relTime(au.data.checked_at)}
        {:else if au.isError}unavailable{:else}reading hosts…{/if}
      </span>
      <div class="right">
        <button class="tbtn sm" onclick={refresh} disabled={au.isFetching}><RefreshCw /> Re-read</button>
        <button class="tbtn sm" onclick={() => all(false)}>Disable all</button>
        <button class="tbtn sm" onclick={() => all(true)}>Enable all</button>
      </div>
    </div>
    <p class="faint intro">
      Nightly <code>homelab-autoupdate</code> runs <code>apt-get upgrade</code> at 02:00 on each host. A docker-ce upgrade restarts
      dockerd and every container on that host. Disabling writes a hold flag the update script checks, so it holds through
      deploys that re-enable the timer.
    </p>
    <label class="reason">
      <span>Reason <span class="faint">(optional, audited)</span></span>
      <input class="input" placeholder="e.g. docker restarts took the app tier down" bind:value={reason} maxlength="300" />
    </label>

    {#if au.isError}<p class="err">Could not read host state: {(au.error as Error).message}</p>{/if}

    <div class="hosts">
      {#each au.data?.hosts ?? [] as h (h.host)}
        {@const s = status(h)}
        <div class="hrow">
          <div class="hname">
            {#if s.tone === 'ok'}<ShieldCheck size={16} class="ok-ic" />{:else if s.tone === 'warn'}<ShieldAlert size={16} class="warn-ic" />{/if}
            <b>{h.host}</b>
            <span class="chip" data-s={s.tone} title={s.title}>{s.label}</span>
          </div>
          <div class="hdetail faint">
            {#if !h.supported}
              {h.error}
            {:else}
              {#if h.mode === 'enabled'}next run {h.timer?.next_run || '—'}{:else if h.flag}held by {h.flag.by ?? '?'}{h.flag.at ? ` · ${relTime(h.flag.at)}` : ''}{h.flag.reason ? ` · “${h.flag.reason}”` : ''}{/if}
              {#if h.last_run?.started_at} · last run {h.last_run.started_at} ({h.last_run.result}){/if}
              {#each h.problems as p (p)}<div class="problem">⚠ {p}</div>{/each}
            {/if}
          </div>
          <div class="hctl">
            {#if h.supported && h.installed}
              <div class="seg" role="group" aria-label="Auto-updates on {h.host}">
                <button class="seg-btn" class:active={h.mode === 'enabled'} disabled={busy[h.host] || h.mode === 'enabled'} onclick={() => toggle(h, true)}>On</button>
                <button class="seg-btn" class:active={h.mode === 'disabled'} disabled={busy[h.host] || (h.mode === 'disabled' && !!h.guaranteed)} onclick={() => toggle(h, false)}>Off</button>
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </section>

  <section class="card c12">
    <div class="chead">
      <h3><History size={12} /> Audit · auto-update changes</h3>
      <span class="meta">last 365 days · permanent JSONL trail</span>
      <div class="right"><a class="tbtn sm" href="/feed?view=audit"><ExternalLink /> Full audit</a></div>
    </div>
    {#if audit.isError}<p class="err">Audit trail unavailable.</p>{/if}
    {#if audit.data && audit.data.entries.length === 0}<p class="faint">No auto-update changes recorded yet.</p>{/if}
    {#if audit.data?.entries.length}
      <div class="tablewrap">
        <table class="t">
          <thead><tr><th>When</th><th>Host</th><th>Change</th><th>Result</th><th>Reason</th><th>Verification</th></tr></thead>
          <tbody>
            {#each audit.data.entries as e (e.id)}
              <tr>
                <td title={e.started_at}>{relTime(e.started_at)}</td>
                <td>{e.host}</td>
                <td>{e.target === 'disabled' ? 'Disable' : 'Enable'}</td>
                <td><span class="chip" data-s={e.status === 'ok' ? 'ok' : 'crit'}>{e.status === 'ok' ? 'verified' : e.status}</span></td>
                <td class="faint">{reasonOf(e.steps) || '—'}</td>
                <td class="faint vline">{e.status === 'ok' ? verifyLine(e.steps) : (e.error ?? '')}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
</div>

<style>
  .intro { margin: 0; font-size: 11.5px; }
  .reason { display: flex; align-items: center; gap: var(--s2); font-size: 12px; flex-wrap: wrap; }
  .reason .input { flex: 1; min-width: 200px; }
  .hosts { display: flex; flex-direction: column; }
  .hrow { display: grid; grid-template-columns: minmax(180px, 1fr) 2fr auto; gap: var(--s3); align-items: center; padding: 10px 0; border-top: 1px solid var(--border); }
  .hname { display: flex; align-items: center; gap: 8px; }
  .hdetail { font-size: 11.5px; min-width: 0; overflow-wrap: anywhere; }
  .problem { color: var(--warn); margin-top: 2px; }
  .vline { max-width: 420px; }
  .hname :global(.ok-ic) { color: var(--ok); }
  .hname :global(.warn-ic) { color: var(--warn); }
  @media (max-width: 720px) {
    .hrow { grid-template-columns: 1fr auto; }
    .hdetail { grid-column: 1 / -1; grid-row: 2; }
  }
</style>
