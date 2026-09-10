<script lang="ts">
  // Full report body. Always shows what the run produced — never a bare "all clear":
  // an OK report still shows its summary, findings, the markdown log (new collectors),
  // or a structured dump of the data (legacy collectors without a log).
  import type { ReportDoc } from '$lib/reports';
  import { localeDateTime } from '$lib/format';
  import Markdown from '$lib/components/Markdown.svelte';
  import StatusBadge from './StatusBadge.svelte';
  import FindingList from './FindingList.svelte';
  import KvTable from './KvTable.svelte';

  let { data }: { data: ReportDoc } = $props();

  const SKIP = new Set(['tool', 'run_at', 'status', 'summary', 'findings', 'recommendations', 'log', 'hosts', 'name', 'label']);

  let findings = $derived(data.findings ?? []);
  let recs = $derived(data.recommendations ?? []);
  let rest = $derived.by(() => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(data)) if (!SKIP.has(k)) out[k] = v;
    return out;
  });
</script>

<div class="report-body">
  <div class="report-status-line">
    <StatusBadge status={data.status} />
    {#if data.run_at}<span class="report-runat">ran {localeDateTime(data.run_at)}</span>{/if}
  </div>
  {#if data.summary}<p class="report-summary">{data.summary}</p>{/if}
  {#if findings.length > 0}
    <h3 class="detail-section-title">Findings</h3>
    <FindingList items={findings} />
  {/if}
  {#if recs.length > 0}
    <h3 class="detail-section-title">Recommendations / watch list</h3>
    <FindingList items={recs} />
  {/if}
  {#if data.log}
    <Markdown source={data.log} />
  {:else}
    {#each data.hosts ?? [] as h, i (i)}
      <section>
        <h3 class="detail-section-title">{h.host || 'host'}</h3>
        {#if h.summary}<p class="report-summary">{h.summary}</p>{/if}
        {#if h.metrics}<KvTable obj={h.metrics} />{/if}
      </section>
    {/each}
    {#if Object.keys(rest).length > 0}
      <h3 class="detail-section-title">Details</h3>
      <KvTable obj={rest} />
    {/if}
  {/if}
</div>
