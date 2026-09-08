<script lang="ts">
  import type { Snippet } from 'svelte';
  import Meter from './Meter.svelte';
  let { label, value, sub, pct, children }: {
    label: string;
    value?: string;
    sub?: string;
    pct?: number | null;
    /** custom value markup instead of `value` */
    children?: Snippet;
  } = $props();
</script>

<div class="vital">
  <div class="vital-label">{label}</div>
  <div class="vital-value">
    {#if children}{@render children()}{:else}{value ?? '—'}{/if}
    {#if sub}<small>{sub}</small>{/if}
  </div>
  <Meter {pct} />
</div>
