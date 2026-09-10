<script lang="ts">
  // Audit — every action the webapp has taken, kept permanently.
  //
  // The other two views on this page describe what the homelab DID. This one describes
  // what WE did to it, which is a different question and the one you ask when something
  // broke shortly after you pressed a button. It is deliberately the plainest view here:
  // a reverse-chronological list of jobs, each expandable into the exact steps that ran,
  // how long each took, and what the agent said.
  //
  // The source is an append-only JSONL file the backend never rewrites, so this survives
  // restarts, and can be read with `cat` if this page ever cannot be.
  import { createQuery } from '@tanstack/svelte-query';
  import { Check, X, Minus, ChevronDown, Loader } from '@lucide/svelte';
  import { get } from '$lib/api/client';
  import type { Job, JobStep } from '$lib/stores/jobs.svelte';
  import { relTime } from '$lib/format';

  interface AuditResp { entries: Job[]; count: number; days: number }

  let days = $state(30);
  let kind = $state<string | null>(null);
  let open = $state<string | null>(null);

  const audit = createQuery(() => ({
    queryKey: ['jobs', 'audit', days],
    queryFn: () => get<AuditResp>(`/api/jobs/audit?days=${days}&limit=300`, 20_000),
    staleTime: 30_000,
    retry: 0,
  }));

  let all = $derived(audit.data?.entries ?? []);
  let kinds = $derived([...new Set(all.map((e) => e.kind))].sort());
  let rows = $derived(kind ? all.filter((e) => e.kind === kind) : all);

  // Counting failures is the reason to open this page at all, so it goes up top.
  let failed = $derived(all.filter((e) => e.status === 'failed').length);

  const ICON = { running: Loader, ok: Check, failed: X, skipped: Minus, pending: null } as const;
  const dur = (ms: number | null) =>
    ms == null ? '' : ms < 1000 ? `${ms}ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 60_000)}m`;
  const stepTone = (s: JobStep) =>
    s.status === 'failed' ? 'crit' : s.status === 'ok' ? 'done' : s.status === 'skipped' ? 'skip' : 'idle';
  const span = (j: Job) => {
    if (!j.finished_at) return 'unfinished';
    const ms = Date.parse(j.finished_at) - Date.parse(j.started_at);
    return Number.isFinite(ms) ? dur(ms) : '';
  };
</script>

