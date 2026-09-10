<script lang="ts">
  import type { Finding } from '$lib/reports';
  let { items }: { items: Finding[] } = $props();
</script>

<div class="findings-list">
  {#each items as f, i (i)}
    <div class="finding" data-sev={(f.severity || 'info').toLowerCase()}>
      <span class="finding-sev">{(f.severity || 'info').toUpperCase()}</span>
      <span class="finding-msg">{f.message || ''}</span>
    </div>
  {/each}
</div>
