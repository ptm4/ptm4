<script lang="ts">
  // Security section — the security-agent reports (journal hunter, persistence
  // auditor…) off /api/reports, same card grammar as the Collectors section. Moved
  // verbatim from the old routes/security/+page.svelte when it was folded into
  // Reports as a filter (2026-09-10).
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import type { ReportMeta } from '$lib/reports';
  import ReportCard from '$lib/components/reports/ReportCard.svelte';
  import ReportModal from '$lib/components/reports/ReportModal.svelte';

  interface ReportsResp { reports: ReportMeta[]; message?: string }

  let detail = $state<{ name: string; label: string } | null>(null);

  const q = createQuery(() => ({
    queryKey: ['reports'],
    queryFn: () => get<ReportsResp>('/api/reports'),
    refetchInterval: 5 * 60_000,
  }));
</script>

{#if q.isError}<div class="card t-crit">Cannot reach /api/reports — is the backend running?</div>{/if}
{#if q.isLoading}<div class="spin"></div>{/if}
{#if q.data?.reports.length === 0}
  <div class="card">{q.data.message ?? 'No security reports yet.'}</div>
{/if}

<div class="report-grid">
  {#each q.data?.reports ?? [] as r (r.name)}
    <ReportCard report={r} apiBase="reports">
      {#snippet actions()}
        <button class="tbtn" onclick={() => (detail = { name: r.name, label: r.label })}>View details</button>
      {/snippet}
    </ReportCard>
  {/each}
</div>

{#if detail}
  <ReportModal name={detail.name} label={detail.label} apiBase="reports" onclose={() => (detail = null)} />
{/if}
