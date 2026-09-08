<script lang="ts">
  // "What's on" — the Home card for streams: running slots, the S/A-tier matches live
  // right now with one-tap Watch, and the next few worth planning for. Same guide the
  // Streams page uses.
  import { Radio, ArrowRight } from '@lucide/svelte';
  import { useGuide, useStreamActions } from '$lib/api/streams';
  import { toast } from '$lib/stores/toast.svelte';

  const guide = useGuide();
  const { watch } = useStreamActions();
  let slots = $derived((guide.data?.station.slots ?? []).filter((s) => s.state === 'running' || s.state === 'starting'));
  let live = $derived((guide.data?.matches ?? []).filter((m) => m.status === 'live' && m.tier !== 'B').slice(0, 4));
  let next = $derived((guide.data?.matches ?? []).filter((m) => m.status === 'upcoming' && m.tier === 'S').slice(0, 3));
  const clock = (u?: number) => (u ? new Date(u * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
  async function go(m: { channel: { platform: string; channel: string; label: string } | null }) {
    if (!m.channel) return;
    try { const r = await watch.mutateAsync({ platform: m.channel.platform, channel: m.channel.channel }); toast(`Slot ${r.slot} → ${m.channel.label}`, 'ok', { ttlMs: 2500 }); }
    catch (e) { toast(`Could not start: ${(e as Error).message}`, 'crit'); }
  }
</script>

<section class="card sc">
  <div class="chead"><Radio size={13} aria-hidden="true" /><h3>Streams</h3>
    <span class="meta">{guide.data ? (guide.data.station.ok ? `${slots.length} slot${slots.length === 1 ? '' : 's'} live` : 'station offline') : guide.isError ? 'unavailable' : '…'}</span>
  </div>
  {#if slots.length}
    <div class="slots">
      {#each slots as s (s.slot)}
        <a class="chip act" href="/streams?slot={s.slot}" data-s={s.state === 'running' ? 'ok' : 'warn'}>▶ {s.slot} · {s.channel ?? s.url?.slice(0, 20)}</a>
      {/each}
    </div>
  {/if}
  {#if live.length}
    <div class="divider">Live now</div>
    {#each live as m (m.id ?? m.url)}
      <div class="mrow">
        <span class="chip" data-s={m.tier === 'S' ? 'crit' : 'warn'}>{m.tier}</span>
        <span class="teams">{m.team1} <span class="faint">vs</span> {m.team2}</span>
        <span class="faint ev">{m.event}</span>
        {#if m.score1 != null}<span class="mono">{m.score1}–{m.score2}</span>{/if}
        {#if m.channel}
          {#if m.watching_slot}<a class="tbtn sm" href="/streams">slot {m.watching_slot}</a>{:else}<button class="tbtn sm primary" disabled={watch.isPending} onclick={() => go(m)}>▶ Watch</button>{/if}
        {/if}
      </div>
    {/each}
  {/if}
  {#if next.length}
    <div class="divider">Next S-tier</div>
    {#each next as m (m.id ?? m.url)}
      <div class="mrow"><span class="mono faint">{clock(m.start_unix)}</span><span class="teams">{m.team1} <span class="faint">vs</span> {m.team2}</span><span class="faint ev">{m.event}</span></div>
    {/each}
  {/if}
  {#if guide.data && !slots.length && !live.length && !next.length}
    <p class="empty">Nothing live. {guide.data.hltv.ok ? 'No S-tier matches scheduled today.' : 'HLTV feed unavailable — the channel directory still works.'}</p>
  {/if}
  <a class="more" href="/streams">Open Streams <ArrowRight size={12} aria-hidden="true" /></a>
</section>

<style>
  .sc { gap: 8px; }
  .chead h3 { flex: none; }
  .slots { display: flex; gap: 6px; flex-wrap: wrap; }
  .slots .chip[data-s="ok"] { color: var(--ok); border-color: var(--ok-muted); }
  .mrow { display: flex; gap: 8px; align-items: center; font-size: 12.5px; min-width: 0; }
  .teams { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ev { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
  .more { margin-top: auto; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; }
</style>
