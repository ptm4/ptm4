<script lang="ts">
  // Streams — the phone page. Player on top, the four slots as pills, and beside
  // (below, on a phone) the guide: what HLTV says is on today, joined with the Valve
  // Regional Standings, plus the channel directory, favourites and recents.
  //
  // The guide states evidence and nothing more (see backend/routes/streams.js):
  // real VRS ranks rather than an invented tier, a Watch button only where HLTV
  // actually supplied a broadcast link, and "unknown" instead of "live" once the feed
  // is too old to speak for the present.
  import { onMount } from 'svelte';
  import { Square, Grid2x2, Tv, Radio, Search, ExternalLink, Star, RefreshCw, Clock } from '@lucide/svelte';
  import Player from '$lib/features/streams/Player.svelte';
  import {
    useStationStatus, useGuide, useStreamActions, watchUrl,
    type Slot, type GuideMatch, type GuideChannel, type WatchTarget,
  } from '$lib/api/streams';
  import { streamPrefs, channelKey } from '$lib/stores/stream-prefs.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { relTime } from '$lib/format';

  const status = useStationStatus(() => true);
  const guide = useGuide();
  const { watch, stop, keepalive } = useStreamActions();

  let current = $state(1);
  let multiview = $state(false);
  let theater = $state(false);
  let reload = $state(0);
  let tab = $state<'guide' | 'channels' | 'recent' | 'custom'>('guide');
  let search = $state('');
  let priority = $state<'priority' | 'top20' | 'premier' | 'all'>('priority');
  let matchStatus = $state<'all' | 'live' | 'upcoming' | 'finished'>('all');
  let group = $state('all');
  let customPlatform = $state('twitch');
  let customChannel = $state('');
  let customUrl = $state('');

  let slots = $derived<Slot[]>(status.data?.slots ?? guide.data?.station.slots ?? [1, 2, 3, 4].map((n) => ({ slot: n, state: 'idle' } as Slot)));
  let liveSlots = $derived(slots.filter((s) => s.state === 'starting' || s.state === 'running'));
  let cur = $derived(slots.find((s) => s.slot === current) ?? null);
  let stationOk = $derived(!!status.data || !!guide.data?.station.ok);

  // Follow a newly started slot, and keep the running ones alive while this page is open.
  $effect(() => {
    if (!liveSlots.some((s) => s.slot === current) && liveSlots.length) current = liveSlots[0].slot;
  });
  onMount(() => {
    const t = setInterval(() => { if (document.visibilityState === 'visible' && liveSlots.length) keepalive(liveSlots.map((s) => s.slot)); }, 5000);
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el?.tagName === 'INPUT' || el?.tagName === 'SELECT' || el?.tagName === 'TEXTAREA') return;
      if (e.key === '/') { e.preventDefault(); document.getElementById('stream-search')?.focus(); }
      if (e.key === 't') theater = !theater;
      if (e.key === 'Escape') theater = false;
      if (e.key === 'm') multiview = !multiview;
      if (/^[1-4]$/.test(e.key)) current = Number(e.key);
    };
    window.addEventListener('keydown', onKey);
    return () => { clearInterval(t); window.removeEventListener('keydown', onKey); };
  });

  async function start(target: WatchTarget, label: string, remember?: { platform: string; channel: string; label: string }) {
    try {
      const req = target.type === 'channel'
        ? { platform: target.platform, channel: target.channel }
        : { url: target.url };
      const r = await watch.mutateAsync({ ...req, quality: streamPrefs.quality || undefined, profile: streamPrefs.profile });
      current = r.slot;
      if (remember) streamPrefs.remember(remember);
      toast(r.reused ? `Already on slot ${r.slot}` : `Starting ${label} in slot ${r.slot}…`, 'ok', { ttlMs: 2500 });
    } catch (e) {
      toast(`Could not start: ${(e as Error).message}`, 'crit', { ttlMs: 8000 });
    }
  }
  const startChannel = (c: { platform: string; channel: string; label: string }) =>
    start({ type: 'channel', platform: c.platform, channel: c.channel }, c.label, c);

  async function doStop(slot: number) {
    try { await stop.mutateAsync(slot); toast(`Slot ${slot} stopped`, 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Stop failed: ${(e as Error).message}`, 'crit'); }
  }

  // ── guide filtering ────────────────────────────────────────────────────────
  let matches = $derived((guide.data?.matches ?? []).filter((m) => {
    const pri = priority === 'all' ? true
      : priority === 'top20' ? m.top20
      : priority === 'premier' ? m.premier || m.tier === 'S'
      : m.top20 || m.premier || m.tier === 'S';
    const st = matchStatus === 'all' ? true
      // "unknown" is a live match we can no longer vouch for — keep it under Live.
      : matchStatus === 'live' ? m.status === 'live' || m.status === 'unknown'
      : m.status === matchStatus;
    const q = search.trim().toLowerCase();
    const hit = !q || `${m.team1 ?? ''} ${m.team2 ?? ''} ${m.event ?? ''}`.toLowerCase().includes(q);
    return pri && st && hit;
  }));
  let liveMatches = $derived(matches.filter((m) => m.status === 'live' || m.status === 'unknown'));
  let upcoming = $derived(matches.filter((m) => m.status === 'upcoming'));
  let finished = $derived(matches.filter((m) => m.status === 'finished'));
  let hiddenCount = $derived((guide.data?.matches?.length ?? 0) - matches.length);

  let channels = $derived((guide.data?.channels ?? []).filter((c) => {
    const q = search.trim().toLowerCase();
    const inGroup = group === 'all' ? true : group === 'favorites' ? streamPrefs.isFavorite(c) : c.group_label === group;
    return inGroup && (!q || `${c.label} ${c.channel} ${c.org ?? ''}`.toLowerCase().includes(q));
  }));
  let groupNames = $derived([...new Set((guide.data?.channels ?? []).map((c) => c.group_label))]);
  let recent = $derived(streamPrefs.recent.filter((c) => {
    const q = search.trim().toLowerCase();
    return !q || `${c.label} ${c.channel}`.toLowerCase().includes(q);
  }));

  const clock = (u?: number) => (u ? new Date(u * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
  const slotName = (s: Slot) => s.channel ?? (s.url ? s.url.replace(/^https?:\/\//, '').slice(0, 24) : `slot ${s.slot}`);
  const rankLabel = (r: number | null) => (r == null ? 'Unranked / unknown' : `VRS #${r}`);
</script>

<div class="streams" class:theater>
  <section class="stage">
    <div class="players" class:multi={multiview}>
      {#if multiview}
        {#each slots as s (s.slot)}
          <Player slot={s.slot} live={s.state === 'starting' || s.state === 'running'} muted={s.slot !== current} active={s.slot === current} label={slotName(s)} {reload} onclick={() => (current = s.slot)} />
        {/each}
      {:else if cur}
        <Player slot={cur.slot} live={cur.state === 'starting' || cur.state === 'running'} active label={slotName(cur)} {reload} />
      {/if}
    </div>

    <div class="slotbar">
      {#each slots as s (s.slot)}
        <button class="slotpill" class:on={s.slot === current} data-s={s.state} onclick={() => (current = s.slot)} title={s.error ?? s.state}>
          <span class="dot"></span>
          <span class="n">{s.slot}</span>
          <span class="name">{s.state === 'idle' ? 'idle' : slotName(s)}</span>
        </button>
      {/each}
      <span class="spacer"></span>
      <button class="tbtn icon" title="Reload player" onclick={() => (reload += 1)}><RefreshCw /></button>
      <button class="tbtn icon" class:on={multiview} title="Multiview (m)" onclick={() => (multiview = !multiview)}><Grid2x2 /></button>
      <button class="tbtn icon" class:on={theater} title="Theater (t)" onclick={() => (theater = !theater)}><Tv /></button>
      {#if cur && (cur.state === 'running' || cur.state === 'starting')}
        <button class="tbtn danger" disabled={stop.isPending} onclick={() => doStop(cur!.slot)}><Square /> Stop {cur.slot}</button>
      {/if}
    </div>

    <div class="statusline">
      {#if !stationOk && status.isError}
        <span class="t-crit">stream station unreachable — {(status.error as Error)?.message}</span>
      {:else if cur && cur.state !== 'idle'}
        <span class="chip" data-s={cur.state === 'running' ? 'ok' : cur.state === 'starting' ? 'warn' : 'crit'}>{cur.state}</span>
        <span class="mono">{cur.platform ? `${cur.platform}/` : ''}{slotName(cur)}</span>
        {#if cur.uptime_s != null}<span class="faint">· up {Math.floor(cur.uptime_s / 60)}m</span>{/if}
        {#if cur.quality}<span class="faint">· {cur.quality.split(',')[0]}</span>{/if}
        {#if cur.profile}<span class="faint">· {cur.profile}</span>{/if}
        {#if cur.state === 'running' && (cur.last_segment_age_s ?? 0) > 20}<span class="t-warn">· source stalled {Math.round(cur.last_segment_age_s!)}s (ad break?)</span>{/if}
        {#if cur.error}<span class="t-crit">· {cur.error}</span>{/if}
        {#if cur.platform && cur.channel}<a class="faint" href={watchUrl(cur.platform, cur.channel)} target="_blank" rel="noreferrer">open on {cur.platform} <ExternalLink size={10} /></a>{/if}
      {:else}
        <span class="faint">Pick a match or channel — the station starts it in a free slot. Keys: 1–4 slots · m multiview · t theater · / search.</span>
      {/if}
    </div>

    <div class="opts">
      <label>Quality
        <select class="input" value={streamPrefs.quality} onchange={(e) => streamPrefs.setQuality(e.currentTarget.value)}>
          <option value="">Best available</option>
          <option value="1080p60,1080p,best">1080p</option>
          <option value="720p60,720p,best">720p · balanced</option>
          <option value="480p,worst">480p · save data</option>
          <option value="worst">Lowest bandwidth</option>
        </select>
      </label>
      <label>Latency
        <select class="input" value={streamPrefs.profile} onchange={(e) => streamPrefs.setProfile(e.currentTarget.value)}>
          <option value="low-latency">Low (~6-10s)</option>
          <option value="smooth">Smooth (~15-20s)</option>
        </select>
      </label>
      {#if streamPrefs.unavailable}<span class="faint">Browser storage unavailable — preferences reset on close.</span>{/if}
    </div>
  </section>

  <section class="side">
    <div class="tabs">
      <button class:on={tab === 'guide'} onclick={() => (tab = 'guide')}><Radio size={13} /> Guide {#if liveMatches.length}<span class="cnt">{liveMatches.length}</span>{/if}</button>
      <button class:on={tab === 'channels'} onclick={() => (tab = 'channels')}><Tv size={13} /> Channels</button>
      <button class:on={tab === 'recent'} onclick={() => (tab = 'recent')}><Clock size={13} /> Recent</button>
      <button class:on={tab === 'custom'} onclick={() => (tab = 'custom')}>Custom</button>
    </div>

    {#if tab !== 'custom'}
      <label class="search">
        <Search size={13} />
        <input id="stream-search" class="input" placeholder={tab === 'guide' ? 'Team, tournament or event…' : 'Find a channel…'} bind:value={search} />
      </label>
    {/if}

    {#if tab === 'guide'}
      <div class="filters">
        <select class="input" bind:value={priority} aria-label="Match priority">
          <option value="priority">Top 20 + premier events</option>
          <option value="top20">VRS top 20 teams</option>
          <option value="premier">Premier event series</option>
          <option value="all">All matches in the feed</option>
        </select>
        <select class="input" bind:value={matchStatus} aria-label="Match status">
          <option value="all">All statuses</option>
          <option value="live">Live</option>
          <option value="upcoming">Upcoming</option>
          <option value="finished">Results</option>
        </select>
      </div>

      {#if guide.isLoading}<div class="spin"></div>{/if}
      {#if guide.isError}
        <div class="card"><p class="err">Guide unavailable — {(guide.error as Error).message}</p></div>
      {:else if guide.data && !guide.data.hltv.ok}
        <div class="card"><p class="dim" style="margin:0">HLTV feed unavailable ({guide.data.hltv.error}) — the channel directory still works.</p></div>
      {:else if guide.data}
        <div class="feedline faint">
          <a href="https://www.hltv.org/matches" target="_blank" rel="noreferrer">HLTV feed <ExternalLink size={9} /></a>
          <span>{guide.data.hltv.date ?? ''}{guide.data.hltv.fetched_at ? ` · ${relTime(new Date(guide.data.hltv.fetched_at * 1000).toISOString())}` : ''}</span>
          {#if guide.data.hltv.stale}<span class="chip" data-s="warn">STALE</span>{/if}
        </div>
        {#if !guide.data.vrs.known}
          <p class="warnline">Rankings unavailable{guide.data.vrs.error ? ` (${guide.data.vrs.error})` : ''} — top-20 status is unknown for every match below.</p>
        {/if}
      {/if}

      {#if liveMatches.length}
        <div class="divider">{matchStatus === 'live' ? 'Live' : 'Live now'}</div>
        {#each liveMatches as m (m.id ?? m.url)}{@render matchRow(m)}{/each}
      {/if}
      {#if upcoming.length}
        <div class="divider">Upcoming</div>
        {#each upcoming.slice(0, 20) as m (m.id ?? m.url)}{@render matchRow(m)}{/each}
      {/if}
      {#if finished.length}
        <div class="divider">Results</div>
        {#each finished.slice(0, 20) as m (m.id ?? m.url)}{@render matchRow(m)}{/each}
      {/if}
      {#if guide.data && matches.length === 0}
        <p class="empty">{guide.data.matches.length ? 'No matches match these filters.' : 'No matches in the feed for today.'}</p>
      {/if}
      {#if hiddenCount > 0}
        <button class="linkish" onclick={() => { priority = 'all'; matchStatus = 'all'; }}>Show {hiddenCount} more the filters hide</button>
      {/if}

      {#if guide.data}
        <details class="provenance">
          <summary>Rankings, event labels &amp; coverage</summary>
          <p>Ranks are {guide.data.vrs.system}{guide.data.vrs.as_of ? `, as of ${guide.data.vrs.as_of}` : ''}{guide.data.vrs.counted ? ` (${guide.data.vrs.counted} teams listed)` : ''}. A team with no rank shown is simply not in that list.</p>
          <p><b>HLTV stars are a match rating, not a tournament tier</b> — so no tier is invented here. “Premier series” reads the event name (Major, IEM, BLAST, PGL, FISSURE, ESL Pro League, excluding qualifiers) and is a label, not a ruling. “S-tier” appears only when the feed says so itself.</p>
          <p>{guide.data.coverage} Only a broadcast HLTV attached to the match becomes a Watch button; directory channels are never assumed to be live.</p>
          {#if guide.data.hltv.stale}<p class="t-warn">This feed is stale, so matches it called live are shown as “unknown” rather than live.</p>{/if}
          <small>Feed retrieved {guide.data.hltv.fetched_at ? relTime(new Date(guide.data.hltv.fetched_at * 1000).toISOString()) : 'unknown'}.</small>
        </details>
      {/if}

    {:else if tab === 'channels'}
      <div class="filters">
        <select class="input" bind:value={group} aria-label="Channel group">
          <option value="all">All channels · {guide.data?.channels.length ?? 0}</option>
          <option value="favorites">Favourites</option>
          {#each groupNames as g (g)}<option value={g}>{g}</option>{/each}
        </select>
        <span class="faint">directory · live status not checked</span>
      </div>
      {#each groupNames.filter((g) => channels.some((c) => c.group_label === g)) as g (g)}
        <div class="divider">{g}</div>
        <div class="chips">
          {#each channels.filter((c) => c.group_label === g) as c (channelKey(c))}{@render channelChip(c)}{/each}
        </div>
      {/each}
      {#if guide.data && channels.length === 0}<p class="empty">No channels match.</p>{/if}
      {#if guide.isError}<p class="err">Directory unavailable — {(guide.error as Error).message}</p>{/if}

    {:else if tab === 'recent'}
      {#if recent.length === 0}
        <p class="empty">Channels you start will appear here.</p>
      {:else}
        <div class="chips">
          {#each recent as c (channelKey(c))}
            <button class="chchip solo" disabled={watch.isPending} onclick={() => startChannel(c)}>
              <span class="dot"></span>{c.label}<span class="tag">{c.platform}</span>
            </button>
          {/each}
        </div>
      {/if}

    {:else}
      <form class="custom" onsubmit={(e) => { e.preventDefault(); const c = customChannel.trim(); if (c) start({ type: 'channel', platform: customPlatform, channel: c }, c, { platform: customPlatform, channel: c, label: c }); }}>
        <div class="row2">
          <select class="input" bind:value={customPlatform}><option value="twitch">twitch</option><option value="youtube">youtube</option><option value="kick">kick</option></select>
          <input class="input" placeholder="channel name" bind:value={customChannel} />
          <button class="tbtn primary" type="submit" disabled={watch.isPending || !customChannel.trim()}>Watch</button>
        </div>
      </form>
      <form class="custom" onsubmit={(e) => { e.preventDefault(); const u = customUrl.trim(); if (u) start({ type: 'url', url: u }, 'URL'); }}>
        <div class="row2">
          <input class="input" placeholder="https://… (any stream URL VLC can open)" bind:value={customUrl} />
          <button class="tbtn" type="submit" disabled={watch.isPending || !customUrl.trim()}>Start URL</button>
        </div>
      </form>
      <p class="faint" style="font-size: 11.5px">Channel names go through streamlink (Twitch ad-bypass, low latency); URLs go straight to VLC and are remuxed, never transcoded.</p>
    {/if}
  </section>
</div>

{#snippet matchRow(m: GuideMatch)}
  <div class="match" data-status={m.status}>
    <div class="mhead">
      <span class="ev">{m.event}</span>
      {#if m.premier}<span class="chip" data-s="info" title="The event name reads as a premier series — a label, not an official tier">PREMIER</span>{/if}
      {#if m.tier === 'S'}<span class="chip" data-s="crit" title="HLTV's feed supplied this tier">S-TIER</span>{/if}
      {#if m.top20}<span class="chip" data-s="warn" title="A Valve Regional Standings top-20 team is playing">TOP 20</span>{/if}
      <span class="st" data-s={m.status}>
        {#if m.status === 'live'}LIVE{:else if m.status === 'unknown'}UNKNOWN{:else if m.status === 'finished'}final{:else}{clock(m.start_unix)}{/if}
      </span>
    </div>
    <div class="teams">
      <span class="team"><b>{m.team1 ?? '?'}</b><small>{rankLabel(m.rank1)}</small></span>
      <span class="vs mono">{m.score1 != null && m.score2 != null ? `${m.score1} : ${m.score2}` : 'vs'}</span>
      <span class="team right"><b>{m.team2 ?? '?'}</b><small>{rankLabel(m.rank2)}</small></span>
    </div>
    {#if m.maps?.length}
      <div class="maps faint">{#each m.maps as mp, i (i)}<span>{mp.name} <b class="mono">{mp.s1}:{mp.s2}</b></span>{/each}</div>
    {/if}
    <div class="mfoot">
      <span class="faint">{m.bo ?? 'format unknown'}{m.stars ? ` · ${'★'.repeat(m.stars)}` : ''}</span>
      <span class="spacer"></span>
      {#if m.status !== 'finished' && m.watch}
        {#if m.watching_slot}
          <button class="tbtn sm" onclick={() => (current = m.watching_slot!)}>slot {m.watching_slot}</button>
        {:else}
          <button class="tbtn sm primary" disabled={watch.isPending}
            onclick={() => start(m.watch!, m.channel?.label ?? m.stream_source ?? 'match', m.channel ? { ...m.channel } : undefined)}>
            ▶ {m.channel?.label ?? m.stream_source ?? 'Watch'}
          </button>
        {/if}
      {:else if m.status !== 'finished'}
        <span class="faint nostream">no broadcast listed</span>
      {/if}
      {#if m.stream?.url}<a class="tbtn sm" href={m.stream.url} target="_blank" rel="noreferrer" title="Open the broadcast directly"><ExternalLink size={11} /></a>{/if}
      {#if m.url}<a class="tbtn sm" href={m.url} target="_blank" rel="noreferrer" title="Open on HLTV">HLTV</a>{/if}
    </div>
  </div>
{/snippet}

{#snippet channelChip(c: GuideChannel)}
  <span class="chwrap">
    <button class="chchip" class:watching={c.watching_slot != null} disabled={watch.isPending}
      title="{c.platform}/{c.channel}{c.org ? ` · ${c.org}` : ''}{c.listed_matches ? ` · ${c.listed_matches} of today's matches list this channel` : ''}"
      onclick={() => (c.watching_slot != null ? (current = c.watching_slot) : startChannel(c))}>
      <span class="dot"></span>{c.label}
      {#if c.watching_slot != null}<span class="tag on">slot {c.watching_slot}</span>
      {:else if c.listed_matches}<span class="tag">{c.listed_matches} listed</span>{/if}
    </button>
    <button class="fav" class:on={streamPrefs.isFavorite(c)} title="Favourite" onclick={() => streamPrefs.toggleFavorite(c)}>
      <Star size={12} fill={streamPrefs.isFavorite(c) ? 'currentColor' : 'none'} />
    </button>
    <a class="fav last" href={watchUrl(c.platform, c.channel)} target="_blank" rel="noreferrer" title="Open on {c.platform}"><ExternalLink size={11} /></a>
  </span>
{/snippet}

<style>
  .streams { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: start; }
  .stage { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .players { display: grid; gap: 6px; }
  .players.multi { grid-template-columns: 1fr 1fr; }
  .slotbar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .slotpill { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--border); background: var(--surface); color: var(--ink-2); border-radius: 99px; padding: 5px 11px 5px 8px; font: inherit; font-size: 12.5px; cursor: pointer; max-width: 200px; }
  .slotpill.on { border-color: var(--accent-muted); color: var(--ink); background: var(--accent-dim); }
  .slotpill .dot { width: 7px; height: 7px; border-radius: 99px; background: var(--ink-3); flex: none; }
  .slotpill[data-s="running"] .dot { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .slotpill[data-s="starting"] .dot { background: var(--warn); animation: beat 1s ease infinite; }
  .slotpill[data-s="ended"] .dot { background: var(--crit); }
  .slotpill .n { font: 600 11px var(--mono); }
  .slotpill .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tbtn.on { color: var(--accent); border-color: var(--accent-muted); }
  .statusline { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: 12.5px; color: var(--ink-2); min-height: 20px; }
  .statusline a { display: inline-flex; align-items: center; gap: 3px; }
  @keyframes beat { 50% { opacity: .3; } }
  .opts { display: flex; gap: 10px; font-size: 11.5px; color: var(--ink-3); flex-wrap: wrap; align-items: center; }
  .opts label { display: flex; align-items: center; gap: 6px; }
  .opts .input { font-size: 12px; padding: 3px 6px; }

  .side { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .tabs { display: flex; gap: 2px; padding: 2px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); }
  .tabs button { flex: 1; border: 0; background: none; color: var(--ink-2); font: inherit; font-size: 12.5px; padding: 6px 6px; border-radius: var(--r-sm); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 5px; }
  .tabs button.on { background: var(--accent-dim); color: var(--accent); font-weight: 600; }
  .tabs .cnt { font: 600 10px var(--mono); color: var(--crit); }
  .search { display: flex; align-items: center; gap: 6px; color: var(--ink-3); }
  .search .input { flex: 1; }
  .filters { display: flex; gap: 6px; align-items: center; font-size: 11.5px; color: var(--ink-3); }
  .filters .input { flex: 1; min-width: 0; font-size: 12px; padding: 3px 6px; }
  .feedline { display: flex; gap: 8px; align-items: center; font-size: 11px; flex-wrap: wrap; }
  .warnline { color: var(--warn); font-size: 11.5px; margin: 0; }

  .match { display: flex; flex-direction: column; gap: 5px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); }
  .match[data-status="live"] { border-color: var(--crit-dim); box-shadow: inset 0 0 0 1px var(--crit-dim); }
  .mhead { display: flex; gap: 6px; align-items: center; font-size: 11px; min-width: 0; }
  .mhead .ev { color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
  .mhead .st { font: 600 10.5px var(--mono); color: var(--ink-3); letter-spacing: .06em; }
  .mhead .st[data-s="live"] { color: var(--crit); }
  .mhead .st[data-s="unknown"] { color: var(--warn); }
  .teams { display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: center; }
  .team { display: flex; flex-direction: column; min-width: 0; }
  .team b { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .team small { font-size: 10px; color: var(--ink-3); }
  .team.right { text-align: right; }
  .vs { font-size: 12px; color: var(--ink-2); font-weight: 600; }
  .maps { display: flex; gap: 8px; flex-wrap: wrap; font-size: 10.5px; }
  .mfoot { display: flex; gap: 6px; align-items: center; font-size: 11px; flex-wrap: wrap; }
  .nostream { font-style: italic; }
  .linkish { background: none; border: 0; color: var(--accent); font: inherit; font-size: 11.5px; cursor: pointer; padding: 2px 0; text-align: left; }

  .chwrap { display: inline-flex; align-items: center; }
  .chchip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); border-right: 0; background: var(--surface); color: var(--ink-2); border-radius: 99px 0 0 99px; padding: 5px 8px 5px 9px; font: inherit; font-size: 12.5px; cursor: pointer; }
  .chchip.solo { border-right: 1px solid var(--border); border-radius: 99px; }
  .chchip:hover { color: var(--ink); border-color: var(--accent-muted); }
  .chchip .dot { width: 6px; height: 6px; border-radius: 99px; background: var(--ink-3); }
  .chchip.watching { border-color: var(--ok-muted); color: var(--ink); }
  .chchip.watching .dot { background: var(--ok); }
  .chchip .tag { font: 600 10px var(--mono); color: var(--ink-3); }
  .chchip .tag.on { color: var(--ok); }
  .fav { display: grid; place-items: center; width: 24px; height: 26px; border: 1px solid var(--border); border-left: 0; background: var(--surface); color: var(--ink-3); cursor: pointer; }
  .fav.last { border-radius: 0 99px 99px 0; padding-right: 2px; }
  .fav:hover { color: var(--accent); }
  .fav.on { color: var(--accent); }
  .provenance { font-size: 11.5px; color: var(--ink-2); border-top: 1px solid var(--border); padding-top: 8px; }
  .provenance summary { cursor: pointer; color: var(--ink-3); }
  .provenance p { margin: 6px 0; line-height: 1.5; }
  .custom { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
  .row2 { display: flex; gap: 6px; }
  .row2 .input { flex: 1; min-width: 0; }

  .theater .stage { position: fixed; inset: 0; z-index: 60; background: #000; padding: 8px; justify-content: center; }
  .theater .players { max-height: calc(100vh - 80px); }
  .theater .slotbar, .theater .statusline { color: var(--ink-2); }
  .theater .side, .theater .opts { display: none; }

  @media (max-width: 1080px) { .streams { grid-template-columns: 1fr; } }
  @media (max-width: 860px) { .slotpill { max-width: 130px; } }
</style>
