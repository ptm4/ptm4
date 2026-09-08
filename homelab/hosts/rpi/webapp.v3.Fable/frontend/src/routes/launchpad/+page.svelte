<script lang="ts">
  // Launchpad — every web UI in the homelab, with live health, grouped by category or
  // host, searchable, with favourites pinned on top (persisted in the shared UI
  // settings so they follow you to the phone). Container-backed tiles get their
  // container state and a restart action.
  import { Search, Star, ExternalLink, RotateCcw, ScrollText, LayoutGrid, Server } from '@lucide/svelte';
  import { useServices, fallbackServices, type Service } from '$lib/api/services';
  import { useSettings, useSaveSettings } from '$lib/api/boards';
  import { iconUrl } from '$lib/links';
  import { post } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { CRITICAL_CONTAINERS, SELF_CONTAINERS } from '$lib/impact';
  import { relTime } from '$lib/format';

  const q = useServices();
  const settings = useSettings();
  const save = useSaveSettings();

  let search = $state('');
  let groupBy = $state<'category' | 'host'>('category');
  let data = $derived(q.data ?? (q.isError ? fallbackServices() : null));
  let favIds = $derived<string[]>((settings.data as { favorites?: string[] } | undefined)?.favorites ?? (data?.services.filter((s) => s.fav).map((s) => s.id) ?? []));
  let list = $derived((data?.services ?? []).filter((s) => !search || `${s.label} ${s.host ?? ''} ${s.category} ${s.description ?? ''}`.toLowerCase().includes(search.toLowerCase())));
  let favs = $derived(list.filter((s) => favIds.includes(s.id)));
  let groups = $derived.by(() => {
    const m = new Map<string, Service[]>();
    for (const s of list) {
      const k = groupBy === 'category' ? s.category : (s.host ?? 'network');
      m.set(k, [...(m.get(k) ?? []), s]);
    }
    return [...m.entries()];
  });
  let up = $derived((data?.services ?? []).filter((s) => s.state === 'up').length);
  let down = $derived((data?.services ?? []).filter((s) => s.state === 'down'));

  async function toggleFav(id: string) {
    const next = favIds.includes(id) ? favIds.filter((x) => x !== id) : [...favIds, id];
    try { await save.mutateAsync({ favorites: next } as never); } catch (e) { toast(`Could not save favourites: ${(e as Error).message}`, 'crit'); }
  }
  async function restart(s: Service) {
    if (!s.host || !s.container) return;
    const ok = await confirm({
      title: `Restart ${s.container} on ${s.host}?`,
      body: `docker restart ${s.container} via the ${s.host} agent.`,
      danger: CRITICAL_CONTAINERS[s.container],
      tone: CRITICAL_CONTAINERS[s.container] ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: CRITICAL_CONTAINERS[s.container] ? s.container : null,
    });
    if (!ok) return;
    try {
      await post(`/api/agents/${s.host}/restart-container`, { container: s.container }, 60_000);
      toast(`${s.container} restarting`, 'ok');
    } catch (e) {
      if (SELF_CONTAINERS.has(s.container)) toast('Connection dropped — expected, that container serves this page. Reload in a few seconds.', 'warn');
      else toast(`Restart failed: ${(e as Error).message}`, 'crit');
    }
  }
</script>

