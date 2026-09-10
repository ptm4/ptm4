<script lang="ts">
  // The card frame every widget renders into. `staleAt` (ISO) renders a uniform
  // data-age pill; `href` makes the whole card a link.
  import type { Snippet } from 'svelte';
  import { relTime } from '$lib/format';

  let {
    title,
    meta,
    scroll = false,
    href,
    bare = false,
    staleAt,
    staleAfterMin,
    children,
    head,
  }: {
    title?: string;
    meta?: string;
    scroll?: boolean;
    href?: string;
    /** no padding/background — for tiles that are their own card */
    bare?: boolean;
    /** timestamp of the data shown; renders "12m ago" and flags it when older than staleAfterMin */
    staleAt?: string | null;
    staleAfterMin?: number;
    children: Snippet;
    /** extra content placed in the head row, after the title */
    head?: Snippet;
  } = $props();

  let stale = $derived.by(() => {
    if (!staleAt || !staleAfterMin) return false;
    const t = Date.parse(staleAt);
    return !Number.isNaN(t) && Date.now() - t > staleAfterMin * 60_000;
  });
</script>

{#snippet body()}
  {#if title || meta || head || staleAt}
    <div class="w-head">
      {#if title}<span class="w-title">{title}</span>{/if}
      {#if head}{@render head()}{/if}
      {#if staleAt}<span class="w-age" data-s={stale ? 'warn' : ''} title={staleAt}>{relTime(staleAt)}</span>{/if}
      {#if meta}<span class="w-meta">{meta}</span>{/if}
    </div>
  {/if}
  <div class="w-body" class:scroll>{@render children()}</div>
{/snippet}

{#if href}
  <a class="w-card glass w-link" class:w-bare={bare} {href}>{@render body()}</a>
{:else}
  <div class="w-card glass" class:w-bare={bare}>{@render body()}</div>
{/if}
