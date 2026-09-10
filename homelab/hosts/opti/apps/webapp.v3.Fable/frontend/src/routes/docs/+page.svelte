<script lang="ts">
  // Docs — the homelab's written knowledge, read straight out of homelab-db.
  //
  // Peter's ask was to "eliminate all old documentation and formalize it in 1 central
  // place", readable by both of us. This page is the human half of that. The agent half
  // already existed: homelab-db indexes every runbook, rule, skill and generated report
  // into a `docs` table with full-text search beside it, which is what a session queries
  // before it probes a host.
  //
  // The important property is that this page has NO content of its own. It does not cache,
  // mirror, or restate anything. If a runbook is wrong here it is wrong in homelab-db, and
  // fixing it there fixes it in both places at once. That is the whole point of picking one
  // source of truth — a second copy that renders prettily is how the first copy goes stale.
  //
  // Freshness is therefore shown, never assumed: every document carries the mtime it was
  // indexed with, and anything older than a fortnight says so out loud.
  import { createQuery } from '@tanstack/svelte-query';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Search, FileText, BookOpen, Wrench, Bot, Sparkles, X } from '@lucide/svelte';
  import { get } from '$lib/api/client';
  import Markdown from '$lib/components/Markdown.svelte';
  import { relTime } from '$lib/format';

  interface DocRow {
    path: string; source_kind: string; title: string;
    sections: number; bytes: number; mtime: string | null;
  }
  interface DocsResp { ok: boolean; count: number; docs: DocRow[] }
  interface DocDetail {
    ok: boolean; path: string; source_kind: string; title: string; mtime: string | null;
    sections: { section: string | null; content: string }[];
  }

  // The kinds, in the order they earn attention. `rule` is first because it is the
  // material that is auto-loaded into every session — if it is wrong, everything
  // downstream of it is wrong too.
  const KINDS = [
    { id: 'rule',      label: 'Rules',     icon: Sparkles, blurb: 'Auto-loaded into every agent session.' },
    { id: 'runbook',   label: 'Runbooks',  icon: BookOpen, blurb: 'Per-host and per-subsystem reference, read on demand.' },
    { id: 'skill',     label: 'Skills',    icon: Wrench,   blurb: 'Procedures an agent follows for a named task.' },
    { id: 'generated', label: 'Generated', icon: Bot,      blurb: 'Machine-written, refreshed nightly. Never hand-edit.' },
    { id: 'agent-doc', label: 'Agent docs', icon: FileText, blurb: 'Reports the collectors publish for people to read.' },
    { id: 'note',      label: 'Notes',     icon: FileText, blurb: 'Everything else.' },
  ];

  const docs = createQuery(() => ({
    queryKey: ['hldb', 'docs'],
    queryFn: () => get<DocsResp>('/api/hldb/docs', 25_000),
    staleTime: 5 * 60_000,
    retry: 0,
  }));

  // URL is the state, so a document is linkable and the back button behaves.
  let openPath = $derived(page.url.searchParams.get('doc') || '');
  let q = $state('');
  let kindFilter = $state<string | null>(null);

  const detail = createQuery(() => ({
    queryKey: ['hldb', 'doc', openPath],
    queryFn: () => get<DocDetail>(`/api/hldb/docs/${openPath}`, 25_000),
    enabled: !!openPath,
    staleTime: 5 * 60_000,
    retry: 0,
  }));

  function open(path: string) {
    const u = new URL(page.url);
    u.searchParams.set('doc', path);
    goto(u.pathname + u.search, { noScroll: false, keepFocus: true });
  }
  function close() {
    const u = new URL(page.url);
    u.searchParams.delete('doc');
    goto(u.pathname + u.search, { keepFocus: true });
  }

  let all = $derived(docs.data?.docs ?? []);

  let filtered = $derived.by(() => {
    const needle = q.trim().toLowerCase();
    return all.filter((d) => {
      if (kindFilter && d.source_kind !== kindFilter) return false;
      if (!needle) return true;
      return d.title.toLowerCase().includes(needle) || d.path.toLowerCase().includes(needle);
    });
  });

  // Group into the KINDS order, dropping empty groups, and appending any kind the
  // database knows about that this file does not — a new source_kind should show up
  // on its own rather than silently vanish from the shelf.
  let groups = $derived.by(() => {
    const seen = new Set(KINDS.map((k) => k.id));
    const extra = [...new Set(filtered.map((d) => d.source_kind))].filter((k) => !seen.has(k));
    const order = [...KINDS, ...extra.map((id) => ({ id, label: id, icon: FileText, blurb: '' }))];
    return order
      .map((k) => ({ ...k, rows: filtered.filter((d) => d.source_kind === k.id) }))
      .filter((g) => g.rows.length > 0);
  });

  let counts = $derived.by(() => {
    const m: Record<string, number> = {};
    for (const d of all) m[d.source_kind] = (m[d.source_kind] ?? 0) + 1;
    return m;
  });

  const STALE_DAYS = 14;
  const isStale = (mtime: string | null) => {
    if (!mtime) return false;
    const t = Date.parse(mtime);
    return Number.isFinite(t) && Date.now() - t > STALE_DAYS * 86_400_000;
  };
  const kb = (n: number) => (n < 1024 ? `${n} B` : `${Math.round(n / 1024)} KB`);
  const shortPath = (p: string) => p.replace(/^.*?(homelab\/|generated-docs\/)/, '$1');

  // Sections are stored split; the reader wants one continuous document.
  let body = $derived((detail.data?.sections ?? []).map((s) => s.content).join('\n\n'));
