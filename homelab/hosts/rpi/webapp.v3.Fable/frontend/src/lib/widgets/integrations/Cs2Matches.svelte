<script lang="ts">
  // Today's HLTV slate, same notable-match filter the Discord digest uses: live
  // scores, what's coming with a stream link, and results with per-map scores.
  // Port of v2 Cs2MatchesWidget (widgets/integrations.tsx).
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { opt, type WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';

  interface Cs2Match {
    id?: string; url?: string; event?: string; stars?: number; bo?: string;
    team1?: string; team2?: string; start_unix?: number;
    status?: 'upcoming' | 'live' | 'finished';
    score1?: number | null; score2?: number | null;
    maps?: { name?: string; s1?: number; s2?: number }[];
    stream?: { name?: string; url?: string } | null;
  }
  interface Cs2Day {
    date?: string; fetched_at?: number; stale?: boolean;
    vrs_as_of?: string; matches?: Cs2Match[];
  }

  let { options = {} }: WidgetProps = $props();
  let limit = $derived(Number(opt(options, 'limit', 6)) || 6);
  let sections = $derived(String(opt(options, 'sections', 'all')));

  const q = createQuery(() => ({
    queryKey: ['hltv-day'],
    queryFn: () => get<Cs2Day>('/api/hltv/day', 25_000),
    refetchInterval: 60_000,
    retry: 0,
  }));

  function clockOf(unix?: number): string {
    if (!unix) return '—';
    return new Date(unix * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  // Winner first, so the result reads without decoding which side is which.
  function result(m: Cs2Match) {
    const flip = (m.score2 ?? 0) > (m.score1 ?? 0);
    const [w, l] = flip ? [m.team2, m.team1] : [m.team1, m.team2];
    const [ws, ls] = flip ? [m.score2, m.score1] : [m.score1, m.score2];
    const maps = (m.maps ?? [])
      .map((mp) => `${mp.name} ${flip ? mp.s2 : mp.s1}–${flip ? mp.s1 : mp.s2}`)
      .join(' · ');
    return { w, l, ws, ls, maps };
  }

  let groups = $derived.by((): [string, Cs2Match[]][] => {
    const all = q.data?.matches ?? [];
    const pick = (s: Cs2Match['status']) => all.filter((m) => m.status === s);
    return [
      ['Live', sections === 'results' ? [] : pick('live')],
      ['Upcoming', sections === 'results' ? [] : pick('upcoming')],
      ['Results', sections === 'upcoming' ? [] : pick('finished')],
    ];
  });
  let shown = $derived(groups.reduce((n, [, ms]) => n + ms.length, 0));
  let fetchedIso = $derived(q.data?.fetched_at ? new Date(q.data.fetched_at * 1000).toISOString() : null);
</script>

{#if q.isError}
  <WidgetFrame title="CS2 today"><WidgetError message="hltv bot unreachable" /></WidgetFrame>
{:else}
  <WidgetFrame title="CS2 today" staleAt={fetchedIso} scroll>
    {#snippet head()}
      {#if q.data?.stale}
        <span class="t-warn" title="HLTV unreachable — showing the last good scrape" aria-label="stale data">⚠</span>
      {/if}
    {/snippet}
    {#if q.isLoading}<WidgetLoading />{/if}
    {#if !q.isLoading && shown === 0}<div class="t-dim">No notable matches today.</div>{/if}
    {#each groups as [label, ms] (label)}
      {#if ms.length > 0}
        <div>
          <div class="t-dim">{label}</div>
          <div class="kv-rows">
            {#each ms.slice(0, limit) as m, i (m.id ?? i)}
              {#if m.status === 'finished'}
                {@const r = result(m)}
                <div class="kv-row">
                  <span class="mono">✅</span>
                  <span>
                    <a href={m.url} target="_blank" rel="noreferrer"><strong>{r.w}</strong> {r.ws}–{r.ls} {r.l}</a>
                    {#if r.maps}<span class="t-dim"> · {r.maps}</span>{/if}
                  </span>
                </div>
              {:else}
                {@const live = m.status === 'live'}
                <div class="kv-row">
                  <span class="mono">{live ? '🔴' : clockOf(m.start_unix)}</span>
                  <span>
                    <a href={m.url} target="_blank" rel="noreferrer">
                      {#if live && m.score1 != null}
                        {m.team1} {m.score1}–{m.score2} {m.team2}
                      {:else}
                        {m.team1 ?? 'TBD'} <span class="t-dim">vs</span> {m.team2 ?? 'TBD'}
                      {/if}
                    </a>
                    {#if m.stream?.url}
                      · <a href={m.stream.url} target="_blank" rel="noreferrer">📺 {m.stream.name}</a>
                    {/if}
                  </span>
                </div>
              {/if}
            {/each}
          </div>
        </div>
      {/if}
    {/each}
  </WidgetFrame>
{/if}
