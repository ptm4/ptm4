<script lang="ts">
  // One row of the stream. Incidents carry their Ack / Mute chips inline.
  import type { FeedItem } from './feed-merge';
  import { AVATAR, timeLabel } from './feed-merge';
  import { useIncidentActions } from '$lib/api/incidents';
  import { toast } from '$lib/stores/toast.svelte';

  let { item, unread = false }: { item: FeedItem; unread?: boolean } = $props();
  const { ack, mute } = useIncidentActions();

  async function doAck() {
    if (!item.incident) return;
    try { await ack.mutateAsync({ id: item.incident.id }); toast('Acknowledged', 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Could not acknowledge: ${(e as Error).message}`, 'crit'); }
  }
  async function doMute(days: number) {
    if (!item.incident) return;
    try { await mute.mutateAsync({ id: item.incident.id, days }); toast(`Muted for ${days} day${days === 1 ? '' : 's'}`, 'ok', { ttlMs: 2000 }); }
    catch (e) { toast(`Could not mute: ${(e as Error).message}`, 'crit'); }
  }
</script>

<div class="item" class:unread class:incident={item.kind === 'incident' && item.tone !== 'info'} id={item.incident ? item.incident.id : undefined}>
  <span class="av {item.category}" data-tone={item.tone}>{AVATAR[item.category]}</span>
  <div class="body">
    <div class="ihead">
      <span class="who">{item.who}</span>
      <span class="what">{item.what}</span>
      <span class="t num">{timeLabel(item.ts)}</span>
    </div>
    {#if item.excerpt}<div class="excerpt">{item.excerpt}</div>{/if}
    <div class="ichips">
      {#if item.kind === 'incident' && item.incident}
        <span class="chip" data-s={item.incident.status === 'muted' ? 'mute' : item.tone}>{item.incident.status === 'muted' ? `muted until ${new Date(item.incident.muted_until ?? '').toLocaleDateString()}` : item.incident.status}</span>
        {#if item.incident.status === 'open'}
          <button class="chip act" disabled={ack.isPending} onclick={doAck}>Ack</button>
          <button class="chip act" disabled={mute.isPending} onclick={() => doMute(7)}>Mute 7d</button>
        {/if}
        {#if item.host}<a class="chip act" href="/host/{item.host}">Open {item.host}</a>{/if}
        <a class="chip act" href="/incidents#{item.incident.id}">Details</a>
      {:else}
        <span class="chip" data-s={item.tone === 'info' ? 'info' : item.tone}>{item.tone === 'info' ? item.category : item.tone}</span>
        {#if item.host}<a class="chip act" href="/host/{item.host}">{item.host}</a>{/if}
        {#if item.category === 'health'}<a class="chip act" href="/reports">Full report</a>{/if}
        {#if item.category === 'security'}<a class="chip act" href="/security">Security</a>{/if}
        {#if item.category === 'changes'}<a class="chip act" href="/query">hl_changes</a>{/if}
        {#if item.category === 'updates'}<a class="chip act" href="/updates">Updates</a>{/if}
        {#if item.category === 'bots'}<a class="chip act" href="/bots">Bots</a>{/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .item { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 9px 12px; display: flex; gap: 11px; min-width: 0; transition: border-color .15s; }
  .item:hover { border-color: var(--border-2); }
  .item.unread { border-left: 3px solid var(--accent); }
  .item.incident { border-color: var(--crit-dim); box-shadow: inset 0 0 0 1px var(--crit-dim); }
  .av { width: 28px; height: 28px; border-radius: var(--r-sm); flex: none; display: grid; place-items: center; font: 700 11.5px var(--sans); color: var(--bg); background: var(--ink-3); }
  .av.health { background: var(--c-network); } .av.vpn { background: var(--c-aqua); } .av.bots { background: var(--ok); }
  .av.updates { background: var(--warn); } .av.security { background: var(--crit); } .av.changes { background: var(--c-apps); }
  .av.backup { background: var(--ink-2); } .av.incident { background: var(--crit); }
  .av.incident[data-tone="warn"] { background: var(--warn); } .av.incident[data-tone="info"] { background: var(--ink-3); }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .ihead { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .who { font-weight: 600; }
  .what { color: var(--ink-2); min-width: 0; }
  .t { margin-left: auto; font-size: 11px; color: var(--ink-3); }
  .excerpt { color: var(--ink-2); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; }
  .ichips { display: flex; gap: 6px; margin-top: 3px; flex-wrap: wrap; align-items: center; }
  a.chip.act { text-decoration: none; }
  .chip.act:disabled { opacity: .5; cursor: default; }
</style>
