<script lang="ts">
  // Feed — the homelab as one chronological stream: reports, heals, bot posts,
  // updates, backups, security, homelab.db changes and open incidents, newest
  // first, filterable by category and host, with the Now rail pinned beside it.
  import { useActivity } from '$lib/api/queries';
  import { useIncidents } from '$lib/api/incidents';
  import { useChanges, FALLBACK_FLEET, useHosts } from '$lib/api/fleet';
  import { mergeFeed, dayLabel, CATEGORY_LABEL, type FeedCategory } from '$lib/features/feed/feed-merge';
  import FeedItemView from '$lib/features/feed/FeedItemView.svelte';
  import NowRail from '$lib/components/NowRail.svelte';

  const activity = useActivity(100);
  const incidents = useIncidents();
  const changes = useChanges(() => '', () => 7);
  const hostsQ = useHosts();

  let category = $state<FeedCategory | 'all'>('all');
  let host = $state<string>('');

  let items = $derived(mergeFeed(activity.data?.events, incidents.data?.incidents, changes.data?.events));
  let counts = $derived.by(() => {
    const c: Record<string, number> = { all: items.length };
    for (const i of items) c[i.category] = (c[i.category] ?? 0) + 1;
    return c;
  });
  let shown = $derived(items.filter((i) => (category === 'all' || i.category === category) && (!host || i.host === host)));
  let hosts = $derived((hostsQ.data ?? FALLBACK_FLEET).hosts.map((h) => h.name));
  const CATS: FeedCategory[] = ['incident', 'health', 'bots', 'security', 'changes', 'updates', 'backup', 'vpn'];

  // Anything newer than the last visit gets the accent bar.
  let lastSeen = $state<number>(0);
  $effect(() => {
    try { lastSeen = Number(localStorage.getItem('feed-seen') ?? 0); } catch { /* private mode */ }
    return () => { try { localStorage.setItem('feed-seen', String(Date.now())); } catch { /* private mode */ } };
  });
  const isUnread = (ts: string | null) => !!ts && Date.parse(ts) > lastSeen;

  let groups = $derived.by(() => {
    const out: { day: string; items: typeof shown }[] = [];
    for (const it of shown) {
      const day = it.kind === 'incident' && it.incident?.status === 'open' ? 'Needs action' : dayLabel(it.ts);
      const g = out[out.length - 1];
      if (g && g.day === day) g.items.push(it); else out.push({ day, items: [it] });
    }
    return out;
  });
</script>

<div class="feed-page">
  <div class="shead"><h2>Feed</h2><span class="meta">everything, newest first{changes.isError ? ' · changes unavailable (homelab-db)' : ''}{incidents.isError ? ' · incidents unavailable on this backend' : ''}</span></div>
  <div class="split">
    <div class="feed">
      <div class="fbar">
        <button class="f" class:on={category === 'all'} onclick={() => (category = 'all')}>Everything <span class="c">{counts.all ?? 0}</span></button>
        {#each CATS as c (c)}
          {#if counts[c]}
            <button class="f" class:on={category === c} onclick={() => (category = c)}>{CATEGORY_LABEL[c]} <span class="c" class:hot={c === 'incident'}>{counts[c]}</span></button>
          {/if}
        {/each}
        <select class="input hostsel" bind:value={host} aria-label="Host filter">
          <option value="">all hosts</option>
          {#each hosts as h (h)}<option value={h}>{h}</option>{/each}
        </select>
      </div>

      {#if activity.isLoading && incidents.isLoading}
        <div class="spin"></div>
      {:else if activity.isError && incidents.isError}
        <div class="card"><p class="err">Could not load the feed — {(activity.error as Error)?.message}</p></div>
      {:else if shown.length === 0}
        <div class="card"><p class="empty">Nothing in the stream for this filter.</p></div>
      {/if}

      {#each groups as g (g.day)}
        <div class="divider">{g.day}</div>
        {#each g.items as it (it.key)}
          <FeedItemView item={it} unread={isUnread(it.ts) && it.kind !== 'incident'} />
        {/each}
      {/each}
    </div>
    <NowRail />
  </div>
</div>

<style>
  .feed-page { display: flex; flex-direction: column; gap: 14px; }
  .split { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: start; }
  .feed { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .fbar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .f { border: 1px solid var(--border); background: none; border-radius: 99px; padding: 2px 10px; font-size: 11.5px; color: var(--ink-2); cursor: pointer; font-family: inherit; }
  .f.on { color: var(--accent); border-color: var(--accent-muted); background: var(--accent-dim); }
  .f .c { color: var(--ink-3); margin-left: 4px; font-family: var(--mono); font-size: 10.5px; }
  .f .c.hot { color: var(--warn); }
  .hostsel { margin-left: auto; font-size: 11.5px; padding: 2px 6px; }
  @media (max-width: 1080px) { .split { grid-template-columns: 1fr; } }
</style>
