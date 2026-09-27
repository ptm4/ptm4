<script lang="ts">
  // Streams: one big player (or a 2×2 multiview), the four stream-station slots, and a
  // guide of what's on. The guide only offers "Watch" where HLTV attached a stream to
  // that match — see backend/lib/streams-guide.js for the rules.
  import { LayoutGrid, Square, X, Play, Radio } from '@lucide/svelte';
  import Player from '$lib/components/Player.svelte';
  import { api, type StreamGuide, type StreamSlot } from '$lib/api';
  import { live } from '$lib/live.svelte';
  import { clock } from '$lib/format';

  let guide = $state<StreamGuide | null>(null);
  let err = $state<string | null>(null);
  let actionErr = $state<string | null>(null);
  let busy = $state<string | null>(null);
  let current = $state(1);
  let multiview = $state(false);
  let q = $state('');

  async function load() {
    try { guide = await api.streams.guide(); err = null; } catch (e) { err = (e as Error).message; }
  }
  // The slot snapshot refreshes every 5s; refetch the guide when it (or HLTV) changes.
  const stamp = $derived(['streams:status', 'hltv:day', 'streams:presets'].map((k) => live.snapshots[k]?.fetched_at).join());
  $effect(() => { void stamp; void load(); });

  const ACTIVE = ['starting', 'running'];
  const slots = $derived<StreamSlot[]>(guide?.station.slots?.length ? guide.station.slots : [1, 2, 3, 4].map((n) => ({ slot: n, state: 'idle' } as StreamSlot)));
  const activeSlots = $derived(slots.filter((s) => ACTIVE.includes(s.state)));
  const cur = $derived(slots.find((s) => s.slot === current));

  // Keep watched slots alive while this page is visible (the station reaps idle slots).
  $effect(() => {
    const ids = activeSlots.map((s) => s.slot);
    if (!ids.length) return;
    const t = setInterval(() => { if (document.visibilityState === 'visible') api.streams.keepalive(ids); }, 5000);
    return () => clearInterval(t);
  });

  async function watch(key: string, body: { platform?: string; channel?: string; url?: string }) {
    busy = key; actionErr = null;
    try {
      const r = await api.streams.watch(body);
      current = r.slot;
      await load();
    } catch (e) {
      actionErr = (e as Error).message;
    } finally { busy = null; }
  }
  async function stop(slot: number) {
    busy = `stop:${slot}`; actionErr = null;
    try { await api.streams.stop(slot); await load(); } catch (e) { actionErr = (e as Error).message; } finally { busy = null; }
  }

  const liveNow = $derived((guide?.matches ?? []).filter((m) => m.status === 'live' || m.status === 'unknown'));
  const upcoming = $derived((guide?.matches ?? []).filter((m) => m.status === 'upcoming' && (m.top20 || m.premier || m.stars >= 1)).slice(0, 8));
  const groups = $derived.by(() => {
    const out = new Map<string, { label: string; channels: StreamGuide['channels'] }>();
    for (const c of guide?.channels ?? []) {
      if (q && !`${c.label ?? ''} ${c.channel} ${c.org ?? ''}`.toLowerCase().includes(q.toLowerCase())) continue;
      if (!out.has(c.group)) out.set(c.group, { label: c.group_label, channels: [] });
      out.get(c.group)!.channels.push(c);
    }
    return [...out.values()];
  });
  const slotName = (s: StreamSlot) => s.channel ?? s.url ?? `slot ${s.slot}`;
  const rank = (r: number | null) => (r != null ? `#${r}` : '');

  // Keyboard: 1–4 pick a slot, m toggles multiview.
  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.closest('input, textarea')) return;
    if (['1', '2', '3', '4'].includes(e.key)) current = Number(e.key);
    else if (e.key === 'm') multiview = !multiview;
  }
</script>

<svelte:window onkeydown={onKey} />
<svelte:head><title>Streams · Pertal</title></svelte:head>

