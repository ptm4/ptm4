<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import StatusDot from '$lib/components/StatusDot.svelte';
  import Age from '$lib/components/Age.svelte';
  import { live } from '$lib/live.svelte';
  import type { Resource } from '$lib/types';

  type Kind = 'all' | 'host' | 'app' | 'bot' | 'infra';
  const kinds: { id: Kind; label: string }[] = [
    { id: 'all', label: 'All' }, { id: 'host', label: 'Hosts' }, { id: 'app', label: 'Apps' },
    { id: 'bot', label: 'Bots' }, { id: 'infra', label: 'Infra' },
  ];

  // Filters live in the URL so a filtered view is shareable and survives reload.
  const kind = $derived((page.url.searchParams.get('kind') as Kind) || 'all');
  const onlyAttn = $derived(page.url.searchParams.get('attn') === '1');
  let q = $state(page.url.searchParams.get('q') ?? '');

  function setParam(key: string, value: string | null) {
    const u = new URL(page.url);
    if (value) u.searchParams.set(key, value); else u.searchParams.delete(key);
    goto(u, { replaceState: true, keepFocus: true, noScroll: true });
  }

  const rank: Record<string, number> = { crit: 0, warn: 1, unknown: 2, ok: 3, offline: 4 };
  // Fleet order (opti, rpi, noblenumbat, android) — the backend emits hosts in that order.
  const hostOrder = $derived(new Map(live.resources.filter((r) => r.type === 'host').map((r, i) => [r.id, i])));
  const list = $derived(
    live.resources
      .filter((r) => kind === 'all' || r.kind === kind)
      .filter((r) => !onlyAttn || r.status === 'warn' || r.status === 'crit' || r.status === 'unknown')
      .filter((r) => !q.trim() || `${r.name} ${r.host} ${r.kind} ${r.status_text}`.toLowerCase().includes(q.trim().toLowerCase()))
      .sort((a, b) =>
        (hostOrder.get(a.host) ?? 99) - (hostOrder.get(b.host) ?? 99) ||
        (a.type === 'host' ? -1 : b.type === 'host' ? 1 : 0) ||
        rank[a.status] - rank[b.status] ||
        a.name.localeCompare(b.name)),
  );
  const count = (k: Kind) => live.resources.filter((r) => k === 'all' || r.kind === k).length;
  const typeLabel = (r: Resource) => (r.type === 'host' ? 'host' : r.kind);
</script>

<svelte:head><title>Resources · Pertal</title></svelte:head>

<div class="head">
  <h1>Resources</h1>
  <span class="faint">{list.length} of {live.resources.length}</span>
</div>

<div class="toolbar">
  <div class="seg" role="group" aria-label="Type">
    {#each kinds as k (k.id)}
      <button aria-pressed={kind === k.id} onclick={() => setParam('kind', k.id === 'all' ? null : k.id)}>{k.label} <span class="faint">{count(k.id)}</span></button>
    {/each}
  </div>
  <label class="attn"><input type="checkbox" checked={onlyAttn} onchange={(e) => setParam('attn', e.currentTarget.checked ? '1' : null)} /> Needs attention</label>
  <input class="field filter" type="search" placeholder="Filter by name, host, status…" bind:value={q} oninput={() => setParam('q', q || null)} />
</div>

<div class="panel">
  <div class="row header">
    <span></span><span>Name</span><span>Type</span><span>Host</span><span>Status</span><span>Updated</span>
  </div>
  <div class="rows">
    {#each list as r (r.id)}
      <a class="row item" class:host={r.type === 'host'} href="/r/{r.id}">
        <StatusDot status={r.status} />
        <span class="name">{r.name}</span>
        <span class="faint type">{typeLabel(r)}</span>
        <span class="muted hostcol">{r.host}</span>
        <span class="st" class:warn={r.status === 'warn'} class:crit={r.status === 'crit'}>{r.status_text}</span>
        <Age at={r.updated_at} />
      </a>
    {:else}
      <div class="empty">{live.loaded ? 'Nothing matches.' : 'Loading…'}</div>
    {/each}
  </div>
</div>

<style>
  .head { display: flex; align-items: baseline; gap: var(--s3); margin-bottom: var(--s3); }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s3); margin-bottom: var(--s3); }
  .attn { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); color: var(--ink-2); }
  .filter { flex: 1; min-width: 180px; max-width: 360px; }
  .row { grid-template-columns: 12px minmax(140px, 1.3fr) 70px 110px minmax(0, 2fr) 70px; }
  .row.header { font-size: var(--fs-xs); color: var(--ink-3); text-transform: uppercase; letter-spacing: .05em; }
  .item.host { background: var(--surface-2); }
  .item.host .name { font-weight: 600; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .type, .hostcol { font-size: var(--fs-sm); }
  .st { font-size: var(--fs-sm); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st.warn { color: var(--warn); }
  .st.crit { color: var(--crit); }
  @media (max-width: 720px) {
    .row.header { display: none; }
    .row.item { grid-template-columns: 12px minmax(0, 1fr) auto; grid-template-areas: 'dot name age' 'dot st st'; row-gap: 2px; }
    .row.item > :global(.dot) { grid-area: dot; align-self: start; margin-top: 5px; }
    .name { grid-area: name; }
    .st { grid-area: st; white-space: normal; }
    .type, .hostcol { display: none; }
    .row.item > :global(.age) { grid-area: age; }
  }
</style>
