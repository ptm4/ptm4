<script lang="ts">
  // sports: teams — league-scoped search + list, committed on Save.
  import { createMutation } from '@tanstack/svelte-query';
  import { Search, X } from '@lucide/svelte';
  import { get, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import type { SportsTeam } from '$lib/bots';

  let { teams, onChange }: {
    teams: SportsTeam[];
    onChange: (teams: SportsTeam[]) => void;
  } = $props();

  function extraErrorMessage(e: unknown, fallback: string): string {
    return (e as ApiError)?.message ?? fallback;
  }

  // NBA only by design — the bot's league support hasn't grown past it.
  const SPORTS_LEAGUES = [{ value: 'nba', label: 'NBA' }];
  const LEAGUE_EMOJI: Record<string, string> = { nba: '🏀' };

  let league = $state(SPORTS_LEAGUES[0].value);
  let q = $state('');
  let results = $state<SportsTeam[] | null>(null);

  const search = createMutation(() => ({
    mutationFn: (query: string) =>
      get<{ results?: SportsTeam[] }>(
        `/api/sports/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(query)}`, 25_000),
    onSuccess: (d) => { results = d?.results ?? []; },
    onError: (e: Error) => toast(extraErrorMessage(e, 'Team search failed.'), 'crit'),
  }));

  function add(t: SportsTeam) {
    if (!teams.some((x) => x.league === t.league && x.abbrev === t.abbrev)) onChange([...teams, t]);
    q = '';
    results = null;
  }
</script>

<section class="card bot-extra">
  <div class="w-head">
    <span class="w-title">Teams ({teams.length})</span>
  </div>
  <div class="bot-list">
    {#each teams as t, i (`${t.abbrev ?? t.name}-${i}`)}
      <div class="bot-list-row">
        <span aria-hidden="true">{LEAGUE_EMOJI[t.league ?? ''] ?? '🏟️'}</span> <span>{t.name}</span>
        <span class="spacer"></span>
        <span class="bot-list-meta mono">
          {(t.league ?? '').toUpperCase()}{t.abbrev ? ` · ${t.abbrev}` : ''}
        </span>
        <button class="tbtn sm danger" aria-label="Remove {t.name}"
          onclick={() => onChange(teams.filter((_, j) => j !== i))}><X size={14} aria-hidden="true" /></button>
      </div>
    {/each}
    {#if teams.length === 0}<p class="t-dim">No teams — search below to add one.</p>{/if}
  </div>
  <div class="bot-add-row">
    <select bind:value={league}>
      {#each SPORTS_LEAGUES as l (l.value)}<option value={l.value}>{l.label}</option>{/each}
    </select>
    <input type="text" bind:value={q} placeholder="team name…"
      onkeydown={(e) => { if (e.key === 'Enter' && q.trim()) search.mutate(q.trim()); }} />
    <button class="tbtn" disabled={search.isPending || !q.trim()}
      onclick={() => search.mutate(q.trim())}>
      <Search size={14} aria-hidden="true" /> {search.isPending ? 'Searching…' : 'Search'}
    </button>
  </div>
  {#if results}
    <div class="geo-results">
      {#each results as t, i (i)}
        <button class="tbtn" onclick={() => add(t)}>
          {t.name} <span class="t-dim">({(t.league ?? '').toUpperCase()}{t.abbrev ? ` · ${t.abbrev}` : ''})</span>
        </button>
      {/each}
      {#if results.length === 0}<p class="t-dim">No matches.</p>{/if}
    </div>
  {/if}
  <p class="form-note t-dim">Changes here are applied when you hit "Save settings".</p>
</section>
