<script lang="ts">
  // A timestamp that keeps ticking ("8s ago" → "9s ago") and turns amber when stale.
  import { ago } from '$lib/format';
  import { live } from '$lib/live.svelte';
  let { at, staleAfterMs = 0, prefix = '' }: { at: string | null | undefined; staleAfterMs?: number; prefix?: string } = $props();
  const stale = $derived(!at || (staleAfterMs > 0 && live.now - Date.parse(at) > staleAfterMs));
</script>

<time class="age" class:stale datetime={at ?? undefined} title={at ?? 'never'}>{prefix}{ago(at, live.now)}</time>

<style>
  .age { color: var(--ink-3); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .stale { color: var(--warn); }
</style>
