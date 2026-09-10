<script lang="ts">
  // The job drawer — bottom-right, above the toasts, showing what the webapp is doing
  // right now, step by step.
  //
  // This is the visible half of Peter's "the actions are such low feedback" complaint.
  // A toast said one thing once and vanished. This shows the whole plan the instant you
  // confirm — every step still pending — then ticks through it. If something fails you
  // see which step, what it said, and that the steps after it never ran.
  //
  // Design rules it follows:
  //   - The plan is visible before the work starts, not assembled as it goes.
  //   - A running step is the only one that moves. Nothing else animates.
  //   - A failed job does not auto-dismiss. You close it, having read it.
  //   - Nothing here is the record. The record is /feed?view=audit, and the drawer
  //     says so, so no one mistakes a disappearing panel for lost history.
  import { Loader, Check, X, Minus, ChevronDown } from '@lucide/svelte';
  import { jobStore, type Job, type JobStep } from '$lib/stores/jobs.svelte';

  let shown = $derived(jobStore.shown);

  const ICON = { running: Loader, ok: Check, failed: X, skipped: Minus, pending: null } as const;

  const stepTone = (s: JobStep) =>
    s.status === 'failed' ? 'crit' : s.status === 'running' ? 'run'
    : s.status === 'ok' ? 'done' : 'idle';

  const dur = (ms: number | null) => {
    if (ms == null) return '';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms / 60_000)}m`;
  };

  // "3 of 5" — what a person actually wants from a progress line.
  const progress = (j: Job) => {
    const done = j.steps.filter((s) => s.status === 'ok' || s.status === 'skipped').length;
    return `${done}/${j.steps.length}`;
  };
</script>

{#if shown.length}
  <aside class="jobs" aria-label="Running actions">
    {#each shown as job (job.id)}
      {@const open = jobStore.expanded === job.id}
      <section class="job" data-s={job.status} class:open>
        <header>
          <button class="head" onclick={() => jobStore.toggle(job.id)} aria-expanded={open}>
            <span class="dot" data-s={job.status}></span>
            <span class="title">{job.title}</span>
            <span class="prog">
              {#if job.status === 'running'}{progress(job)}{:else if job.status === 'ok'}done{:else}failed{/if}
            </span>
            <ChevronDown size={13} class="chev" aria-hidden="true" />
          </button>
          {#if job.status !== 'running'}
            <button class="x" onclick={() => jobStore.dismiss(job.id)} aria-label="Dismiss">
              <X size={13} aria-hidden="true" />
            </button>
          {/if}
        </header>

        {#if open}
          <ol class="steps">
            {#each job.steps as s (s.key)}
              {@const Icon = ICON[s.status]}
              <li data-t={stepTone(s)}>
                <span class="ico">
                  {#if Icon}<Icon size={12} class={s.status === 'running' ? 'spin' : ''} aria-hidden="true" />
                  {:else}<span class="pip"></span>{/if}
                </span>
                <span class="lbl">
                  {s.label}
                  {#if s.ms != null}<span class="ms">{dur(s.ms)}</span>{/if}
                </span>
                {#if s.detail && s.status === 'pending'}<span class="det">{s.detail}</span>{/if}
                {#if s.output}<pre class="out">{s.output}</pre>{/if}
              </li>
            {/each}
          </ol>

          {#if job.status === 'failed'}
            <p class="foot crit">
              Stopped at the step above. Anything still marked plain never ran.
            </p>
          {/if}
          <p class="foot">
            <a href="/feed?view=audit">Kept in the audit trail →</a>
          </p>
        {/if}
      </section>
    {/each}
  </aside>
{/if}

<style>
  .jobs { position: fixed; right: var(--s4); bottom: var(--s4); z-index: 60;
          display: flex; flex-direction: column; gap: var(--s2);
          width: min(400px, calc(100vw - var(--s5))); }

  .job { background: var(--surface); border: 1px solid var(--border);
         border-radius: var(--r); box-shadow: var(--sh-2); overflow: hidden; }
  .job[data-s="failed"] { border-color: var(--crit-muted); }
  .job[data-s="running"] { border-color: var(--accent-muted); }

  header { display: flex; align-items: stretch; }
  .head { flex: 1; display: flex; align-items: center; gap: var(--s2); min-width: 0;
          background: none; border: 0; color: var(--ink); font: inherit;
          font-size: var(--fs-sm); padding: var(--s3); cursor: pointer; text-align: left; }
  .head :global(.chev) { flex: none; color: var(--ink-3); transition: transform .15s; }
  .job.open .head :global(.chev) { transform: rotate(180deg); }
  .title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .prog { flex: none; font-size: var(--fs-xs); color: var(--ink-3);
          font-variant-numeric: tabular-nums; }
  .x { flex: none; background: none; border: 0; color: var(--ink-3); cursor: pointer;
       padding: 0 var(--s3); }
  .x:hover { color: var(--ink); }

  .dot { flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); }
  .dot[data-s="running"] { background: var(--accent); }
  .dot[data-s="ok"] { background: var(--ok); }
  .dot[data-s="failed"] { background: var(--crit); }

  .steps { list-style: none; margin: 0; padding: 0 var(--s3) var(--s2);
           border-top: 1px solid var(--border); }
  .steps li { display: grid; grid-template-columns: 18px 1fr; gap: 0 var(--s2);
              padding: var(--s2) 0; font-size: var(--fs-xs); color: var(--ink-3); }
  .steps li + li { border-top: 1px solid var(--border); }
  /* A step that has not run yet is quiet but legible — that is the plan, and the
     plan is the feature. Done steps recede; only the running one is bright. */
  .steps li[data-t="idle"] .lbl { color: var(--ink-3); }
  .steps li[data-t="done"] .lbl { color: var(--ink-2); }
  .steps li[data-t="run"]  .lbl { color: var(--accent); font-weight: 600; }
  .steps li[data-t="crit"] .lbl { color: var(--crit); font-weight: 600; }
  .ico { display: flex; align-items: center; justify-content: center; padding-top: 1px; }
  .steps li[data-t="done"] .ico { color: var(--ok); }
  .steps li[data-t="run"]  .ico { color: var(--accent); }
  .steps li[data-t="crit"] .ico { color: var(--crit); }
  .pip { width: 5px; height: 5px; border-radius: 50%; border: 1px solid var(--ink-3); }
  .lbl { line-height: 1.45; }
  .ms { color: var(--ink-3); font-weight: 400; margin-left: 6px;
        font-variant-numeric: tabular-nums; }
  .det { grid-column: 2; color: var(--ink-3); opacity: .85; line-height: 1.45; margin-top: 2px; }
  .out { grid-column: 2; margin: 4px 0 0; padding: var(--s2); border-radius: var(--r-sm);
         background: var(--bg-inset); color: var(--ink-2); font-family: var(--mono);
         font-size: var(--fs-xs); line-height: 1.5; white-space: pre-wrap;
         word-break: break-word; max-height: 140px; overflow: auto; }

  .foot { margin: 0; padding: var(--s2) var(--s3); font-size: var(--fs-xs);
          color: var(--ink-3); border-top: 1px solid var(--border); }
  .foot.crit { color: var(--crit); border-top: 0; padding-top: 0; }
  .foot a { color: var(--ink-3); }
  .foot a:hover { color: var(--accent); }

  :global(.spin) { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { :global(.spin) { animation: none; } }

  @media (max-width: 620px) {
    .jobs { left: var(--s3); right: var(--s3); width: auto; bottom: var(--s3); }
  }
</style>
