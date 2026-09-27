<script lang="ts">
  // Asset Library: E:\Assets on the workstation (ptm), browsed live and read-only. The
  // folder tree sits beside the open folder; a model opens in the library's own 3D
  // inspector, an image full size, a text file as text. Everything is in the URL
  // (?path=…&file=…, ?q=…), so each view is a link and Back works.
  // Folders and search come through /api/assets (Pertal asks ptm, hard timeouts); file
  // bytes and thumbnails load from /asset-files and /asset-thumbs, which nginx passes
  // straight to ptm. While ptm is off, asleep or in Linux the page says so.
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { untrack } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import {
    ArrowLeft, Box, ChevronLeft, ChevronRight, Download, ExternalLink, FileCode, FileText,
    File as FileIcon, Folder, FolderTree, Globe, Image as ImageIcon, LayoutGrid, List,
    RefreshCw, Search, WifiOff,
  } from '@lucide/svelte';
  import Age from '$lib/components/Age.svelte';
  import FolderTreeNav from '$lib/components/assets/FolderTree.svelte';
  import ModelViewer from '$lib/components/assets/ModelViewer.svelte';
  import ImageView from '$lib/components/assets/ImageView.svelte';
  import TextView from '$lib/components/assets/TextView.svelte';
  import { api, type AssetDir, type AssetFile, type AssetHit, type AssetListing, type AssetStatus } from '$lib/api';
  import { live } from '$lib/live.svelte';
  import { bytes, clock } from '$lib/format';
  import {
    ancestors, baseName, ext, fileUrl, GALLERIES, hasThumb, join, kindOf, parentOf, thumbUrl, type AssetKind,
  } from '$lib/assets';

  // ── ptm's asset server: refetched whenever its snapshot is (every 30 s) ──
  let status = $state<AssetStatus | null>(null);
  const stamp = $derived(live.snapshots['assets:server']?.fetched_at);
  $effect(() => { void stamp; api.assets.status().then((s) => (status = s)).catch(() => {}); });
  const offline = $derived(status?.online === false);
  const rootLabel = $derived(status?.server?.root ?? 'E:\\Assets');

  // ── where we are: all of it in the URL ──
  const path = $derived((page.url.searchParams.get('path') ?? '').replace(/^\/+|\/+$/g, ''));
  const fileName = $derived(page.url.searchParams.get('file'));
  const q = $derived((page.url.searchParams.get('q') ?? '').trim());

  function href(p: string, file?: string | null, query?: string | null) {
    const sp = new URLSearchParams();
    if (p) sp.set('path', p);
    if (file) sp.set('file', file);
    if (query) sp.set('q', query);
    const s = sp.toString().replaceAll('%2F', '/'); // '/' is legal in a query; keeps links readable
    return s ? `/assets?${s}` : '/assets';
  }
  const iso = (t: number) => new Date(t * 1000).toISOString();

  // ── folders, read from ptm once each (Refresh reads again) ──
  let listings = $state.raw<Record<string, AssetListing>>({});
  let errors = $state.raw<Record<string, string>>({});
  const busy = new SvelteSet<string>();
  const expanded = new SvelteSet<string>(['']);
  const broken = new SvelteSet<string>(); // thumbnails that failed: show an icon instead

  const without = (o: Record<string, string>, k: string) => Object.fromEntries(Object.entries(o).filter(([x]) => x !== k));

  async function ensure(rel: string, force = false) {
    if (busy.has(rel) || (!force && listings[rel])) return;
    busy.add(rel);
    try {
      const l = await api.assets.list(rel); // await first: several folders load at once, so
      listings = { ...listings, [rel]: l }; // spread the map as it is *now*, not as it was
      if (errors[rel]) errors = without(errors, rel);
    } catch (e) {
      errors = { ...errors, [rel]: (e as Error).message };
    } finally {
      busy.delete(rel);
    }
  }

  function toggle(rel: string) {
    if (expanded.has(rel)) expanded.delete(rel);
    else { expanded.add(rel); void ensure(rel); }
  }

  let treeOpen = $state(false); // phones: the tree folds away under its Folders button

  // Opening a folder from anywhere (link, search, Back) opens the tree down to it.
  $effect(() => {
    const p = path;
    untrack(() => {
      for (const a of ancestors(p)) { expanded.add(a); void ensure(a); }
      treeOpen = false;
      limit = 240;
    });
  });

  // ptm came back: retry what failed while it was away, and the thumbnails.
  let wasOffline = false;
  $effect(() => {
    const on = status?.online;
    untrack(() => {
      if (on === false) wasOffline = true;
      if (on && wasOffline) {
        wasOffline = false;
        broken.clear();
        for (const rel of Object.keys(errors)) void ensure(rel, true);
      }
    });
  });

  // ── the open folder ──
  const current = $derived(listings[path] ?? null);
  const loading = $derived(!current && (busy.has(path) || (!errors[path] && !offline)));
  const error = $derived(current ? null : (errors[path] ?? null));

  type Show = 'all' | 'model' | 'image' | 'other';
  let show = $state<Show>('all');
  let viewChoice = $state<'auto' | 'grid' | 'list'>('auto');
  let limit = $state(240);

  const group = (k: AssetKind): Show => (k === 'model' || k === 'image' ? k : 'other');
  const counts = $derived.by(() => {
    const c = { model: 0, image: 0, other: 0 };
    for (const f of current?.files ?? []) c[group(kindOf(f.name)) as 'model' | 'image' | 'other']++;
    return c;
  });
  // The filter only exists where there is a mix; elsewhere it is off, so nothing can hide.
  const mixed = $derived([counts.model, counts.image, counts.other].filter(Boolean).length > 1);
  const filter = $derived(mixed ? show : 'all');
  const files = $derived((current?.files ?? []).filter((f) => filter === 'all' || group(kindOf(f.name)) === filter));
  const shownFiles = $derived(files.slice(0, limit));
  const autoView = $derived(
    current && (current.dirs.some((d) => d.cover) || current.files.some((f) => kindOf(f.name) === 'model' || hasThumb(f.name)))
      ? 'grid' : 'list',
  );
  const view = $derived(viewChoice === 'auto' ? autoView : viewChoice);
  const totalBytes = $derived((current?.files ?? []).reduce((n, f) => n + f.size, 0));
  const plural = (n: number, one: string) => `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;
  function dirCounts(d: AssetDir) {
    if (d.dirs == null || d.files == null) return '';
    if (!d.dirs && !d.files) return 'empty';
    return [d.dirs ? plural(d.dirs, 'folder') : '', d.files ? plural(d.files, 'file') : ''].filter(Boolean).join(' · ');
  }
  const ICONS = { model: Box, image: ImageIcon, text: FileText, page: Globe, other: FileIcon } as const;
  const iconFor = (name: string) => (ext(name) === 'json' ? FileCode : ICONS[kindOf(name)]);

  // ── the open file ──
  const selected = $derived(fileName && current ? (current.files.find((f) => f.name === fileName) ?? null) : null);
  const selKind = $derived(selected ? kindOf(selected.name) : null);
  const selRel = $derived(selected ? join(path, selected.name) : '');
  const peers = $derived(selected && current ? current.files.filter((f) => kindOf(f.name) === selKind) : []);
  const pos = $derived(selected ? peers.findIndex((f) => f.name === selected.name) : -1);
  const prevHref = $derived(pos > 0 ? href(path, peers[pos - 1].name) : null);
  const nextHref = $derived(pos >= 0 && pos < peers.length - 1 ? href(path, peers[pos + 1].name) : null);

  function onKey(e: KeyboardEvent) {
    if (!selected || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    // Typing, and the 3D stage's own arrow-key orbit, keep their keys.
    if (e.target instanceof Element && e.target.closest('input, select, textarea, [contenteditable], model-viewer, dialog')) return;
    const to = e.key === 'Escape' ? href(path) : e.key === 'ArrowLeft' ? prevHref : e.key === 'ArrowRight' ? nextHref : null;
    if (to) { e.preventDefault(); void goto(to); }
  }

  // ── search: ptm's in-memory index of every name under E:\Assets ──
  let query = $state('');
  $effect(() => { const v = q; untrack(() => { if (v !== query.trim()) query = v; }); }); // Back/forward
  let timer: ReturnType<typeof setTimeout> | undefined;
  function runSearch(now = false) {
    clearTimeout(timer);
    const go = () => goto(href(path, null, query.trim() || null), { replaceState: true, keepFocus: true, noScroll: true });
    if (now) void go(); else timer = setTimeout(go, 300);
  }
  let results = $state.raw<{ total: number; results: AssetHit[]; building: boolean } | null>(null);
  let searchErr = $state<string | null>(null);
  let searching = $state(false);
  $effect(() => {
    const text = q;
    if (!text) { results = null; searchErr = null; return; }
    searching = true;
    api.assets.search(text)
      .then((r) => { if (text === q) { results = r; searchErr = null; } })
      .catch((e) => { if (text === q) { results = null; searchErr = (e as Error).message; } })
      .finally(() => { if (text === q) searching = false; });
  });
  const hitHref = (h: AssetHit) => (h.dir ? href(h.path) : href(parentOf(h.path), h.name));
</script>

<svelte:head><title>{selected ? `${selected.name} · ` : ''}Asset Library · Pertal</title></svelte:head>
<svelte:window onkeydown={onKey} />

<div class="head">
  <h1>Asset Library</h1>
  <span class="where">
    <span class="dot" class:offline title={offline ? 'ptm is offline' : 'ptm is serving the library'}></span>
    ptm · {rootLabel}
    {#if status?.server?.index?.built_at}
      · {status.server.index.files.toLocaleString()} files · {bytes(status.server.index.bytes)}
    {:else if status?.server?.index?.building}
      · indexing…
    {/if}
  </span>
  <form class="search" role="search" onsubmit={(e) => { e.preventDefault(); runSearch(true); }}>
    <Search size={14} />
    <input class="field" type="search" placeholder="Search names under {rootLabel}…" aria-label="Search the asset library"
      bind:value={query} oninput={() => runSearch()} />
  </form>
</div>

{#if offline && status}
  <div class="banner">
    <WifiOff size={16} />
    <div>
      <strong>ptm is offline.</strong> {status.error}.
      {#if status.last_seen_at}Last seen <Age at={status.last_seen_at} />.{/if}
      The library is read live from {rootLabel}, so it comes back when ptm does.
    </div>
  </div>
{/if}

{#if status?.online && GALLERIES.some((g) => status?.server?.roots.includes(g.root))}
  <div class="galleries">
    <span class="faint">The library's own pages:</span>
    {#each GALLERIES.filter((g) => status?.server?.roots.includes(g.root)) as g (g.path)}
      <a href={fileUrl(g.path)} target="_blank" rel="noreferrer">{g.label} <ExternalLink size={12} /></a>
    {/each}
  </div>
{/if}

<!-- Phones only: the tree folds away and opens right under this button. -->
<button class="btn treebtn" aria-expanded={treeOpen} onclick={() => (treeOpen = !treeOpen)}><FolderTree size={14} /> Folders</button>

<div class="lib" class:tree-open={treeOpen}>
  <aside class="panel treepane">
    <FolderTreeNav {rootLabel} {listings} {expanded} {busy} {errors} current={path} {href} ontoggle={toggle} />
  </aside>

  <section class="content">
    <div class="bar">
      <nav class="crumbs" aria-label="Location">
        {#each ancestors(path) as a, i (a)}
          {#if i > 0}<ChevronRight size={12} />{/if}
          <a href={href(a)} aria-current={a === path && !selected && !q ? 'page' : undefined}>{i === 0 ? rootLabel : baseName(a)}</a>
        {/each}
      </nav>
      {#if current && !selected && !q}
        <span class="faint small">
          {plural(current.dirs.length, 'folder')} · {plural(current.files.length, 'file')}{#if totalBytes} · {bytes(totalBytes)}{/if}
        </span>
        <span class="tools">
          {#if mixed}
            <span class="seg" role="group" aria-label="Show">
              <button aria-pressed={filter === 'all'} onclick={() => (show = 'all')}>All</button>
              {#if counts.model}<button aria-pressed={filter === 'model'} onclick={() => (show = 'model')}>3D {counts.model}</button>{/if}
              {#if counts.image}<button aria-pressed={filter === 'image'} onclick={() => (show = 'image')}>Images {counts.image}</button>{/if}
              {#if counts.other}<button aria-pressed={filter === 'other'} onclick={() => (show = 'other')}>Other {counts.other}</button>{/if}
            </span>
          {/if}
          <span class="seg" role="group" aria-label="View">
            <button aria-pressed={view === 'grid'} aria-label="Grid" title="Grid" onclick={() => (viewChoice = 'grid')}><LayoutGrid size={14} /></button>
            <button aria-pressed={view === 'list'} aria-label="List" title="List" onclick={() => (viewChoice = 'list')}><List size={14} /></button>
          </span>
          <button class="btn icon" title="Read this folder again" aria-label="Refresh" onclick={() => ensure(path, true)}>
            <RefreshCw size={14} class={busy.has(path) ? 'spin' : ''} />
          </button>
        </span>
      {/if}
    </div>

    {#if q}
      <!-- Search results replace the folder until the search is cleared. -->
      <section class="panel">
        <div class="panel-head">
          <h2>Search: “{q}”</h2>
          {#if results}<span class="faint small">{results.total > results.results.length ? `first ${results.results.length} of ${results.total.toLocaleString()}` : plural(results.total, 'match')}</span>{/if}
          <a class="btn ghost" href={href(path)} onclick={() => (query = '')}>Clear</a>
        </div>
        {#if searchErr}
          <p class="empty">{searchErr}</p>
        {:else if !results}
          <p class="empty">{searching ? 'Searching…' : ''}</p>
        {:else if !results.results.length}
          <p class="empty">Nothing under {rootLabel} has a name containing every word of “{q}”.</p>
        {:else}
          <div class="rows">
            {#each results.results as h (h.path)}
              {@const Icon = h.dir ? Folder : iconFor(h.name)}
              <a class="row hit" href={hitHref(h)}>
                <Icon size={15} />
                <span class="hname">{h.name}<span class="faint hpath">{parentOf(h.path) || rootLabel}</span></span>
                <span class="faint small">{h.dir ? 'folder' : bytes(h.size)}</span>
              </a>
            {/each}
          </div>
        {/if}
      </section>
    {:else if fileName}
      {#if selected}
        {@const Icon = iconFor(selected.name)}
        <div class="vbar">
          <a class="btn icon" href={href(path)} title="Back to the folder (Esc)" aria-label="Back to the folder"><ArrowLeft size={16} /></a>
          <div class="vtitle">
            <strong title={selected.name}>{selected.name}</strong>
            <span class="faint small">{bytes(selected.size)} · modified {clock(iso(selected.mtime))}</span>
          </div>
          {#if peers.length > 1}
            <span class="pager">
              {#if prevHref}<a class="btn icon" href={prevHref} title="Previous (←)" aria-label="Previous"><ChevronLeft size={16} /></a>
              {:else}<button class="btn icon" disabled aria-label="Previous"><ChevronLeft size={16} /></button>{/if}
              <span class="faint small">{pos + 1} / {peers.length}</span>
              {#if nextHref}<a class="btn icon" href={nextHref} title="Next (→)" aria-label="Next"><ChevronRight size={16} /></a>
              {:else}<button class="btn icon" disabled aria-label="Next"><ChevronRight size={16} /></button>{/if}
            </span>
          {/if}
          <a class="btn" href={fileUrl(selRel)} download={selected.name} title="Download"><Download size={14} /><span class="lbl">Download</span></a>
          <a class="btn" href={fileUrl(selRel, selected.mtime)} target="_blank" rel="noreferrer" title="Open in a new tab"><ExternalLink size={14} /><span class="lbl">Open</span></a>
        </div>
        {#if selKind === 'model'}
          <ModelViewer rel={selRel} file={selected} siblings={current?.files ?? []} />
        {:else if selKind === 'image'}
          <ImageView rel={selRel} file={selected} />
        {:else if selKind === 'text'}
          <TextView rel={selRel} file={selected} />
        {:else if selKind === 'page'}
          <iframe class="pageframe" src={fileUrl(selRel, selected.mtime)} title={selected.name}></iframe>
        {:else}
          <div class="panel other">
            <Icon size={40} strokeWidth={1.25} />
            <div>
              <strong>{ext(selected.name).toUpperCase() || 'File'} file</strong>
              <p class="muted">No preview for this kind of file. Download it to open it here, or open it on ptm.</p>
            </div>
          </div>
        {/if}
      {:else if current}
        <p class="panel empty">“{fileName}” is not in this folder any more. <a href={href(path)}>Back to the folder</a></p>
      {:else if error}
        <p class="panel empty">{error}</p>
      {:else}
        <p class="panel empty">Reading the folder on ptm…</p>
      {/if}
    {:else if current}
      {#if !current.dirs.length && !current.files.length}
        <p class="panel empty">This folder is empty.</p>
      {:else if view === 'grid'}
        <div class="grid">
          {#each current.dirs as d (d.name)}
            <a class="tile" href={href(join(path, d.name))}>
              <div class="pic">
                {#if d.cover && !broken.has(d.cover)}
                  <img src={thumbUrl(d.cover, 320)} alt="" loading="lazy" decoding="async" onerror={() => broken.add(d.cover!)} />
                {:else}
                  <Folder size={38} strokeWidth={1.25} />
                {/if}
              </div>
              <div class="cap">
                <span class="nm" title={d.name}><Folder size={12} />{d.name}</span>
                <span class="meta">{dirCounts(d)}</span>
              </div>
            </a>
          {/each}
          {#each shownFiles as f (f.name)}
            {@const k = kindOf(f.name)}
            {@const rel = join(path, f.name)}
            {@const pic = k === 'model' ? (f.preview ?? null) : hasThumb(f.name) ? rel : null}
            {@const Icon = iconFor(f.name)}
            <a class="tile" href={href(path, f.name)}>
              <div class="pic">
                {#if pic && !broken.has(pic)}
                  <img src={k === 'model' ? thumbUrl(pic, 320) : thumbUrl(pic, 320, f.mtime)} alt="" loading="lazy" decoding="async" onerror={() => pic && broken.add(pic)} />
                {:else if ext(f.name) === 'svg'}
                  <img src={fileUrl(rel, f.mtime)} alt="" loading="lazy" />
                {:else}
                  <Icon size={34} strokeWidth={1.25} />
                {/if}
                {#if k === 'model'}<span class="tag">3D</span>{:else if !pic}<span class="tag">{ext(f.name).toUpperCase() || 'FILE'}</span>{/if}
              </div>
              <div class="cap">
                <span class="nm" title={f.name}>{f.name}</span>
                <span class="meta">{bytes(f.size)}</span>
              </div>
            </a>
          {/each}
        </div>
      {:else}
        <div class="panel rows">
          {#each current.dirs as d (d.name)}
            <a class="row lrow" href={href(join(path, d.name))}>
              <Folder size={15} /><span class="nm">{d.name}</span>
              <span class="faint small">{dirCounts(d)}</span><span class="faint small when">{clock(iso(d.mtime))}</span>
            </a>
          {/each}
          {#each shownFiles as f (f.name)}
            {@const Icon = iconFor(f.name)}
            <a class="row lrow" href={href(path, f.name)}>
              <Icon size={15} /><span class="nm">{f.name}</span>
              <span class="faint small">{bytes(f.size)}</span><span class="faint small when">{clock(iso(f.mtime))}</span>
            </a>
          {/each}
        </div>
      {/if}
      {#if files.length > shownFiles.length}
        <button class="btn more" onclick={() => (limit += 480)}>Show {Math.min(480, files.length - shownFiles.length)} more of {files.length - shownFiles.length}</button>
      {/if}
    {:else if error}
      <div class="panel empty">
        <p>{error}</p>
        <button class="btn" onclick={() => ensure(path, true)}><RefreshCw size={14} /> Try again</button>
      </div>
    {:else if loading}
      <p class="panel empty">Reading the folder on ptm…</p>
    {/if}
  </section>
</div>

<style>
  .head { display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .where { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-3); font-size: var(--fs-sm); }
  .search { margin-left: auto; position: relative; display: flex; align-items: center; width: min(360px, 100%); }
  .search :global(svg) { position: absolute; left: 9px; color: var(--ink-3); pointer-events: none; }
  .search input { width: 100%; padding-left: 28px; }
  .banner {
    display: flex; align-items: flex-start; gap: 10px; margin-bottom: var(--s3); padding: 10px 14px;
    border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); font-size: var(--fs-sm);
  }
  .banner :global(svg) { color: var(--warn); flex: none; margin-top: 1px; }
  .banner strong { color: var(--warn); }
  .galleries { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; margin-bottom: var(--s3); font-size: var(--fs-sm); }
  .galleries a { display: inline-flex; align-items: center; gap: 4px; }

  .lib { display: grid; grid-template-columns: 272px minmax(0, 1fr); gap: var(--s3); align-items: start; }
  .treepane {
    position: sticky; top: calc(var(--topbar-h) + var(--s3)); max-height: calc(100vh - var(--topbar-h) - 2 * var(--s3));
    overflow: auto; padding: 2px 4px;
  }
  .content { min-width: 0; display: flex; flex-direction: column; gap: var(--s3); }

  .bar { display: flex; align-items: center; gap: var(--s2) var(--s3); flex-wrap: wrap; min-height: 30px; }
  .treebtn { display: none; }
  .crumbs { display: flex; align-items: center; flex-wrap: wrap; gap: 2px 4px; min-width: 0; flex: 1 1 260px; font-size: var(--fs-md); }
  .crumbs :global(svg) { color: var(--ink-3); flex: none; }
  .crumbs a { color: var(--ink-2); overflow-wrap: anywhere; }
  .crumbs a[aria-current='page'] { color: var(--ink); font-weight: 600; }
  .tools { display: inline-flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
  .seg button { display: inline-flex; align-items: center; gap: 4px; }
  .small { font-size: var(--fs-xs); }
  .bar :global(.spin) { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--s2); }
  .tile {
    display: flex; flex-direction: column; min-width: 0; overflow: hidden;
    border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); color: var(--ink);
  }
  .tile:hover { border-color: var(--border-2); background: var(--surface-2); text-decoration: none; }
  .pic { position: relative; aspect-ratio: 1; display: flex; align-items: center; justify-content: center; background: var(--bg-inset); color: var(--ink-3); }
  .pic img { width: 100%; height: 100%; object-fit: contain; }
  .tag {
    position: absolute; top: 6px; left: 6px; padding: 1px 6px; border-radius: 999px;
    border: 1px solid var(--border-2); background: var(--surface); color: var(--ink-2);
    font-size: 10px; font-weight: 700; letter-spacing: .04em;
  }
  .cap { display: flex; flex-direction: column; gap: 1px; padding: 6px 8px 7px; min-width: 0; }
  .nm { display: flex; align-items: center; gap: 5px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-sm); }
  .nm :global(svg) { flex: none; color: var(--ink-3); }
  .meta { font-size: var(--fs-xs); color: var(--ink-3); }
  .lrow { grid-template-columns: auto minmax(0, 1fr) auto auto; font-size: var(--fs-sm); }
  .lrow :global(svg) { color: var(--ink-3); }
  .lrow .nm { display: block; }
  .when { min-width: 92px; text-align: right; }
  .more { align-self: center; }

  .hit { grid-template-columns: auto minmax(0, 1fr) auto; font-size: var(--fs-sm); }
  .hit :global(svg) { color: var(--ink-3); }
  .hname { display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
  .hpath { font-size: var(--fs-xs); }

  .vbar { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
  .vtitle { display: flex; flex-direction: column; min-width: 0; flex: 1 1 200px; }
  .vtitle strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pager { display: inline-flex; align-items: center; gap: 6px; }
  .pageframe { width: 100%; height: min(76vh, 860px); border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--bg-inset); }
  .other { display: flex; align-items: center; gap: var(--s4); padding: var(--s5); color: var(--ink-3); }
  .other strong { color: var(--ink); }
  .other p { margin: 4px 0 0; }

  @media (max-width: 900px) {
    .lib { grid-template-columns: minmax(0, 1fr); }
    .treepane { display: none; position: static; max-height: 55vh; }
    .lib.tree-open .treepane { display: block; }
    .treebtn { display: inline-flex; margin-bottom: var(--s3); }
    .search { margin-left: 0; width: 100%; }
  }
  @media (max-width: 720px) {
    .vbar .lbl { display: none; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); }
    .lrow { grid-template-columns: auto minmax(0, 1fr) auto; }
    .lrow .when { display: none; }
  }
</style>
