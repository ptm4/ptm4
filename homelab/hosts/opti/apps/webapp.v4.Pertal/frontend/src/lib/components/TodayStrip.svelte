<script lang="ts">
  // "Today" on the Status page: weather, calendar, CS2, NBA. Each card reads its own
  // snapshot, shows its own age, and fails on its own — a dead feed greys one card.
  import {
    Sun, Moon, Cloud, CloudSun, CloudDrizzle, CloudRain, CloudSnow, CloudLightning, CloudFog,
    CalendarDays, Crosshair, Trophy,
  } from '@lucide/svelte';
  import Age from './Age.svelte';
  import { live } from '$lib/live.svelte';
  import { clock } from '$lib/format';

  type Card<T> = { data: T | null; ok: boolean | null; error: string | null; fetched_at: string | null; stale: boolean } | null;
  let extras = $state<{ weather: Card<any>; nba: Card<any>; cs2: Card<any>; calendar: Card<any> } | null>(null);

  async function load() {
    try {
      const res = await fetch('/api/extras', { signal: AbortSignal.timeout(8000) });
      if (res.ok) extras = await res.json();
    } catch { /* the cards keep their last data and their ages keep ticking */ }
  }
  // Refetch whenever an extras snapshot changes (the live store sees every meta).
  const stamp = $derived(Object.values(live.snapshots).filter((m) => m.key.startsWith('extras:')).map((m) => m.fetched_at).join());
  $effect(() => { void stamp; void load(); });

  const wIcon = (code: number, day: boolean) =>
    code === 0 || code === 1 ? (day ? Sun : Moon)
    : code === 2 ? CloudSun
    : code === 3 ? Cloud
    : code === 45 || code === 48 ? CloudFog
    : code >= 51 && code <= 57 ? CloudDrizzle
    : (code >= 61 && code <= 67) || (code >= 80 && code <= 82) ? CloudRain
    : (code >= 71 && code <= 77) || code === 85 || code === 86 ? CloudSnow
    : code >= 95 ? CloudLightning : Cloud;
  const hour = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric' });
  const dayLabel = (iso: string) => {
    const d = new Date(iso), t = new Date();
    const tomorrow = new Date(t); tomorrow.setDate(t.getDate() + 1);
    return d.toDateString() === t.toDateString() ? 'Today' : d.toDateString() === tomorrow.toDateString() ? 'Tomorrow' : d.toLocaleDateString([], { weekday: 'short' });
  };
  const time = (e: any) => (e.all_day ? 'all day' : new Date(e.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }));
</script>

