<script lang="ts">
  // Incidents view — the bell, grown up. Findings correlated by host and time, each
  // group acknowledgeable or mutable as one thing, with the member findings and any
  // homelab.db changes that happened around the same time. Moved verbatim from the
  // old routes/incidents/+page.svelte body when Activity gained the Stream/Incidents
  // toggle (2026-09-10) — the #<id> hash deep link still works because it only
  // depends on page.url.hash, not the route.
  import { page } from '$app/state';
  import { Check, BellOff, Undo2 } from '@lucide/svelte';
  import { useIncidents, useIncidentActions, type Incident } from '$lib/api/incidents';
  import { relTime, localeDateTime } from '$lib/format';
  import { toast } from '$lib/stores/toast.svelte';

  let showAll = $state(false);
  const q = useIncidents(() => showAll);
  const { ack, mute } = useIncidentActions();
  let expanded = $state<string | null>(page.url.hash ? page.url.hash.slice(1) : null);

  $effect(() => {
    const id = page.url.hash.slice(1);
    if (id && q.data) { expanded = id; document.getElementById(id)?.scrollIntoView({ block: 'center' }); }
  });

  async function doAck(i: Incident, acked = true) {
    try { await ack.mutateAsync({ id: i.id, acked }); toast(acked ? 'Acknowledged' : 'Re-opened', 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Failed: ${(e as Error).message}`, 'crit'); }
  }
  async function doMute(i: Incident, days?: number, clear = false) {
    try { await mute.mutateAsync({ id: i.id, days, clear }); toast(clear ? 'Unmuted' : `Muted ${days}d`, 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Failed: ${(e as Error).message}`, 'crit'); }
  }
  let list = $derived(q.data?.incidents ?? []);
</script>

<div class="inc-page">
  <div class="shead">
    <span class="meta">{q.data ? `${q.data.open} open · ${q.data.muted} muted · ${q.data.acked} acknowledged` : ''}</span>
    <label class="right faint" style="font-size: 12px"><input type="checkbox" bind:checked={showAll} /> show acknowledged</label>
  </div>

  {#if q.isLoading}<div class="spin"></div>{/if}
  {#if q.isError}
    <div class="card"><p class="err">Incidents unavailable — {(q.error as Error).message}</p><p class="faint" style="margin:0; font-size:12px">This backend has no <code>/api/incidents</code> (a v2 backend, or the dev proxy pointed at the live rpi). The notification bell still works.</p></div>
  {/if}
  {#if q.data && list.length === 0}
    <div class="card"><p class="empty">Nothing open — every finding has been acknowledged.</p></div>
  {/if}

  <div class="list">
    {#each list as i (i.id)}
      <article class="inc card" id={i.id} data-s={i.status} data-sev={i.severity}>
        <header>
          <span class="sev" data-s={i.severity}></span>
          <button class="title" onclick={() => (expanded = expanded === i.id ? null : i.id)}>{i.title}</button>
          <span class="chip" data-s={i.status === 'open' ? i.severity : i.status === 'muted' ? 'mute' : 'ok'}>{i.status}</span>
        </header>
        <div class="meta-line faint">
          {i.host ?? 'fleet'} · {i.sources.join(', ')} · {i.count} finding{i.count === 1 ? '' : 's'}{i.open_count !== i.count ? ` (${i.open_count} open)` : ''} · first {relTime(i.first_seen)} · last {relTime(i.last_seen)}{i.muted_until ? ` · muted until ${localeDateTime(i.muted_until)}` : ''}
        </div>
        <div class="actions">
          {#if i.status === 'acked'}
            <button class="tbtn sm" disabled={ack.isPending} onclick={() => doAck(i, false)}><Undo2 /> Re-open</button>
          {:else}
            <button class="tbtn sm" disabled={ack.isPending} onclick={() => doAck(i)}><Check /> Acknowledge</button>
            {#if i.status === 'muted'}
              <button class="tbtn sm" disabled={mute.isPending} onclick={() => doMute(i, undefined, true)}><BellOff /> Unmute</button>
            {:else}
              <button class="tbtn sm" disabled={mute.isPending} onclick={() => doMute(i, 1)}><BellOff /> Mute 1d</button>
              <button class="tbtn sm" disabled={mute.isPending} onclick={() => doMute(i, 7)}><BellOff /> 7d</button>
              <button class="tbtn sm" disabled={mute.isPending} onclick={() => doMute(i, 30)}><BellOff /> 30d</button>
            {/if}
          {/if}
          {#if i.host}<a class="tbtn sm" href="/host/{i.host}">Open {i.host}</a>{/if}
          <span class="spacer"></span>
          <button class="link-btn" style="font-size: 12px" onclick={() => (expanded = expanded === i.id ? null : i.id)}>{expanded === i.id ? 'hide' : 'details'}</button>
        </div>
        {#if expanded === i.id}
          <div class="detail">
            <h3 class="detail-section-title">Findings</h3>
            <div class="notif-list">
              {#each i.items as n (n.id)}
                <div class="notif" class:acked={n.acked} data-sev={n.severity}>
                  <span class="notif-sev">{n.severity.toUpperCase()}</span>
                  <div class="notif-body"><div>{n.message}</div><div class="notif-meta">{n.host ? `${n.host} · ` : ''}{n.source} · {relTime(n.ts)}{n.acked ? ' · acked' : ''}</div></div>
                </div>
              {/each}
            </div>
            {#if i.changes.length}
              <h3 class="detail-section-title">Changes around the same time</h3>
              <div class="rows">
                {#each i.changes as c (c.at + c.key)}
                  <div class="row"><span class="t">{relTime(c.at)}</span><span class="who">{c.kind}</span><span class="what">{c.key} {c.change}</span><span class="chip" data-s={c.change === 'removed' ? 'crit' : c.change === 'added' ? 'ok' : 'warn'}>{c.change}</span></div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </article>
    {/each}
  </div>
</div>

<style>
  .inc-page { display: flex; flex-direction: column; gap: 14px; }
  .list { display: flex; flex-direction: column; gap: 10px; }
  .inc { gap: 6px; border-left: 3px solid var(--ink-3); }
  .inc[data-s="open"][data-sev="crit"] { border-left-color: var(--crit); }
  .inc[data-s="open"][data-sev="warn"] { border-left-color: var(--warn); }
  .inc[data-s="muted"] { opacity: .75; }
  .inc[data-s="acked"] { opacity: .55; }
  header { display: flex; align-items: center; gap: 10px; }
  .sev { width: 8px; height: 8px; border-radius: 2px; flex: none; background: var(--ink-3); }
  .sev[data-s="crit"] { background: var(--crit); } .sev[data-s="warn"] { background: var(--warn); }
  .title { flex: 1; min-width: 0; text-align: left; background: none; border: 0; padding: 0; color: var(--ink); font: 600 14px var(--sans); cursor: pointer; }
  .title:hover { color: var(--accent); }
  .meta-line { font-size: 11.5px; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .detail { border-top: 1px solid var(--border); padding-top: 6px; }
</style>
