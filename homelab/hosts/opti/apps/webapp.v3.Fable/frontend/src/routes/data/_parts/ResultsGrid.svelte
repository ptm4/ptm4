<script lang="ts">
  // Results grid for one query response: truncation notice, empty state, or the
  // column/row table. Cells render NULL dimmed and objects as JSON.
  export interface QueryResp {
    columns?: string[];
    rows?: unknown[][];
    row_count?: number;
    truncated?: boolean;
    ms?: number;
    note?: string | null;
  }

  let { result }: { result: QueryResp } = $props();

  function cell(v: unknown): string {
    if (v === null || v === undefined) return 'NULL';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }

  let columns = $derived(result.columns ?? []);
  let rows = $derived(result.rows ?? []);
</script>

<div class="card query-results">
  {#if result.truncated}
    <div class="t-warn query-truncated">{result.note}</div>
  {/if}
  {#if rows.length === 0}
    <div class="t-dim">No rows.</div>
  {:else}
    <div class="query-grid-wrap">
      <table class="detail-table query-grid">
        <thead>
          <tr>
            {#each columns as c, i (i)}<th>{c}</th>{/each}
          </tr>
        </thead>
        <tbody>
          {#each rows as r, i (i)}
            <tr>
              {#each r as v, j (j)}
                <td class:t-dim={v === null}>{cell(v)}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  /* .detail-table styles the first column as a dim label column (key/value use);
     a results grid wants every column treated alike. */
  .query-grid th {
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--ink-3);
    padding: 6px var(--s2);
    border-bottom: 1px solid var(--border-2);
    white-space: nowrap;
    position: sticky;
    top: 0;
    background: var(--surface);
  }
  .query-grid td:first-child {
    color: inherit;
    white-space: nowrap;
    width: auto;
    padding-right: var(--s2);
  }
  .query-grid td { font-family: var(--mono); font-variant-numeric: tabular-nums; }
</style>