<div class="launchpad">
  <div class="bar">
    <label class="search"><Search size={14} /><input class="input" placeholder="Search services, hosts…" bind:value={search} /></label>
    <div class="seg">
      <button class="seg-btn" class:active={groupBy === 'category'} onclick={() => (groupBy = 'category')}><LayoutGrid size={12} /> by category</button>
      <button class="seg-btn" class:active={groupBy === 'host'} onclick={() => (groupBy = 'host')}><Server size={12} /> by host</button>
    </div>
    <span class="faint num">{data ? `${up}/${data.services.length} up` : '…'}{data?.checked_at ? ` · probed ${relTime(data.checked_at)}` : ''}{q.isError ? ' · static catalog (backend without /api/services)' : ''}</span>
  </div>

  {#if down.length}
    <div class="downbar">
      <span class="t-crit">Down:</span>
      {#each down as s (s.id)}<a class="chip" data-s="crit" href={s.url} target={s.internal ? undefined : '_blank'} rel="noreferrer">{s.label}{s.probe_error ? ` · ${s.probe_error}` : ''}</a>{/each}
    </div>
  {/if}

  {#if favs.length}
    <div class="shead"><h2>Favourites</h2><span class="meta">star a tile to pin it here</span></div>
    <div class="grid-tiles">
      {#each favs as s (s.id)}{@render tile(s)}{/each}
    </div>
  {/if}

  {#each groups as [g, items] (g)}
    <div class="shead"><h2>{g}</h2><span class="meta">{items.length}</span></div>
    <div class="grid-tiles">
      {#each items as s (s.id)}{@render tile(s)}{/each}
    </div>
  {/each}
  {#if q.isLoading}<div class="spin"></div>{/if}
</div>

{#snippet tile(s: Service)}
  <div class="tile" data-s={s.state}>
    <a class="open" href={s.url} target={s.internal || s.url.startsWith('/') ? undefined : '_blank'} rel="noreferrer">
      <img src={iconUrl(s.icon)} alt="" width="34" height="34" />
      <span class="lbl">{s.label}</span>
      <span class="sub faint">{s.host ?? 'network'}{s.container_state ? ` · ${s.container_state}` : ''}{s.probe_status ? ` · ${s.probe_status}` : ''}</span>
    </a>
    <span class="dot" title={s.state === 'down' ? `down: ${s.probe_error ?? ''}` : s.state}></span>
    {#if s.update_available}<span class="chip upd" data-s="warn">update</span>{/if}
    <div class="acts">
      <button class="ic" class:fav={favIds.includes(s.id)} title="Favourite" onclick={() => toggleFav(s.id)}><Star size={13} /></button>
      {#if s.internalPage}<a class="ic" href={s.internalPage} title="Dashboard page"><LayoutGrid size={13} /></a>{/if}
      {#if s.container}<a class="ic" href="/logs" title="Logs (Dozzle)"><ScrollText size={13} /></a>{/if}
      {#if s.container && s.host && s.host !== 'opti'}<button class="ic" title="Restart container" onclick={() => restart(s)}><RotateCcw size={13} /></button>{/if}
      {#if !s.url.startsWith('/')}<a class="ic" href={s.url} target="_blank" rel="noreferrer" title="Open in new tab"><ExternalLink size={13} /></a>{/if}
    </div>
    {#if s.description}<span class="desc">{s.description}</span>{/if}
  </div>
{/snippet}

<style>
  .launchpad { display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .search { display: flex; align-items: center; gap: 6px; color: var(--ink-3); flex: 1; min-width: 200px; max-width: 420px; }
  .search .input { flex: 1; }
  .seg-btn { display: inline-flex; align-items: center; gap: 5px; }
  .downbar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 12px; }
  .grid-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .tile { position: relative; display: flex; flex-direction: column; gap: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 12px 10px 8px; min-width: 0; transition: border-color .15s, transform .15s; }
  .tile:hover { border-color: var(--accent-muted); transform: translateY(-2px); }
  .tile[data-s="down"] { border-color: var(--crit-muted); }
  .open { display: flex; flex-direction: column; align-items: center; gap: 6px; text-decoration: none; color: var(--ink-2); text-align: center; }
  .open:hover { color: var(--ink); text-decoration: none; }
  .open img { object-fit: contain; }
  .lbl { font-size: 12.5px; font-weight: 600; color: var(--ink); line-height: 1.25; }
  .sub { font-size: 10.5px; }
  .dot { position: absolute; top: 9px; right: 9px; width: 7px; height: 7px; border-radius: 99px; background: var(--surface-3); }
  .tile[data-s="up"] .dot { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .tile[data-s="down"] .dot { background: var(--crit); box-shadow: 0 0 6px var(--crit); }
  .chip.upd { position: absolute; top: 6px; left: 8px; }
  .acts { display: flex; justify-content: center; gap: 2px; opacity: .55; transition: opacity .15s; }
  .tile:hover .acts, .tile:focus-within .acts { opacity: 1; }
  @media (pointer: coarse) { .acts { opacity: 1; } }
  .ic { display: grid; place-items: center; width: 26px; height: 26px; border: 0; background: none; color: var(--ink-3); border-radius: var(--r-sm); cursor: pointer; text-decoration: none; }
  .ic:hover { color: var(--accent); background: var(--surface-2); }
  .ic.fav { color: var(--accent); }
  .desc { font-size: 10.5px; color: var(--ink-3); text-align: center; line-height: 1.35; display: none; }
  .tile:hover .desc { display: block; }
</style>