<section class="today">
  <!-- Weather -->
  <div class="panel card">
    {#if extras?.weather?.data}
      {@const w = extras.weather.data}
      {@const Icon = wIcon(w.now.code, w.now.is_day)}
      <div class="top">
        <Icon size={30} />
        <div class="big">{w.now.temp}°</div>
        <div class="sub">
          <div>{w.now.text}</div>
          <div class="faint">feels {w.now.feels}° · wind {w.now.wind_mph} mph</div>
        </div>
      </div>
      <div class="line faint">Today {w.today.hi}° / {w.today.lo}° · rain {w.today.rain_pct}% · tomorrow {w.tomorrow.hi}° {w.tomorrow.text.toLowerCase()}</div>
      <div class="hours">
        {#each w.hours.slice(1, 7) as h (h.time)}
          {@const HI = wIcon(h.code, true)}
          <div class="hr"><span class="faint">{hour(h.time)}</span><HI size={14} /><span class="num">{h.temp}°</span>{#if h.rain_pct >= 30}<span class="rain">{h.rain_pct}%</span>{/if}</div>
        {/each}
      </div>
      <div class="foot faint"><span>{w.location}</span><Age at={extras.weather.fetched_at} staleAfterMs={3600_000} /></div>
    {:else}
      <div class="title faint">Weather</div><div class="empty">{extras?.weather?.error ?? 'Loading…'}</div>
    {/if}
  </div>

  <!-- Calendar -->
  <div class="panel card">
    <div class="title"><CalendarDays size={15} /> Calendar</div>
    {#if !extras || extras.calendar === null}
      <div class="empty small">Not connected. Set <code>PERTAL_CALENDAR_ICS</code> on opti to your Google Calendar's secret iCal address.</div>
    {:else if extras.calendar?.data}
      <div class="list">
        {#each extras.calendar.data.events.slice(0, 6) as e (e.start + e.title)}
          <div class="ev"><span class="when faint">{dayLabel(e.start)} {time(e)}</span><span class="what">{e.title}</span></div>
        {:else}
          <div class="faint small">Nothing in the next three days.</div>
        {/each}
      </div>
      <div class="foot faint"><span></span><Age at={extras.calendar.fetched_at} staleAfterMs={3600_000} /></div>
    {:else}
      <div class="empty small">{extras.calendar?.error}</div>
    {/if}
  </div>

  <!-- CS2 -->
  <div class="panel card">
    <div class="title"><Crosshair size={15} /> CS2 today</div>
    {#if extras?.cs2?.data}
      <div class="list">
        {#each extras.cs2.data.matches.slice(0, 5) as m (m.id)}
          <a class="match" href={m.url} target="_blank" rel="noreferrer">
            {#if m.status === 'live'}<span class="badge crit">live</span>{:else if m.status === 'finished'}<span class="faint st">done</span>{:else}<span class="faint st">{m.start ? clock(m.start) : ''}</span>{/if}
            <span class="teams"><b class:win={m.score1 > m.score2}>{m.team1}</b>{#if m.score1 != null} <span class="num">{m.score1}–{m.score2}</span> {:else} vs {/if}<b class:win={m.score2 > m.score1}>{m.team2}</b></span>
          </a>
        {:else}
          <div class="faint small">No starred matches today.</div>
        {/each}
      </div>
      <div class="foot faint"><span>{extras.cs2.data.total} matches on hltv.org</span><Age at={extras.cs2.fetched_at} staleAfterMs={30 * 60_000} /></div>
    {:else}
      <div class="empty small">{extras?.cs2?.error ? `hltv-api: ${extras.cs2.error}` : 'Loading…'}</div>
    {/if}
  </div>

  <!-- NBA -->
  <div class="panel card">
    <div class="title"><Trophy size={15} /> NBA</div>
    {#if extras?.nba?.data}
      {@const n = extras.nba.data}
      <div class="list">
        {#each n.games.slice(0, 4) as g (g.id)}
          <div class="game" class:mine={g.mine}>
            <span class="teams"><b class:win={g.away.winner}>{g.away.abbrev}</b> {#if g.state !== 'pre'}<span class="num">{g.away.score}–{g.home.score}</span>{:else}@{/if} <b class:win={g.home.winner}>{g.home.abbrev}</b></span>
            <span class="faint st">{g.state === 'pre' ? clock(g.start) : g.detail}</span>
          </div>
        {:else}
          <div class="faint small">No games today.</div>
        {/each}
      </div>
      {#if n.next}<div class="line faint">Next: {n.next.name} · {clock(n.next.start)}</div>{/if}
      <div class="foot faint"><span>{n.teams.join(', ')}</span><Age at={extras.nba.fetched_at} staleAfterMs={20 * 60_000} /></div>
    {:else}
      <div class="empty small">{extras?.nba?.error ?? 'Loading…'}</div>
    {/if}
  </div>
</section>

<style>
  .today { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: var(--s3); margin-bottom: var(--s4); }
  .card { display: flex; flex-direction: column; gap: 8px; padding: var(--s3) var(--s4); min-height: 150px; }
  .title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: var(--fs-sm); color: var(--ink-2); }
  .top { display: flex; align-items: center; gap: 10px; color: var(--ink); }
  .big { font-size: 32px; font-weight: 600; line-height: 1; font-variant-numeric: tabular-nums; }
  .sub { font-size: var(--fs-sm); }
  .line { font-size: var(--fs-xs); }
  .hours { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
  .hr { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: var(--fs-xs); color: var(--ink-2); white-space: nowrap; }
  .rain { color: var(--accent); }
  .list { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-sm); }
  .ev, .game, .match { display: flex; justify-content: space-between; gap: 8px; }
  .ev .when, .st { flex: none; font-size: var(--fs-xs); min-width: 58px; }
  .ev .what { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
  .match { color: var(--ink); text-decoration: none; justify-content: flex-start; align-items: center; }
  .match:hover { text-decoration: none; color: var(--accent); }
  .teams { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .teams b { font-weight: 500; color: var(--ink-2); }
  .teams b.win { color: var(--ink); font-weight: 700; }
  .game.mine .teams b { color: var(--brand); }
  .foot { margin-top: auto; display: flex; justify-content: space-between; gap: 8px; font-size: var(--fs-xs); }
  .empty { padding: var(--s3) 0; text-align: left; }
  .small { font-size: var(--fs-xs); }
  code { font: var(--fs-xs) var(--mono); background: var(--surface-2); padding: 0 4px; border-radius: 3px; }
</style>
