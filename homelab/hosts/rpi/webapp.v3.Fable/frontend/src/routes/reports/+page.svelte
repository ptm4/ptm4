<script lang="ts">
  // Runners page — the scheduled collectors (doctor, hardware, software, network,
  // coldcopy) with enable/run controls, latest-report viewer and per-run history.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import type { ReportMeta } from '$lib/reports';
  import ReportCard from '$lib/components/reports/ReportCard.svelte';
  import ReportModal from '$lib/components/reports/ReportModal.svelte';
  import HistoryModal from '$lib/components/reports/HistoryModal.svelte';
  import LogTail from '$lib/components/LogTail.svelte';

  interface RunnersResp { runners: ReportMeta[] }
  interface AgentsResp { hosts: { reachable: boolean; drift_count?: number }[] }

  type ModalState =
    | { kind: 'none' }
    | { kind: 'report'; name: string; label: string; date?: string }
    | { kind: 'history'; name: string; label: string };

  let modal = $state<ModalState>({ kind: 'none' });
  let tail = $state<{ name: string; label: string } | null>(null);

  const runners = createQuery(() => ({
    queryKey: ['runners'],
    queryFn: () => get<RunnersResp>('/api/runners'),
    refetchInterval: 5 * 60_000,
  }));
  const agents = createQuery(() => ({
    queryKey: ['agents-strip'],
    queryFn: () => get<AgentsResp>('/api/agents', 15_000),
    refetchInterval: 5 * 60_000,
  }));

  let unreachable = $derived(agents.data?.hosts.filter((h) => !h.reachable).length ?? 0);
  let drift = $derived(agents.data?.hosts.reduce((n, h) => n + (h.drift_count || 0), 0) ?? 0);
</script>

<div class="reports-page">
  <div class="agents-strip card">
    🛰️ Architecture agents
    {#if agents.data}
      — {agents.data.hosts.length} host(s)
      {#if unreachable > 0} · <span class="t-crit">{unreachable} unreachable</span>{/if}
      {#if drift > 0} · <span class="t-warn">{drift} drift</span>{/if}
    {/if}
    — <a href="/agents/">view status →</a>
  </div>

  {#if runners.isError}
    <div class="card t-crit">Cannot reach /api/runners — is the backend running?</div>
  {/if}
  {#if runners.isLoading}<div class="spin"></div>{/if}
  {#if runners.data?.runners.length === 0}
    <div class="card">No runner reports yet. Run them from opti (GitHub Actions or the dispatcher).</div>
  {/if}

  <div class="report-grid">
    {#each runners.data?.runners ?? [] as r (r.name)}
      <ReportCard report={r} apiBase="runners" onTail={(name, label) => (tail = { name, label })}>
        {#snippet actions()}
          <button class="tbtn" onclick={() => (modal = { kind: 'report', name: r.name, label: r.label })}>View latest</button>
          <button class="tbtn" onclick={() => (modal = { kind: 'history', name: r.name, label: r.label })}>History</button>
          <button class="tbtn" onclick={() => (tail = { name: r.name, label: r.label })}>Log</button>
        {/snippet}
      </ReportCard>
    {/each}
  </div>

  {#if tail}<LogTail name={tail.name} label={tail.label} onclose={() => (tail = null)} />{/if}
  {#if modal.kind === 'report'}
    <ReportModal name={modal.name} label={modal.label} date={modal.date} onclose={() => (modal = { kind: 'none' })} />
  {:else if modal.kind === 'history'}
    {@const m = modal}
    <HistoryModal name={m.name} label={m.label}
      onOpenDate={(date) => (modal = { kind: 'report', name: m.name, label: m.label, date })}
      onclose={() => (modal = { kind: 'none' })} />
  {/if}
</div>
