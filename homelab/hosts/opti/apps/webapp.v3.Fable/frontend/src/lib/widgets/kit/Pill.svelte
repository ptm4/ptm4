<script lang="ts">
  import type { Snippet } from 'svelte';
  let { tone, title, children }: { tone?: string; title?: string; children: Snippet } = $props();
</script>

<span class="pill" data-s={tone} {title}>{@render children()}</span>
