<script lang="ts">
  // CS2 / Leetify — the leetify-stats runner's report, rendered as dimension chips,
  // a per-map table, AI coaching notes, the HLTV VRS watchlist, and a collapsible
  // round-by-round deep dive per parsed demo.
  import { createQuery } from '@tanstack/svelte-query';
  import { get, ApiError } from '$lib/api/client';
  import Markdown from '$lib/components/Markdown.svelte';
  import { localeDateTime } from '$lib/format';
  import DeepDive from './_parts/DeepDive.svelte';

  interface MapRow {
    map: string; matches: number; win_rate: number;
    avg_rating?: number; ct_rating?: number; t_rating?: number;
  }
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
  interface LeetifyReport {
    run_at?: string;
    summary?: string;
    dimensions?: Record<string, number>;
    maps?: MapRow[];
    demo_summaries?: DemoSummary[];
    coaching?: string;
    log?: string;
  }

  const q = createQuery(() => ({
    queryKey: ['leetify'],
    queryFn: () => get<LeetifyReport>('/api/runners/leetify-latest', 15_000),
    retry: 0,
  }));

  let dims = $derived(Object.entries(q.data?.dimensions ?? {}));
  let demos = $derived(q.data?.demo_summaries ?? []);
  let deepDives = $derived(demos.filter((ds) => (ds.rounds ?? []).length > 0));

  function verdictFor(m: MapRow): string {
    if (m.matches < 2) return 'low sample';
    if (m.win_rate >= 55 && (m.avg_rating ?? 0) >= 0) return 'strong';
    if (m.win_rate <= 40 || (m.avg_rating ?? 0) < -0.03) return 'avoid / practice';
    return 'even';
  }
</script>

{#if q.isError}
  {@const err = q.error as ApiError}
  <div class="glass card">
    {#if err.status === 500}
      <p>Leetify report is corrupt and could not be read.</p>
      <p class="t-dim">{err.message}</p>
      <p class="t-dim">Re-run the agent on opti to regenerate it.</p>
    {:else}
      <p>No Leetify report yet.</p>
      <p class="t-dim">Set LEETIFY_API_KEY + STEAM64_ID on opti and run the agent.</p>
    {/if}
  </div>
{:else if q.isLoading || !q.data}
  <div class="spin"></div>
{:else}
  {@const d = q.data}
  <div class="leetify-page">
    <section class="glass card">
      <div class="w-head">
        <span class="w-title">Overview</span>
        <span class="w-meta">{d.run_at ? localeDateTime(d.run_at) : ''}</span>
      </div>
      {#if d.summary}<p class="report-summary">{d.summary}</p>{/if}
      {#if dims.length > 0}
        <div class="dim-strip">
          {#each dims as [k, v] (k)}
            <div class="dim" data-s={v >= 60 ? 'strong' : v < 52 ? 'focus' : 'ok'}>
              <span class="dim-name">{k}</span>
              <span class="dim-val">{Math.round(v)}</span>
            </div>
          {/each}
        </div>
      {/if}
    </section>

    {#if (d.maps?.length ?? 0) > 0}
      <section class="glass card">
        <div class="w-head"><span class="w-title">Maps</span></div>
        <table class="detail-table">
          <thead>
            <tr><th>Map</th><th>Matches</th><th>Win rate</th><th>CT</th><th>T</th><th>Verdict</th></tr>
          </thead>
          <tbody>
            {#each d.maps ?? [] as m (m.map)}
              <tr>
                <td>{m.map}</td>
                <td>{m.matches}</td>
                <td>{m.win_rate}%</td>
                <td>{(m.ct_rating ?? 0).toFixed(3)}</td>
                <td>{(m.t_rating ?? 0).toFixed(3)}</td>
                <td>{verdictFor(m)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}

    {#if d.coaching}
      <section class="glass card">
        <div class="w-head"><span class="w-title">Coaching</span></div>
        <Markdown source={d.coaching} />
      </section>
    {/if}

    {#if demos.length > 0}
      <section class="glass card">
        <div class="w-head"><span class="w-title">Recent demos</span></div>
        <div class="demo-grid">
          {#each demos as ds, i (i)}
            <div class="demo-card glass">
              <div class="demo-head">
                <span class="demo-map">{ds.map}</span>
                <span class="t-dim">{ds.date}</span>
                <span class="demo-result" data-s={ds.result}>{ds.result}{ds.score ? ` ${ds.score}` : ''}</span>
              </div>
              <div class="t-dim">
                {ds.kills != null && ds.deaths != null ? `${ds.kills}/${ds.deaths} K/D` : ''}
                {ds.rating != null ? ` · ${ds.rating > 0 ? '+' : ''}${ds.rating.toFixed(3)} rating` : ''}
                {ds.hs_pct != null ? ` · ${ds.hs_pct}% HS` : ''}
              </div>
              {#if (ds.hotspots?.length ?? 0) > 0}
                <table class="detail-table">
                  <thead><tr><th>Died at</th><th>Side</th><th>×</th><th>%</th></tr></thead>
                  <tbody>
                    {#each ds.hotspots ?? [] as h, j (j)}
                      <tr><td>{h.area}</td><td>{h.side}</td><td>{h.count}</td><td>{h.pct}%</td></tr>
                    {/each}
                  </tbody>
                </table>
              {/if}
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if deepDives.length > 0}
      <section class="glass card">
        <div class="w-head"><span class="w-title">Match deep-dive — round by round</span></div>
        {#each deepDives as ds, i (i)}
          <DeepDive demo={ds} />
        {/each}
      </section>
    {/if}

    {#if d.log}
      <section class="glass card">
        <div class="w-head"><span class="w-title">Full report</span></div>
        <Markdown source={d.log} />
      </section>
    {/if}
  </div>
{/if}
