<script lang="ts">
  // One runner/security report as a card — with the enable/disable + run-now
  // dispatcher controls. `actions` snippet supplies the page-specific buttons.
  import type { Snippet } from 'svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { post, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { localeDateTime } from '$lib/format';
  import { dispatcherErrorMessage, type ReportApiBase, type ReportMeta } from '$lib/reports';
  import StatusBadge from './StatusBadge.svelte';

  let { report, apiBase, actions, onTail }: {
    report: ReportMeta;
    apiBase: ReportApiBase;
    actions?: Snippet;
    /** open the live log drawer for this runner (runners only) */
    onTail?: (name: string, label: string) => void;
  } = $props();

  const qc = useQueryClient();

  const toggle = createMutation(() => ({
    mutationFn: () => post(`/api/${apiBase}/${encodeURIComponent(report.agent!)}/enabled`, { enabled: !report.enabled }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: [apiBase] }); },
    onError: (e: Error) => {
      const err = e as ApiError;
      toast(dispatcherErrorMessage(err.status ?? 0, err.message), 'crit', { ttlMs: 8000 });
    },
  }));

  const run = createMutation(() => ({
    mutationFn: () => post(`/api/${apiBase}/${encodeURIComponent(report.agent!)}/run`),
    onSuccess: () => {
      toast(`${report.label} queued`, 'ok');
      // v1 fired and forgot for ~90s; the drawer tails the runner's own log instead.
      onTail?.(report.name, report.label);
    },
    onError: (e: Error) => {
      const err = e as ApiError;
      toast(dispatcherErrorMessage(err.status ?? 0, err.message), 'crit', { ttlMs: 8000 });
    },
  }));
</script>

<article class="report-card card" class:disabled={!report.enabled} data-s={report.status}>
  <header>
    <StatusBadge status={report.status} />
    <h3>{report.label}</h3>
    {#if report.has_alert}<span class="badge badge-alert" title="Alert flagged in this report">ALERT</span>{/if}
    {#if report.stale}<span class="badge badge-stale" title="No fresh run recently">STALE</span>{/if}
  </header>
  <p class="report-summary">{report.summary || 'No summary available'}</p>
  <div class="report-meta">Last run: {localeDateTime(report.run_at)}</div>
  <footer class="report-actions">
    {#if actions}{@render actions()}{/if}
    {#if report.agent}
      <button class="tbtn toggle {report.enabled ? 'on' : 'off'}" disabled={toggle.isPending} onclick={() => toggle.mutate()}>
        {report.enabled ? 'Enabled' : 'Disabled'}
      </button>
      <button class="tbtn" disabled={run.isPending} onclick={() => run.mutate()}>
        {run.isPending ? 'Queued…' : 'Run now'}
      </button>
    {/if}
  </footer>
</article>
