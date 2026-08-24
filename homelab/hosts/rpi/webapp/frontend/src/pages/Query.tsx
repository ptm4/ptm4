// Query — a SQL console over homelab.db, SSMS-shaped: schema on the left, editor on
// top, results grid under it.
//
// There is deliberately no client-side SQL validation. Read-only is enforced where it
// cannot be bypassed — the upstream opens the database on a read-only file descriptor
// with a default-deny authorizer — and a second, weaker validator here would only drift
// from the real one. Anything the engine refuses comes back as a plain error message,
// and every query lands in the server's audit trail.
import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { get, post, ApiError } from '../lib/api';

interface SchemaResp {
  schema?: string;
  tables?: { table: string; rows: number | null }[];
  hints?: string[];
}

interface QueryResp {
  columns?: string[];
  rows?: unknown[][];
  row_count?: number;
  truncated?: boolean;
  ms?: number;
  note?: string | null;
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

function cell(v: unknown): string {
  if (v === null || v === undefined) return 'NULL';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export default function QueryPage() {
  const [sql, setSql] = useState(STARTER);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const schema = useQuery({
    queryKey: ['hldb-schema'],
    queryFn: () => get<SchemaResp>('/api/hldb/schema', 20_000),
    staleTime: 5 * 60_000,
    retry: 0,
  });

  const run = useMutation({
    mutationFn: (statement: string) =>
      post<QueryResp>('/api/hldb/query', { sql: statement }, 25_000),
  });

  const runSql = (statement: string) => {
    setSql(statement);
    run.mutate(statement);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      run.mutate(sql);
    }
  };

  const peek = (table: string) => runSql(`SELECT * FROM ${table} LIMIT 50;`);

  const errorText = useMemo(() => {
    if (!run.isError) return null;
    const err = run.error;
    return err instanceof ApiError ? err.message : String(err);
  }, [run.isError, run.error]);

  const result = run.data;

  return (
    <div className="query-page">
      <div className="board-bar">
        <span className="board-name">Query</span>
        <span className="t-dim">read-only SQL over homelab.db · every query is audited</span>
        <span className="spacer" />
        {result?.ms != null && !run.isPending && (
          <span className="t-dim">{result.row_count} row{result.row_count === 1 ? '' : 's'} · {result.ms} ms</span>
        )}
      </div>

      <div className="query-layout">
        <aside className="glass card query-schema">
          <div className="w-head"><span className="w-title">Tables</span></div>
          {schema.isLoading && <div className="t-dim">loading…</div>}
          {schema.isError && <div className="t-dim">homelab-db unavailable</div>}
          <div className="query-tables">
            {(schema.data?.tables ?? []).map((t) => (
              <button
                key={t.table}
                type="button"
                className="query-table-btn"
                title={`SELECT * FROM ${t.table} LIMIT 50`}
                onClick={() => peek(t.table)}
              >
                <span className="mono">{t.table}</span>
                <span className="t-dim">{t.rows?.toLocaleString() ?? '—'}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="query-main">
          <div className="glass card query-editor-card">
            <textarea
              ref={editorRef}
              className="query-editor mono"
              value={sql}
              spellCheck={false}
              onChange={(e) => setSql(e.target.value)}
              onKeyDown={onKeyDown}
              rows={8}
            />
            <div className="query-actions">
              <button
                type="button"
                className="tb-btn"
                disabled={run.isPending}
                onClick={() => run.mutate(sql)}
              >
                {run.isPending ? 'Running…' : 'Run (Ctrl+Enter)'}
              </button>
              <span className="query-canned">
                {CANNED.map((c) => (
                  <button key={c.label} type="button" className="tb-btn" onClick={() => runSql(c.sql)}>
                    {c.label}
                  </button>
                ))}
              </span>
            </div>
          </div>

          {errorText && (
            <div className="glass card query-error">
              <span className="t-crit">{errorText}</span>
            </div>
          )}

          {result && !run.isError && (
            <div className="glass card query-results">
              {result.truncated && (
                <div className="t-warn query-truncated">{result.note}</div>
              )}
              {(result.rows?.length ?? 0) === 0 ? (
                <div className="t-dim">No rows.</div>
              ) : (
                <div className="query-grid-wrap">
                  <table className="detail-table query-grid">
                    <thead>
                      <tr>{(result.columns ?? []).map((c, i) => <th key={i}>{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {(result.rows ?? []).map((r, i) => (
                        <tr key={i}>
                          {r.map((v, j) => (
                            <td key={j} className={v === null ? 't-dim' : undefined}>
                              {cell(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
