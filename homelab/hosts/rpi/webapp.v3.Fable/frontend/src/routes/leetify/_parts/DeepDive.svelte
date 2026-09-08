<script lang="ts">
  // One collapsible round-by-round table for a parsed demo.
  interface RoundRow {
    round?: number; won?: boolean | null; damage?: number; died?: boolean;
    killer?: string; planted?: boolean; defused?: boolean;
    kills?: unknown[];
  }
  interface DemoSummary {
    map: string; date: string; result: string; score?: string;
    kills?: number; deaths?: number; rating?: number; hs_pct?: number;
    hotspots?: { area: string; side: string; count: number; pct: number }[];
    rounds?: RoundRow[];
  }

  let { demo }: { demo: DemoSummary } = $props();

  let open = $state(false);
  let rounds = $derived(demo.rounds ?? []);
  let won = $derived(rounds.filter((r) => r.won === true).length);
  let lost = $derived(rounds.filter((r) => r.won === false).length);
</script>

<details class="deep-dive" bind:open>
  <summary>
    <span class="demo-map">{demo.map}</span>
    <span class="t-dim"> {demo.date} · {won}–{lost}</span>
    <span class="demo-result" data-s={demo.result}>{demo.result}</span>
  </summary>
  <table class="detail-table">
    <thead>
      <tr><th>#</th><th>Result</th><th>Kills</th><th>Damage</th><th>Objective</th><th>Fate</th></tr>
    </thead>
    <tbody>
      {#each rounds as r, i (i)}
        <tr data-s={r.won === true ? 'won' : r.won === false ? 'lost' : undefined}>
          <td>{r.round ?? i + 1}</td>
          <td>{r.won === true ? 'won' : r.won === false ? 'lost' : '—'}</td>
          <td>{(r.kills ?? []).length || '—'}</td>
          <td>{r.damage ?? '—'}</td>
          <td>{r.planted ? '💣 plant' : r.defused ? '🛡 defuse' : ''}</td>
          <td>{r.died ? (r.killer ? `died → ${r.killer}` : 'died') : 'survived'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</details>
