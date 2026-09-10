<script lang="ts">
  // Data flow view — how every fact in the homelab gets from the thing that observes
  // it to the thing that reads it, with live freshness on each hop.
  //
  // The map is not derived from scanning the filesystem: a machine can see that a file
  // exists but not what it is for or who reads it. It comes from the curated `datasets`
  // registry in homelab/tools/homelab-db/ingest.py, joined with real ingest state. That
  // same registry renders generated/92-data-flows.md and answers the hl_dataplane MCP
  // tool, so this page, the docs, and what an agent sees can never disagree.
  //
  // Port of webapp.v2.legacy/frontend/src/pages/DataFlow.tsx. homelab-db lives on opti
  // (a single point of failure) and answers 503 with { ok: false, error, hint } when
  // opti is unreachable — that body is rendered honestly below rather than a blank page
  // or a generic error boundary (retry: 0, same posture as DbHealth.svelte).
  //
  // Moved verbatim from the old routes/data/+page.svelte body when Data gained the
  // Data flow/Query tabs (2026-09-10) — see ./QueryView.svelte for the other tab.
  import { createQuery } from '@tanstack/svelte-query';
  import { get, ApiError } from '$lib/api/client';
  import { relTime, localeDateTime } from '$lib/format';

  interface Dataset {
    id: string;
    label: string;
    stage: 'producer' | 'store' | 'db' | 'consumer';
    producer: string;
    producer_host?: string | null;
    source: string;
    format?: string | null;
    cadence_hours?: number | null;
    consumers?: string | null;
    retention?: string | null;
    notes?: string | null;
    last_source_at?: string | null;
    last_ingested?: string | null;
    last_rows?: number | null;
    last_error?: string | null;
    age_hours?: number | null;
    stale?: boolean;
  }

  interface DataplaneResp {
    datasets?: Dataset[];
    database?: {
      history_from?: string;
      history_to?: string;
      runs?: number;
      rows?: Record<string, number>;
      schema_version?: number;
    };
  }

  // Shape of the 503 body opti's absence produces: { ok: false, error, hint }.
  interface DataplaneErrBody {
    ok?: false;
    error?: string;
    hint?: string;
  }

  const STAGES: { key: Dataset['stage']; title: string; blurb: string }[] = [
    { key: 'producer', title: 'Producers', blurb: 'observe the homelab' },
    { key: 'store', title: 'Stores', blurb: 'where facts land' },
    { key: 'db', title: 'Index', blurb: 'queryable, with history' },
    { key: 'consumer', title: 'Consumers', blurb: 'read it back' },
  ];

  const TABLE_BLURB: Record<string, string> = {
    agent_runs: 'one row per collector run, per day',
    findings: 'every warning and error the collectors raised',
    collector_metrics: 'numeric series — the long-range trends',
    docs: 'runbooks, rules and skills, chunked and full-text indexed',
    change_events: 'containers and mounts appearing, changing, vanishing',
    arch_nodes: 'the curated architecture graph',
    raw_documents: 'JSON that has no purpose-built table yet, still queryable',
    vitals_samples: 'durable per-minute host vitals',
  };

  const q = createQuery(() => ({
    queryKey: ['hldb-dataplane-page'],
    queryFn: () => get<DataplaneResp>('/api/hldb/dataplane', 20_000),
    refetchInterval: 5 * 60_000,
    retry: 0,
  }));

  let datasets = $derived(q.data?.datasets ?? []);
  let db = $derived(q.data?.database);
  let stale = $derived(datasets.filter((d) => d.stale || d.last_error));
  let rows = $derived(db?.rows ?? {});
  let rowEntries = $derived(Object.entries(rows));
  let totalRows = $derived(Object.values(rows).reduce((a, b) => a + b, 0));

  // The upstream error body when homelab-db answers 503 — surfaced verbatim so an
  // opti outage reads as "homelab-db unavailable: <error>" plus its hint, not a blank page.
  let errBody = $derived.by((): DataplaneErrBody | null => {
    const e = q.error;
    if (e instanceof ApiError && e.body && typeof e.body === 'object') {
      return e.body as DataplaneErrBody;
    }
    return null;
  });

  function stageItems(key: Dataset['stage']) {
    return datasets.filter((d) => d.stage === key);
  }
