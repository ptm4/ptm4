<script lang="ts">
  // Sports bot: teams. League-scoped search plus a list, committed on "Save settings".
  // NBA only, by design: the bot's league support hasn't grown past it.
  import { Search, X } from '@lucide/svelte';
  import { botCall, BOT_BY_ID, botError, type SportsTeam } from '$lib/bots';

  let { teams, onChange }: { teams: SportsTeam[]; onChange: (t: SportsTeam[]) => void } = $props();

  const LEAGUES = [{ value: 'nba', label: 'NBA' }];
  let league = $state(LEAGUES[0].value);
  let q = $state('');
  let results = $state<SportsTeam[] | null>(null);
  let searching = $state(false);
  let err = $state<string | null>(null);

  async function search() {
    const query = q.trim();
    if (!query) return;
    searching = true; err = null;
    try {
      results = (await botCall<{ results?: SportsTeam[] }>(`/api/sports/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(query)}`, { timeoutMs: 25_000 }))?.results ?? [];
    } catch (e) { err = botError(BOT_BY_ID.sports, e); } finally { searching = false; }
  }
  function add(t: SportsTeam) {
    if (!teams.some((x) => x.league === t.league && x.abbrev === t.abbrev)) onChange([...teams, t]);
    q = ''; results = null;
  }
  const tag = (t: SportsTeam) => `${(t.league ?? '').toUpperCase()}${t.abbrev ? ` · ${t.abbrev}` : ''}`;
</script>

<section class="panel">
  <div class="panel-head"><h2>Teams ({teams.length})</h2></div>
  <div class="panel-body body">
    <div class="rows list">
      {#each teams as t, i (`${t.abbrev ?? t.name}-${i}`)}
        <div class="row item"><span>{t.name}</span><span class="mono faint">{tag(t)}</span>
          <button class="btn icon ghost" aria-label="Remove {t.name}" onclick={() => onChange(teams.filter((_, j) => j !== i))}><X size={14} /></button></div>
      {:else}
        <p class="faint">No teams. Search below to add one.</p>
      {/each}
    </div>
    <div class="add">
      <select class="field" bind:value={league}>{#each LEAGUES as l (l.value)}<option value={l.value}>{l.label}</option>{/each}</select>
      <input class="field" type="text" bind:value={q} placeholder="team name" onkeydown={(e) => { if (e.key === 'Enter') void search(); }} />
      <button class="btn" disabled={searching || !q.trim()} onclick={search}><Search size={14} /> {searching ? 'Searching…' : 'Search'}</button>
    </div>
    {#if err}<p class="crit">{err}</p>{/if}
    {#if results}
      <div class="results">
        {#each results as t, i (i)}
          <button class="btn" onclick={() => add(t)}>{t.name} <span class="faint">({tag(t)})</span></button>
        {:else}
          <p class="faint">No matches.</p>
        {/each}
      </div>
    {/if}
    <small class="faint">Changes here apply when you press "Save settings".</small>
  </div>
</section>

<style>
  .body { display: flex; flex-direction: column; gap: var(--s3); }
  .list { border: 1px solid var(--border); border-radius: var(--r); }
  .item { grid-template-columns: 1fr auto auto; padding: 4px var(--s3); font-size: var(--fs-sm); }
  .list p { margin: 0; padding: 6px var(--s3); }
  .add { display: flex; gap: 8px; }
  .add input { flex: 1; min-width: 0; }
  .results { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
  .crit { color: var(--crit); margin: 0; }
</style>
