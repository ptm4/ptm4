<script lang="ts">
  // Streams — the phone page. Player on top, the four slots as pills, and beside
  // (below, on a phone) the guide: what HLTV says is worth watching today, joined with
  // the Valve top-20 and the broadcast channel the station can start, plus the channel
  // directory and a custom-URL box. Every "Watch" is one tap: the backend picks a slot.
  import { onMount } from 'svelte';
  import { Square, Grid2x2, Tv, Radio, Search, ExternalLink, Star } from '@lucide/svelte';
  import Player from '$lib/features/streams/Player.svelte';
  import { useStationStatus, useGuide, useStreamActions, watchUrl, type Slot, type GuideMatch, type GuideChannel } from '$lib/api/streams';
  import { toast } from '$lib/stores/toast.svelte';
  import { relTime, durSince } from '$lib/format';

  const status = useStationStatus(() => true);
  const guide = useGuide();
  const { watch, stop, keepalive } = useStreamActions();

  let current = $state(1);
  let multiview = $state(false);
  let theater = $state(false);
  let tab = $state<'guide' | 'channels' | 'custom'>('guide');
  let search = $state('');
  let quality = $state('');
  let profile = $state('low-latency');
  let customPlatform = $state('twitch');
  let customChannel = $state('');
  let customUrl = $state('');
  let showResults = $state(false);

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
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
      if (e.key === 't') theater = !theater;
      if (e.key === 'Escape') theater = false;
      if (e.key === 'm') multiview = !multiview;
      if (/^[1-4]$/.test(e.key)) current = Number(e.key);
    };
    window.addEventListener('keydown', onKey);
    return () => { clearInterval(t); window.removeEventListener('keydown', onKey); };
  });

  async function doWatch(req: { platform?: string; channel?: string; url?: string; label?: string }) {
    try {
      const r = await watch.mutateAsync({ ...req, quality: quality || undefined, profile });
      current = r.slot;
      toast(r.reused ? `Already on slot ${r.slot}` : `Starting ${req.label ?? req.channel ?? 'stream'} in slot ${r.slot}…`, 'ok', { ttlMs: 2500 });
    } catch (e) {
      toast(`Could not start: ${(e as Error).message}`, 'crit', { ttlMs: 8000 });
    }
  }
  async function doStop(slot: number) {
    try { await stop.mutateAsync(slot); toast(`Slot ${slot} stopped`, 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Stop failed: ${(e as Error).message}`, 'crit'); }
  }

  let matches = $derived(guide.data?.matches ?? []);
  let liveMatches = $derived(matches.filter((m) => m.status === 'live'));
  let upcoming = $derived(matches.filter((m) => m.status === 'upcoming'));
  let finished = $derived(matches.filter((m) => m.status === 'finished'));
  let channels = $derived((guide.data?.channels ?? []).filter((c) => !search || `${c.label} ${c.channel} ${c.org ?? ''}`.toLowerCase().includes(search.toLowerCase())));
  let groups = $derived([...new Set(channels.map((c) => c.group_label))]);
  const clock = (u?: number) => (u ? new Date(u * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
  const slotName = (s: Slot) => s.channel ?? (s.url ? s.url.replace(/^https?:\/\//, '').slice(0, 24) : `slot ${s.slot}`);
  const tierTone = (t: string) => (t === 'S' ? 'crit' : t === 'A' ? 'warn' : 'mute');
</script>

<div class="streams" class:theater>
  <section class="stage">
    <div class="players" class:multi={multiview}>
      {#if multiview}
        {#each slots as s (s.slot)}
          <Player slot={s.slot} live={s.state === 'starting' || s.state === 'running'} muted={s.slot !== current} active={s.slot === current} label={slotName(s)} onclick={() => (current = s.slot)} />
        {/each}
      {:else if cur}
        <Player slot={cur.slot} live={cur.state === 'starting' || cur.state === 'running'} active label={slotName(cur)} />
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
        <span class="faint">Pick a match or channel — the station starts it in a free slot. Keys: 1–4 slots · m multiview · t theater.</span>
      {/if}
    </div>
  </section>

  <section class="side">
    <div class="tabs">
      <button class:on={tab === 'guide'} onclick={() => (tab = 'guide')}><Radio size={13} /> Guide {#if liveMatches.length}<span class="cnt">{liveMatches.length} live</span>{/if}</button>
      <button class:on={tab === 'channels'} onclick={() => (tab = 'channels')}><Tv size={13} /> Channels</button>
      <button class:on={tab === 'custom'} onclick={() => (tab = 'custom')}>Custom</button>
    </div>

    <div class="opts">
      <label>Quality <select class="input" bind:value={quality}>
        <option value="">best</option><option value="1080p60,1080p,best">1080p</option><option value="720p60,720p,best">720p</option><option value="480p,worst">480p</option><option value="worst">lowest</option>
      </select></label>
      <label>Latency <select class="input" bind:value={profile}>
        <option value="low-latency">low (~6-10s)</option><option value="smooth">smooth (~15-20s)</option>
      </select></label>
    </div>

    {#if tab === 'guide'}
      {#if guide.isLoading}<div class="spin"></div>{/if}
      {#if guide.data && !guide.data.hltv.ok}
        <div class="card"><p class="dim" style="margin:0">HLTV feed unavailable ({guide.data.hltv.error}) — the channel directory still works.</p></div>
      {:else if guide.data}
        <div class="meta faint">
          HLTV {guide.data.hltv.date ?? ''}{guide.data.hltv.fetched_at ? ` · ${relTime(new Date(guide.data.hltv.fetched_at * 1000).toISOString())}` : ''}{guide.data.hltv.stale ? ' · ⚠ stale' : ''}{guide.data.vrs.as_of ? ` · VRS ${guide.data.vrs.as_of}` : ''}
        </div>
      {/if}

      {#if liveMatches.length}
        <div class="divider">Live now</div>
        {#each liveMatches as m (m.id ?? m.url)}
          {@render matchRow(m)}
        {/each}
      {/if}
      {#if guide.data?.events.length}
        <div class="divider">Today's events</div>
        <div class="events">
          {#each guide.data.events as e (e.event)}
            <div class="ev" data-tier={e.tier}>
              <span class="chip" data-s={tierTone(e.tier)}>{e.tier}-tier</span>
              <span class="evname">{e.event}</span>
              <span class="faint num">{e.live ? `${e.live} live · ` : ''}{e.upcoming} upcoming{e.top20.length ? ` · ${e.top20.length} top-20` : ''}</span>
              {#if e.channel}
                <button class="chip act" onclick={() => doWatch({ platform: e.channel!.platform, channel: e.channel!.channel, label: e.channel!.label })}>▶ {e.channel.label}</button>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
      {#if upcoming.length}
        <div class="divider">Upcoming</div>
        {#each upcoming.slice(0, 14) as m (m.id ?? m.url)}
          {@render matchRow(m)}
        {/each}
      {/if}
      {#if finished.length}
        <button class="divider asbtn" onclick={() => (showResults = !showResults)}>Results ({finished.length}) {showResults ? '▾' : '▸'}</button>
        {#if showResults}
          {#each finished as m (m.id ?? m.url)}
            {@render matchRow(m)}
          {/each}
        {/if}
      {/if}
      {#if guide.data?.vrs.top.length}
        <div class="divider">Valve top 20</div>
        <div class="vrs">{#each guide.data.vrs.top as t, i (t)}<span class="chip mute">#{i + 1} {t}</span>{/each}</div>
      {/if}
      {#if guide.data && matches.length === 0 && guide.data.hltv.ok}
        <p class="empty">No notable matches today.</p>
      {/if}
    {:else if tab === 'channels'}
      <label class="search"><Search size={13} /><input class="input" placeholder="Filter channels" bind:value={search} /></label>
      {#each groups as g (g)}
        <div class="divider">{g}</div>
        <div class="chips">
          {#each channels.filter((c) => c.group_label === g) as c (c.platform + c.channel)}
            {@render channelChip(c)}
          {/each}
        </div>
      {/each}
      {#if guide.isError}<p class="err">Guide unavailable — {(guide.error as Error).message}</p>{/if}
    {:else}
      <form class="custom" onsubmit={(e) => { e.preventDefault(); if (customChannel.trim()) doWatch({ platform: customPlatform, channel: customChannel.trim() }); }}>
        <div class="row2">
          <select class="input" bind:value={customPlatform}><option value="twitch">twitch</option><option value="youtube">youtube</option><option value="kick">kick</option></select>
          <input class="input" placeholder="channel name" bind:value={customChannel} />
          <button class="tbtn primary" type="submit" disabled={watch.isPending || !customChannel.trim()}>Watch</button>
        </div>
      </form>
      <form class="custom" onsubmit={(e) => { e.preventDefault(); if (customUrl.trim()) doWatch({ url: customUrl.trim(), label: 'URL' }); }}>
        <div class="row2">
          <input class="input" placeholder="https://… (any stream URL VLC can open: hls, rtsp, rtmp)" bind:value={customUrl} />
          <button class="tbtn" type="submit" disabled={watch.isPending || !customUrl.trim()}>Start URL</button>
        </div>
      </form>
      <p class="faint" style="font-size: 11.5px">Channel names go through streamlink (Twitch ad-bypass, low-latency); URLs go straight to VLC and are remuxed, never transcoded.</p>
    {/if}
  </section>
</div>

{#snippet matchRow(m: GuideMatch)}
  <div class="match" data-status={m.status}>
    <span class="chip" data-s={tierTone(m.tier)} title="{m.stars ?? 0}★ on HLTV{m.top20.length ? ` · top-20: ${m.top20.join(', ')}` : ''}">{m.tier}</span>
    <div class="mbody">
      <div class="mhead">
        {#if m.status === 'live'}<span class="t-crit mono">LIVE</span>{:else if m.status === 'finished'}<span class="faint mono">final</span>{:else}<span class="faint mono">{clock(m.start_unix)}</span>{/if}
        <a class="teams" href={m.url} target="_blank" rel="noreferrer">{m.team1 ?? '?'} <span class="faint">vs</span> {m.team2 ?? '?'}</a>
        {#if m.score1 != null && m.score2 != null}<span class="mono score">{m.score1}–{m.score2}</span>{/if}
      </div>
      <div class="msub faint">{m.event}{m.bo ? ` · ${m.bo}` : ''}{m.stars ? ` · ${'★'.repeat(m.stars)}` : ''}{m.maps?.length ? ` · ${m.maps.map((x) => `${x.name} ${x.s1}-${x.s2}`).join(' · ')}` : ''}</div>
    </div>
    {#if m.status !== 'finished' && m.channel}
      {#if m.watching_slot}
        <button class="tbtn sm" onclick={() => (current = m.watching_slot!)}>slot {m.watching_slot}</button>
      {:else}
        <button class="tbtn sm primary" disabled={watch.isPending} onclick={() => doWatch({ platform: m.channel!.platform, channel: m.channel!.channel, label: m.channel!.label })}>▶ {m.channel.label}</button>
      {/if}
    {/if}
  </div>
{/snippet}

{#snippet channelChip(c: GuideChannel)}
  <button class="chchip" class:onair={c.on_air} class:watching={c.watching_slot != null} disabled={watch.isPending}
    title="{c.platform}/{c.channel}{c.org ? ` · ${c.org}` : ''}{c.scheduled ? ` · ${c.scheduled} match(es) scheduled` : ''}"
    onclick={() => (c.watching_slot != null ? (current = c.watching_slot) : doWatch({ platform: c.platform, channel: c.channel, label: c.label }))}>
    <span class="dot"></span>{c.label}
    {#if c.watching_slot != null}<span class="tag">slot {c.watching_slot}</span>{:else if c.on_air}<span class="tag live">on air</span>{:else if c.scheduled}<span class="tag">{c.scheduled}</span>{/if}
    {#if c.org}<Star size={10} class="org" />{/if}
  </button>
{/snippet}

<style>
  .streams { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
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

  .side { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .tabs { display: flex; gap: 2px; padding: 2px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); }
  .tabs button { flex: 1; border: 0; background: none; color: var(--ink-2); font: inherit; font-size: 12.5px; padding: 6px 8px; border-radius: var(--r-sm); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
  .tabs button.on { background: var(--accent-dim); color: var(--accent); font-weight: 600; }
  .tabs .cnt { font: 600 10px var(--mono); color: var(--crit); }
  .opts { display: flex; gap: 8px; font-size: 11.5px; color: var(--ink-3); }
  .opts label { display: flex; align-items: center; gap: 6px; flex: 1; }
  .opts .input { flex: 1; font-size: 12px; padding: 3px 6px; }
  .meta { font-size: 11px; }
  .divider.asbtn { background: none; border: 0; font: inherit; color: var(--ink-3); cursor: pointer; width: 100%; text-align: left; font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; }
  .match { display: flex; gap: 9px; align-items: center; padding: 7px 10px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); }
  .match[data-status="live"] { border-color: var(--crit-dim); box-shadow: inset 0 0 0 1px var(--crit-dim); }
  .mbody { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .mhead { display: flex; gap: 8px; align-items: baseline; font-size: 13px; min-width: 0; }
  .teams { color: var(--ink); font-weight: 600; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .teams:hover { color: var(--accent); }
  .score { margin-left: auto; font-weight: 600; }
  .msub { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .events { display: flex; flex-direction: column; gap: 4px; }
  .ev { display: flex; gap: 8px; align-items: center; font-size: 12.5px; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); flex-wrap: wrap; }
  .evname { font-weight: 600; flex: 1; min-width: 0; }
  .vrs { display: flex; flex-wrap: wrap; gap: 4px; }
  .search { display: flex; align-items: center; gap: 6px; color: var(--ink-3); }
  .search .input { flex: 1; }
  .chchip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--ink-2); border-radius: 99px; padding: 5px 10px 5px 8px; font: inherit; font-size: 12.5px; cursor: pointer; }
  .chchip:hover { color: var(--ink); border-color: var(--accent-muted); }
  .chchip .dot { width: 6px; height: 6px; border-radius: 99px; background: var(--ink-3); }
  .chchip.onair .dot { background: var(--crit); box-shadow: 0 0 6px var(--crit); }
  .chchip.watching { border-color: var(--ok-muted); color: var(--ink); }
  .chchip.watching .dot { background: var(--ok); }
  .chchip .tag { font: 600 10px var(--mono); color: var(--ink-3); }
  .chchip .tag.live { color: var(--crit); }
  .chchip :global(.org) { color: var(--accent); opacity: .8; }
  .custom { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
  .row2 { display: flex; gap: 6px; }
  .row2 .input { flex: 1; min-width: 0; }

  .theater .stage { position: fixed; inset: 0; z-index: 60; background: #000; padding: 8px; justify-content: center; }
  .theater .players { max-height: calc(100vh - 80px); }
  .theater .players :global(.player) { max-height: calc(100vh - 90px); }
  .theater .slotbar, .theater .statusline { color: var(--ink-2); }
  .theater .side { display: none; }

  @media (max-width: 1080px) {
    .streams { grid-template-columns: 1fr; }
  }
  @media (max-width: 860px) {
    .slotpill { max-width: 130px; }
    .players.multi { grid-template-columns: 1fr 1fr; }
  }
</style>
