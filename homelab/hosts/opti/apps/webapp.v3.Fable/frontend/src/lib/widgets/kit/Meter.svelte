<script lang="ts">
  import { toneFor } from '$lib/format';
  let { pct, tone }: { pct: number | null | undefined; tone?: string } = $props();
</script>

{#if pct != null}
  <div class="meter">
    <span data-tone={tone || toneFor(pct)} style="width: {Math.min(100, Math.max(0, pct))}%"></span>
  </div>
{/if}
