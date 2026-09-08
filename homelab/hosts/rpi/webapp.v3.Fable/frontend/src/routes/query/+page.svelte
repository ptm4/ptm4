<script lang="ts">
  // Query — a SQL console over homelab.db, SSMS-shaped: schema on the left, editor on
  // top, results grid under it.
  //
  // There is deliberately no client-side SQL validation. Read-only is enforced where it
  // cannot be bypassed — the upstream opens the database on a read-only file descriptor
  // with a default-deny authorizer — and a second, weaker validator here would only drift
  // from the real one. Anything the engine refuses comes back as a plain error message,
  // and every query lands in the server's audit trail.
  import { createQuery, createMutation } from '@tanstack/svelte-query';
  import { get, post, ApiError } from '$lib/api/client';
  import SchemaTree, { type SchemaTable } from './_parts/SchemaTree.svelte';
  import ResultsGrid, { type QueryResp } from './_parts/ResultsGrid.svelte';

  interface SchemaResp {
    schema?: string;
    tables?: SchemaTable[];
    hints?: string[];
  }

  const STARTER = `-- homelab.db is read-only from here; SELECT away.
-- Click a table to peek at it, or try a canned query below.
SELECT tool, COUNT(*) AS runs, MIN(run_date) AS oldest, MAX(run_date) AS newest
FROM agent_runs GROUP BY tool ORDER BY runs DESC;`;

  const CANNED: { label: string; sql: string }[] = [
    {
      label: 'Pool fill trend',
      sql: `SELECT substr(at,1,10) AS day, ROUND(AVG(value),1) AS used_pct
FROM collector_metrics
WHERE metric='pool_used_pct' AND host='opti'
GROUP BY day ORDER BY day DESC LIMIT 30;`,
    },
    {
      label: 'Changes this week',
      sql: `SELECT at, host, kind, key, change FROM change_events
WHERE at > datetime('now','-7 day') ORDER BY at DESC;`,
    },
    {
      label: 'Open findings',
      sql: `SELECT severity, tool, host, message FROM findings
WHERE run_at > datetime('now','-1 day') AND severity IN ('critical','warn')
ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END;`,
    },
    {
      label: 'SMART history',
      sql: `SELECT substr(at,1,10) AS day, metric, value FROM collector_metrics
WHERE metric LIKE 'smart%reallocated' AND host='opti'
GROUP BY day, metric ORDER BY day DESC LIMIT 20;`,
    },
    {
      label: 'Who queried the DB',
      sql: `SELECT at, client, tool, rows_returned, ms, ok FROM query_audit
ORDER BY id DESC LIMIT 25;`,
    },
  ];

  let sql = $state(STARTER);

  const schema = createQuery(() => ({
    queryKey: ['hldb-schema'],
    queryFn: () => get<SchemaResp>('/api/hldb/schema', 20_000),
    staleTime: 5 * 60_000,
    retry: 0,
  }));

  const run = createMutation(() => ({
    mutationFn: (statement: string) =>
      post<QueryResp>('/api/hldb/query', { sql: statement }, 25_000),
  }));

  function runSql(statement: string) {
    sql = statement;
    run.mutate(statement);
  }

  function onKeyDown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      run.mutate(sql);
    }
  }

  const peek = (table: string) => runSql(`SELECT * FROM ${table} LIMIT 50;`);

  let errorText = $derived.by(() => {
    if (!run.isError) return null;
    const err = run.error;
    return err instanceof ApiError ? err.message : String(err);
  });

  let result = $derived(run.data);
  let tables = $derived(schema.data?.tables ?? []);
</script>

<div class="query-page">
  <div class="board-bar board-head">
    <div>
      <h1 class="board-title">Query</h1>
      <div class="board-sub">read-only SQL over homelab.db · every query is audited</div>
    </div>
    <span class="spacer"></span>
    {#if result?.ms != null && !run.isPending}
      <span class="t-dim num">{result.row_count} row{result.row_count === 1 ? '' : 's'} · {result.ms} ms</span>
    {/if}
  </div>

  <div class="query-layout">
    <SchemaTree {tables} loading={schema.isLoading} error={schema.isError} onpeek={peek} />

    <div class="query-main">
      <div class="card query-editor-card">
        <textarea
          class="query-editor mono"
          aria-label="SQL editor"
          bind:value={sql}
          spellcheck={false}
          onkeydown={onKeyDown}
          rows={8}
        ></textarea>
        <div class="query-actions">
          <button
            type="button"
            class="tbtn"
            disabled={run.isPending}
            onclick={() => run.mutate(sql)}
          >
            {run.isPending ? 'Running…' : 'Run (Ctrl+Enter)'}
          </button>
          <span class="query-canned">
            {#each CANNED as c (c.label)}
              <button type="button" class="tbtn" onclick={() => runSql(c.sql)}>{c.label}</button>
            {/each}
          </span>
        </div>
      </div>

      {#if errorText}
        <div class="card query-error">
          <span class="t-crit">{errorText}</span>
        </div>
      {/if}

      {#if result && !run.isError}
        <ResultsGrid {result} />
      {/if}
    </div>
  </div>
</div>