</script>

<div class="docs-page">
  {#if openPath}
    <!-- ── Reader ─────────────────────────────────────────────────────────── -->
    <article class="reader">
      <header class="rhead">
        <button class="back" onclick={close}><X size={14} aria-hidden="true" /> Back to all docs</button>
        {#if detail.data}
          <h1>{detail.data.title}</h1>
          <p class="meta">
            <span class="kind" data-k={detail.data.source_kind}>{detail.data.source_kind}</span>
            <code>{shortPath(detail.data.path)}</code>
            {#if detail.data.mtime}
              <span class:stale={isStale(detail.data.mtime)}>indexed {relTime(detail.data.mtime)}</span>
            {/if}
          </p>
          {#if isStale(detail.data.mtime)}
            <p class="warnbar">
              This document has not been re-indexed in over {STALE_DAYS} days. It may describe
              the homelab as it was, not as it is — check it against the Monitor or Topology
              before acting on it.
            </p>
          {/if}
        {/if}
      </header>

      {#if detail.isPending}
        <p class="state">loading…</p>
      {:else if detail.isError}
        <p class="state err">
          Could not read this document: {(detail.error as Error).message}.
          homelab-db may be stopped.
        </p>
      {:else if detail.data}
        <div class="body"><Markdown source={body} /></div>
      {/if}
    </article>
  {:else}
    <!-- ── Shelf ──────────────────────────────────────────────────────────── -->
    <header class="head">
      <div class="intro">
        <h1>Docs</h1>
        <p>
          Every runbook, rule, skill and generated report, read live from homelab-db on opti.
          This page stores nothing of its own — correct a document at its source and it is
          corrected here too.
        </p>
      </div>
      <label class="search">
        <Search size={14} aria-hidden="true" />
        <input placeholder="Filter by title or path…" bind:value={q} />
      </label>
    </header>

    <div class="chips">
      <button class="chip" class:on={kindFilter === null} onclick={() => (kindFilter = null)}>
        All <b>{all.length}</b>
      </button>
      {#each KINDS as k (k.id)}
        {#if counts[k.id]}
          <button class="chip" class:on={kindFilter === k.id} onclick={() => (kindFilter = kindFilter === k.id ? null : k.id)}>
            {k.label} <b>{counts[k.id]}</b>
          </button>
        {/if}
      {/each}
    </div>

    {#if docs.isPending}
      <p class="state">loading the shelf…</p>
    {:else if docs.isError}
      <p class="state err">
        homelab-db is unreachable: {(docs.error as Error).message}.
        Nothing is cached here on purpose, so there is nothing to show until it returns.
      </p>
    {:else if filtered.length === 0}
      <p class="state">Nothing matches “{q}”.</p>
    {:else}
      {#each groups as g (g.id)}
        {@const Icon = g.icon}
        <section class="group">
          <h2><Icon size={15} aria-hidden="true" /> {g.label} <span class="n">{g.rows.length}</span></h2>
          {#if g.blurb}<p class="blurb">{g.blurb}</p>{/if}
          <div class="rows">
            {#each g.rows as d (d.path)}
              <button class="row" onclick={() => open(d.path)}>
                <span class="t">{d.title}</span>
                <code class="p">{shortPath(d.path)}</code>
                <span class="s">{d.sections} §</span>
                <span class="s">{kb(d.bytes)}</span>
                <span class="s" class:stale={isStale(d.mtime)}>
                  {d.mtime ? relTime(d.mtime) : '—'}
                </span>
              </button>
            {/each}
          </div>
        </section>
      {/each}
    {/if}
  {/if}
</div>

<style>
  .docs-page { max-width: 1000px; }

  .head { display: flex; gap: var(--s4); align-items: flex-start; flex-wrap: wrap; margin-bottom: var(--s4); }
  .intro { flex: 1 1 380px; }
  .intro h1 { font-size: var(--fs-xl); margin: 0 0 var(--s2); }
  .intro p { margin: 0; color: var(--ink-2); font-size: var(--fs-sm); line-height: 1.55; max-width: 62ch; }

  .search { display: flex; align-items: center; gap: var(--s2); flex: 0 1 280px;
            background: var(--surface); border: 1px solid var(--border); border-radius: var(--r);
            padding: 0 var(--s3); color: var(--ink-3); }
  .search input { flex: 1; background: none; border: 0; outline: none; color: var(--ink);
                  font: inherit; font-size: var(--fs-sm); padding: var(--s2) 0; min-width: 0; }

  .chips { display: flex; gap: var(--s2); flex-wrap: wrap; margin-bottom: var(--s5); }
  .chip { background: var(--surface); border: 1px solid var(--border); color: var(--ink-2);
          border-radius: 999px; padding: 3px var(--s3); font-size: var(--fs-xs); cursor: pointer; }
  .chip b { color: var(--ink-3); font-weight: 600; margin-left: 2px; }
  .chip:hover { border-color: var(--border-2); color: var(--ink); }
  .chip.on { background: var(--accent-dim); border-color: var(--accent-muted); color: var(--accent); }
  .chip.on b { color: var(--accent); }

  .group { margin-bottom: var(--s6); }
  .group h2 { display: flex; align-items: center; gap: var(--s2); font-size: var(--fs-md);
              margin: 0 0 2px; color: var(--ink); }
  .group h2 .n { font-size: var(--fs-xs); color: var(--ink-3); font-weight: 400; }
  .blurb { margin: 0 0 var(--s3); font-size: var(--fs-xs); color: var(--ink-3); }

  .rows { display: flex; flex-direction: column; border: 1px solid var(--border);
          border-radius: var(--r); overflow: hidden; }
  .row { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr) auto auto auto;
         gap: var(--s3); align-items: baseline; text-align: left; width: 100%;
         background: var(--surface); border: 0; border-bottom: 1px solid var(--border);
         padding: var(--s3); cursor: pointer; color: var(--ink); font: inherit; }
  .row:last-child { border-bottom: 0; }
  .row:hover { background: var(--surface-2); }
  .row .t { font-size: var(--fs-sm); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .p { font-family: var(--mono); font-size: var(--fs-xs); color: var(--ink-3);
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .s { font-size: var(--fs-xs); color: var(--ink-3); font-variant-numeric: tabular-nums;
            justify-self: end; white-space: nowrap; }
  /* Specificity matters here: `.row .s` is two selectors deep, so a bare `.stale`
     loses to it and the warning silently never paints. Match the depth. */
  .row .s.stale, .meta .stale { color: var(--warn); }

  .state { color: var(--ink-3); font-size: var(--fs-sm); padding: var(--s5) 0; }
  .state.err { color: var(--crit); }

  /* ── Reader ── */
  .reader { max-width: 78ch; }
  .rhead { margin-bottom: var(--s5); }
  .back { display: inline-flex; align-items: center; gap: 6px; background: none; border: 0;
          color: var(--ink-3); font: inherit; font-size: var(--fs-xs); cursor: pointer;
          padding: 0; margin-bottom: var(--s4); }
  .back:hover { color: var(--accent); }
  .rhead h1 { font-size: var(--fs-xl); margin: 0 0 var(--s2); line-height: 1.25; }
  .meta { display: flex; gap: var(--s3); flex-wrap: wrap; align-items: center; margin: 0;
          font-size: var(--fs-xs); color: var(--ink-3); }
  .meta code { font-family: var(--mono); }
  .kind { background: var(--brand-dim); color: var(--brand); border-radius: 999px;
          padding: 1px var(--s2); font-size: var(--fs-xs); }
  .warnbar { margin: var(--s4) 0 0; padding: var(--s3); border-radius: var(--r);
             background: var(--warn-dim); border: 1px solid var(--warn-muted);
             color: var(--warn); font-size: var(--fs-xs); line-height: 1.55; }

  @media (max-width: 780px) {
    .row { grid-template-columns: 1fr auto; }
    .row .p, .row .s:nth-of-type(2) { display: none; }
  }
</style>
