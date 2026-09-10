<script lang="ts">
  let { obj }: { obj: Record<string, unknown> } = $props();
  const show = (v: unknown) => (v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));
</script>

<table class="detail-table">
  <tbody>
    {#each Object.entries(obj) as [k, v] (k)}
      <tr><td>{k}</td><td>{show(v)}</td></tr>
    {/each}
  </tbody>
</table>
