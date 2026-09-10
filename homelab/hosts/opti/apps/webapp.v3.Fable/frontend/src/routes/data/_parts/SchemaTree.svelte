<script lang="ts">
  // Left rail of the SQL console: the table list from /api/hldb/schema. Clicking a
  // table "peeks" it (SELECT * … LIMIT 50) via the parent's callback.
  export interface SchemaTable { table: string; rows: number | null }

  let { tables, loading, error, onpeek }: {
    tables: SchemaTable[];
    loading: boolean;
    error: boolean;
    onpeek: (table: string) => void;
  } = $props();
</script>

<aside class="card query-schema">
  <div class="w-head"><span class="w-title">Tables</span></div>
  {#if loading}<div class="t-dim">loading…</div>{/if}
  {#if error}<div class="t-dim">homelab-db unavailable</div>{/if}
  <div class="query-tables">
    {#each tables as t (t.table)}
      <button
        type="button"
        class="query-table-btn"
        title={`SELECT * FROM ${t.table} LIMIT 50`}
        onclick={() => onpeek(t.table)}
      >
        <span class="mono">{t.table}</span>
        <span class="t-dim num">{t.rows?.toLocaleString() ?? '—'}</span>
      </button>
    {/each}
  </div>
</aside>
