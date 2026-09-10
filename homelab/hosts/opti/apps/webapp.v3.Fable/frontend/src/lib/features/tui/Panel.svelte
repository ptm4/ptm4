<script lang="ts">
  // A btop panel: a box-drawn frame with its title inset into the top rule, and an
  // optional right-hand summary inset the same way. The border is drawn with CSS
  // (a real border stays hairline-crisp at any zoom) and the title sits on it, which
  // is how ncurses panels read without gluing together ─ characters by hand.
  import type { Snippet } from 'svelte';

  let { title, meta, tone = 'accent', children }: {
    title: string;
    meta?: string;
    tone?: 'accent' | 'ok' | 'warn' | 'crit' | 'dim';
    children: Snippet;
  } = $props();
</script>

<section class="panel" data-tone={tone}>
  <span class="title">{title}</span>
  {#if meta}<span class="meta">{meta}</span>{/if}
  <div class="body">{@render children()}</div>
</section>

<style>
  .panel {
    position: relative;
    border: 1px solid var(--border-2);
    border-radius: 2px;                 /* terminals have corners, not pills */
    padding: 12px 10px 9px;
    background: var(--bg);
    min-width: 0;
  }
  .title, .meta {
    position: absolute;
    top: -0.62em;
    font: 600 10.5px var(--mono);
    letter-spacing: .1em;
    text-transform: lowercase;
    background: var(--bg);              /* punches the hole in the top rule */
    padding: 0 6px;
    white-space: nowrap;
  }
  .title { left: 8px; color: var(--accent); }
  .meta { right: 8px; color: var(--ink-3); text-transform: none; letter-spacing: 0; }
  .panel[data-tone="ok"] .title { color: var(--ok); }
  .panel[data-tone="warn"] .title { color: var(--warn); }
  .panel[data-tone="crit"] .title { color: var(--crit); }
  .panel[data-tone="dim"] .title { color: var(--ink-3); }
  .body {
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.5;
    font-variant-numeric: tabular-nums;
    overflow-x: auto;
    scrollbar-width: thin;
  }
</style>
