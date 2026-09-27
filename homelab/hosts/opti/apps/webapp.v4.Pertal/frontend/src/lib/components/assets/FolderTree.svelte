<script lang="ts">
  // The folder tree beside the Asset Library: folders only, read one level at a time as
  // they are expanded. A name is a link to that folder; the chevron only expands it.
  import { ChevronRight, Folder, FolderOpen, HardDrive, LoaderCircle } from '@lucide/svelte';
  import type { SvelteSet } from 'svelte/reactivity';
  import type { AssetListing } from '$lib/api';
  import { join } from '$lib/assets';

  let { rootLabel, listings, expanded, busy, errors, current, href, ontoggle }: {
    rootLabel: string;
    listings: Record<string, AssetListing>;
    expanded: SvelteSet<string>;
    busy: SvelteSet<string>;
    errors: Record<string, string>;
    current: string;
    href: (rel: string) => string;
    ontoggle: (rel: string) => void;
  } = $props();

  type Row = { rel: string; name: string; depth: number; kids: boolean | null; open: boolean };
  const rows = $derived.by(() => {
    const out: Row[] = [{ rel: '', name: rootLabel, depth: 0, kids: true, open: expanded.has('') }];
    const walk = (rel: string, depth: number) => {
      for (const d of listings[rel]?.dirs ?? []) {
        const r = join(rel, d.name);
        const open = expanded.has(r);
        out.push({ rel: r, name: d.name, depth, kids: d.dirs == null ? null : d.dirs > 0, open });
        if (open) walk(r, depth + 1);
      }
    };
    if (expanded.has('')) walk('', 1);
    return out;
  });
</script>

<nav class="tree" aria-label="Folders">
  {#each rows as r (r.rel)}
    <div class="node" class:active={r.rel === current} style="--depth: {r.depth}">
      {#if r.kids !== false}
        <button class="chev" class:open={r.open} aria-expanded={r.open}
          aria-label="{r.open ? 'Collapse' : 'Expand'} {r.name}" onclick={() => ontoggle(r.rel)}>
          {#if r.open && busy.has(r.rel)}<LoaderCircle size={13} class="spin" />{:else}<ChevronRight size={13} />{/if}
        </button>
      {:else}
        <span class="chev"></span>
      {/if}
      <a href={href(r.rel)} aria-current={r.rel === current ? 'page' : undefined} title={r.rel || rootLabel}>
        {#if r.depth === 0}<HardDrive size={14} />{:else if r.open}<FolderOpen size={14} />{:else}<Folder size={14} />{/if}
        <span>{r.name}</span>
      </a>
    </div>
    {#if r.open && errors[r.rel]}<div class="err" style="--depth: {r.depth + 1}">{errors[r.rel]}</div>{/if}
  {/each}
</nav>

<style>
  .tree { display: flex; flex-direction: column; padding: 4px 0; font-size: var(--fs-sm); }
  .node {
    display: flex; align-items: center; gap: 2px; height: 28px;
    padding-left: calc(var(--depth) * 14px + 4px); border-radius: var(--r-sm);
  }
  .node:hover { background: var(--surface-2); }
  .node.active { background: var(--accent-dim); box-shadow: inset 2px 0 0 var(--accent); }
  .chev {
    flex: none; width: 20px; height: 20px; padding: 0; display: inline-flex; align-items: center; justify-content: center;
    border: 0; border-radius: var(--r-sm); background: none; color: var(--ink-3); cursor: pointer;
  }
  .chev:hover { color: var(--ink); }
  .chev :global(svg) { transition: transform .12s ease; }
  .chev.open :global(svg) { transform: rotate(90deg); }
  .chev :global(.spin) { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  a {
    flex: 1; min-width: 0; height: 100%; display: flex; align-items: center; gap: 6px; padding-right: 8px;
    color: var(--ink-2); text-decoration: none;
  }
  a:hover { color: var(--ink); text-decoration: none; }
  a :global(svg) { flex: none; color: var(--ink-3); }
  .node.active a { color: var(--ink); }
  a span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { padding: 2px 8px 4px calc(var(--depth) * 14px + 26px); color: var(--warn); font-size: var(--fs-xs); }
  @media (max-width: 900px) { .node { height: 36px; } }
</style>
