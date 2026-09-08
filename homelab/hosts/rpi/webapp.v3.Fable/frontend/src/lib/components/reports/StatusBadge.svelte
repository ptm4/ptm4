<script lang="ts">
  let { status }: { status?: string } = $props();
  let s = $derived((status || 'unknown').toLowerCase());
</script>

<span class="status-badge" data-s={s}>{s === 'unknown' ? '?' : s.toUpperCase()}</span>