<div class="audit">
  <div class="bar">
    <span class="sum">
      {#if audit.isPending}reading the trail…
      {:else}
        <b>{all.length}</b> action{all.length === 1 ? '' : 's'} in the last {days} days
        {#if failed > 0}<span class="fail">· {failed} failed</span>{/if}
      {/if}
    </span>
    <div class="spacer"></div>
    <div class="chips">
      {#each kinds as k (k)}
        <button class="chip" class:on={kind === k} onclick={() => (kind = kind === k ? null : k)}>{k}</button>
      {/each}
    </div>
    <div class="ranges">
      {#each [7, 30, 90, 365] as d (d)}
        <button class="chip" class:on={days === d} onclick={() => (days = d)}>{d}d</button>
      {/each}
    </div>
  </div>

  {#if audit.isError}
    <p class="state err">Could not read the audit trail: {(audit.error as Error).message}</p>
  {:else if !audit.isPending && rows.length === 0}
    <p class="state">
      Nothing recorded yet. Every reboot, upgrade, container restart and service restart
      run from this dashboard is written here from the moment it is started.
    </p>
  {:else}
    <ul class="list">
      {#each rows as j (j.id)}
        {@const isOpen = open === j.id}
        <li data-s={j.status}>
          <button class="row" onclick={() => (open = isOpen ? null : j.id)} aria-expanded={isOpen}>
            <span class="dot" data-s={j.status}></span>
            <span class="ttl">{j.title}</span>
            <span class="kind">{j.kind}</span>
            <span class="when">{relTime(j.started_at)}</span>
            <span class="took">{span(j)}</span>
            <ChevronDown size={13} class="chev" aria-hidden="true" />
          </button>

          {#if isOpen}
            <div class="detail">
              {#if j.error}<p class="err">{j.error}</p>{/if}
              <ol class="steps">
                {#each j.steps as s (s.key)}
                  {@const Icon = ICON[s.status]}
                  <li data-t={stepTone(s)}>
                    <span class="ico">
                      {#if Icon}<Icon size={12} aria-hidden="true" />{:else}<span class="pip"></span>{/if}
                    </span>
                    <span class="lbl">
                      {s.label}
                      {#if s.ms != null}<span class="ms">{dur(s.ms)}</span>{/if}
                      {#if s.status === 'pending'}<span class="ms">never ran</span>{/if}
                    </span>
                    {#if s.output}<pre class="out">{s.output}</pre>{/if}
                  </li>
                {/each}
              </ol>
              <p class="meta">
                {j.actor} · started {new Date(j.started_at).toLocaleString()}
                {#if j.host}· on {j.host}{/if}
                · id <code>{j.id}</code>
              </p>
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .bar { display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s4); }
  .sum { font-size: var(--fs-sm); color: var(--ink-2); }
  .sum b { color: var(--ink); }
  .fail { color: var(--crit); }
  .spacer { flex: 1; }
  .chips, .ranges { display: flex; gap: var(--s1); flex-wrap: wrap; }
  .chip { background: var(--surface); border: 1px solid var(--border); color: var(--ink-3);
          border-radius: 999px; padding: 2px var(--s3); font-size: var(--fs-xs); cursor: pointer; }
  .chip:hover { color: var(--ink); border-color: var(--border-2); }
  .chip.on { background: var(--accent-dim); border-color: var(--accent-muted); color: var(--accent); }

  .list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border);
          border-radius: var(--r); overflow: hidden; }
  .list > li { border-bottom: 1px solid var(--border); }
  .list > li:last-child { border-bottom: 0; }

  .row { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto auto 16px;
         gap: var(--s3); align-items: center; width: 100%; text-align: left;
         background: var(--surface); border: 0; padding: var(--s3); cursor: pointer;
         color: var(--ink); font: inherit; font-size: var(--fs-sm); }
  .row:hover { background: var(--surface-2); }
  .row :global(.chev) { color: var(--ink-3); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
  .dot[data-s="failed"] { background: var(--crit); }
  .dot[data-s="running"] { background: var(--accent); }
  .ttl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kind, .when, .took { font-size: var(--fs-xs); color: var(--ink-3); white-space: nowrap;
                        font-variant-numeric: tabular-nums; }
  .kind { font-family: var(--mono); }

  .detail { padding: 0 var(--s4) var(--s3) var(--s5); background: var(--bg-inset); }
  .detail .err { color: var(--crit); font-size: var(--fs-xs); margin: var(--s3) 0 0; }
  .steps { list-style: none; margin: var(--s2) 0 0; padding: 0; }
  .steps li { display: grid; grid-template-columns: 18px 1fr; gap: 0 var(--s2);
              padding: 5px 0; font-size: var(--fs-xs); }
  .steps li[data-t="idle"] .lbl { color: var(--ink-3); }
  .steps li[data-t="skip"] .lbl { color: var(--ink-3); }
  .steps li[data-t="done"] .lbl { color: var(--ink-2); }
  .steps li[data-t="crit"] .lbl { color: var(--crit); font-weight: 600; }
  .steps li[data-t="done"] .ico { color: var(--ok); }
  .steps li[data-t="crit"] .ico { color: var(--crit); }
  .ico { display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
  .pip { width: 5px; height: 5px; border-radius: 50%; border: 1px solid var(--ink-3); }
  .ms { color: var(--ink-3); margin-left: 6px; font-variant-numeric: tabular-nums; }
  .out { grid-column: 2; margin: 3px 0 0; padding: var(--s2); border-radius: var(--r-sm);
         background: var(--surface); color: var(--ink-2); font-family: var(--mono);
         font-size: var(--fs-xs); line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
  .meta { margin: var(--s3) 0 0; font-size: var(--fs-xs); color: var(--ink-3); }
  .meta code { font-family: var(--mono); }

  .state { color: var(--ink-3); font-size: var(--fs-sm); padding: var(--s5) 0; max-width: 60ch; line-height: 1.6; }
  .state.err { color: var(--crit); }

  @media (max-width: 720px) {
    .row { grid-template-columns: 10px minmax(0, 1fr) auto 16px; }
    .kind, .took { display: none; }
  }
</style>