<div class="head">
  <h1>Streams</h1>
  <span class="faint">
    {#if guide?.station.ok}stream-station {guide.station.version} · {activeSlots.length}/4 slots in use{:else if guide}stream-station unreachable{/if}
  </span>
  <button class="btn" onclick={() => (multiview = !multiview)} title="Multiview (m)">
    {#if multiview}<Square size={15} /> Single{:else}<LayoutGrid size={15} /> Multiview{/if}
  </button>
</div>

{#if err}<p class="banner">Could not load the guide: {err}</p>{/if}
{#if actionErr}<p class="banner">{actionErr}</p>{/if}

<section class="stage" class:grid={multiview}>
  {#if multiview}
    {#each slots as s (s.slot)}
      <Player slot={s.slot} live={ACTIVE.includes(s.state)} muted={s.slot !== current} active={s.slot === current} label="{s.slot} · {slotName(s)}" onclick={() => (current = s.slot)} />
    {/each}
  {:else}
    <Player slot={current} live={!!cur && ACTIVE.includes(cur.state)} label={cur && cur.state !== 'idle' ? `${cur.slot} · ${slotName(cur)}` : ''} />
  {/if}
</section>

<div class="slots">
  {#each slots as s (s.slot)}
    <div class="slot" class:on={s.slot === current} class:active={ACTIVE.includes(s.state)}>
      <button class="pick" onclick={() => (current = s.slot)}>
        <span class="n">{s.slot}</span>
        <span class="name">{s.state === 'idle' ? 'idle' : slotName(s)}</span>
        <span class="st faint">{s.state}{#if s.state === 'ended' && s.error} · {s.error}{/if}</span>
      </button>
      {#if ACTIVE.includes(s.state)}
        <button class="btn ghost icon" aria-label="Stop slot {s.slot}" disabled={busy === `stop:${s.slot}`} onclick={() => stop(s.slot)}><X size={14} /></button>
      {/if}
    </div>
  {/each}
</div>

<div class="cols">
  <section class="panel">
    <div class="panel-head">
      <h2>CS2 · live now</h2>
      <span class="faint">{#if guide?.hltv.stale}feed stale — "live" not claimed{:else if guide?.hltv.ok}HLTV{:else if guide}{guide.hltv.error}{/if}</span>
    </div>
    <div class="rows">
      {#each liveNow as m (m.id)}
        <div class="row match">
          <span class="badge {m.status === 'live' ? 'crit' : ''}">{m.status}</span>
          <div class="mm">
            <div><b>{m.team1}</b> <span class="faint">{rank(m.rank1)}</span> {#if m.score1 != null}<span class="num">{m.score1}–{m.score2}</span>{:else}vs{/if} <b>{m.team2}</b> <span class="faint">{rank(m.rank2)}</span></div>
            <div class="faint ev">{m.event}{#if m.premier} · premier series{/if}</div>
          </div>
          {#if m.watching_slot}
            <button class="btn" onclick={() => (current = m.watching_slot!)}>Slot {m.watching_slot}</button>
          {:else if m.channel}
            <button class="btn primary" disabled={busy === m.id} onclick={() => watch(m.id, { platform: m.channel!.platform, channel: m.channel!.channel })}><Play size={14} /> Watch</button>
          {:else}
            <a class="btn ghost" href={m.url} target="_blank" rel="noreferrer" title="HLTV lists no stream for this match">HLTV</a>
          {/if}
        </div>
      {:else}
        <div class="empty">{guide?.hltv.ok ? 'No CS2 matches live right now.' : 'No HLTV data.'}</div>
      {/each}
      {#if upcoming.length}
        <div class="sub faint">Coming up</div>
        {#each upcoming as m (m.id)}
          <div class="row match up">
            <span class="faint when">{m.start_unix ? clock(new Date(m.start_unix * 1000).toISOString()) : ''}</span>
            <div class="mm">
              <div>{m.team1} <span class="faint">{rank(m.rank1)}</span> vs {m.team2} <span class="faint">{rank(m.rank2)}</span></div>
              <div class="faint ev">{m.event}</div>
            </div>
            <a class="btn ghost" href={m.url} target="_blank" rel="noreferrer">HLTV</a>
          </div>
        {/each}
      {/if}
    </div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>Channels</h2><input class="field" type="search" placeholder="Filter…" bind:value={q} /></div>
    {#each groups as g (g.label)}
      <div class="sub faint">{g.label}</div>
      <div class="chans">
        {#each g.channels as c (c.platform + c.channel)}
          <button class="chan" class:watching={!!c.watching_slot} disabled={busy === c.channel}
            onclick={() => (c.watching_slot ? (current = c.watching_slot) : watch(c.channel, { platform: c.platform, channel: c.channel }))}
            title="{c.platform}/{c.channel}{c.listed_matches ? ` · listed for ${c.listed_matches} match(es) today` : ''}">
            {#if c.watching_slot}<Radio size={13} />{/if}
            <span>{c.label ?? c.channel}</span>
            <span class="faint plat">{c.platform}</span>
            {#if c.listed_matches}<span class="badge accent">{c.listed_matches}</span>{/if}
          </button>
        {/each}
      </div>
    {/each}
  </section>
</div>

<style>
  .head { display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .head .faint { flex: 1; font-size: var(--fs-sm); }
  .banner { margin: 0 0 var(--s3); padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); }
  .stage { max-width: 1100px; margin-bottom: var(--s3); }
  .stage.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  .slots { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--s2); margin-bottom: var(--s4); max-width: 1100px; }
  .slot { display: flex; align-items: center; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); }
  .slot.on { border-color: var(--accent); }
  .pick { flex: 1; min-width: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 8px; padding: 6px 10px; border: 0; background: none; text-align: left; cursor: pointer; }
  .n { grid-row: span 2; font: 600 var(--fs-lg) var(--mono); color: var(--ink-3); align-self: center; }
  .slot.active .n { color: var(--accent); }
  .name { font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st { font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: var(--s3); align-items: start; }
  .match { grid-template-columns: 64px minmax(0, 1fr) auto; font-size: var(--fs-sm); }
  .match b { font-weight: 600; }
  .mm { min-width: 0; }
  .ev { font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .when { font-size: var(--fs-xs); }
  .sub { padding: 10px 16px 4px; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; }
  .panel-head .field { width: 140px; }
  .chans { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 16px 10px; }
  .chan {
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border-2); background: var(--surface-2); cursor: pointer; font-size: var(--fs-sm);
  }
  .chan:hover:not(:disabled) { border-color: var(--accent); }
  .chan.watching { border-color: var(--accent); background: var(--accent-dim); }
  .plat { font-size: var(--fs-xs); }
  @media (max-width: 900px) {
    .cols { grid-template-columns: minmax(0, 1fr); }
    .slots { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .stage.grid { gap: 3px; }
  }
</style>