</script>

{#snippet freshness(d: Dataset)}
  {#if d.last_error}
    <span class="badge badge-stale" title={d.last_error}>error</span>
  {:else if !d.last_source_at}
    <span class="faint" title="Nothing ingested from this source yet">—</span>
  {:else if d.stale}
    <span class="badge badge-stale" title={`Expected every ${d.cadence_hours}h`}>{relTime(d.last_source_at)}</span>
  {:else}
    <span class="dim">{relTime(d.last_source_at)}</span>
  {/if}
{/snippet}

<div class="dataflow-page">
  <div class="board-bar">
    <span class="board-name">Data</span>
    {#if db}
      <span class="t-dim">
        {totalRows.toLocaleString()} rows indexed · history {localeDateTime(db.history_from)} → {localeDateTime(db.history_to)}
      </span>
    {/if}
    <span class="spacer"></span>
    {#if stale.length > 0}
      <span class="t-warn">{stale.length} feed{stale.length === 1 ? '' : 's'} stale</span>
    {:else}
      <span class="t-dim">all feeds fresh</span>
    {/if}
  </div>

  {#if q.isError}
    <div class="glass card">
      <div class="w-head"><span class="w-title">homelab-db unavailable</span></div>
      {#if errBody?.error}
        <p class="err">{errBody.error}</p>
      {/if}
      {#if errBody?.hint}
        <p class="t-dim">{errBody.hint}</p>
      {:else}
        <p class="t-dim">
          The database lives on opti and is served at <code>:9100</code>. If opti is up,
          check <code>homelab-db.service</code>; if this dashboard has never reached it,
          check <code>HOMELAB_DB_URL</code> and <code>HL_DB_TOKEN</code> in the webapp env.
        </p>
      {/if}
    </div>
  {/if}

  {#if q.isLoading}
    <div class="t-dim"><span class="spin"></span> Loading the data plane…</div>
  {/if}

  {#if !q.isLoading && !q.isError}
    <div class="flow-stages">
      {#each STAGES as stage (stage.key)}
        {@const items = stageItems(stage.key)}
        {#if items.length > 0}
          <section class="flow-stage">
            <header>
              <h3>{stage.title}</h3>
              <span class="t-dim">{stage.blurb}</span>
            </header>
            {#each items as d (d.id)}
              <article class="glass card flow-card" class:is-stale={d.stale || !!d.last_error}>
                <div class="flow-card-head">
                  <span class="w-title">{d.label}</span>
                  {@render freshness(d)}
                </div>
                <div class="mono t-dim flow-source">{d.source}</div>
                <div class="flow-meta t-dim">
                  {#if d.producer_host}<span>{d.producer_host}</span>{/if}
                  <span>{d.cadence_hours ? `every ${d.cadence_hours}h` : 'on demand'}</span>
                  {#if d.last_rows != null}<span>{d.last_rows.toLocaleString()} rows</span>{/if}
                </div>
                {#if d.notes}<p class="flow-notes t-dim">{d.notes}</p>{/if}
              </article>
            {/each}
          </section>
        {/if}
      {/each}
    </div>

    <div class="glass card">
      <div class="w-head">
        <span class="w-title">What is indexed</span>
        <span class="t-dim">
          schema v{db?.schema_version ?? '—'} · {(db?.runs ?? 0).toLocaleString()} collector runs
        </span>
      </div>
      <table class="detail-table">
        <thead>
          <tr><th>Table</th><th>Rows</th><th>What it holds</th></tr>
        </thead>
        <tbody>
          {#each rowEntries as [table, count] (table)}
            <tr>
              <td class="mono">{table}</td>
              <td>{count.toLocaleString()}</td>
              <td class="t-dim">{TABLE_BLURB[table] ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
