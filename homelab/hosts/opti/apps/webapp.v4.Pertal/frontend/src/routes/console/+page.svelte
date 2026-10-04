<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { consoleHost } from '$lib/console';
  onMount(() => {
    let host = 'opti';
    try { const last = localStorage.getItem('pertal-console-host'); if (last && consoleHost(last)) host = last; } catch { /* private storage */ }
    void goto(`/console/${host}/system`, { replaceState: true, state: {} });
  });
</script>
<svelte:head><title>Console · Pertal</title></svelte:head>
<p class="empty" role="status">Opening Console…</p>
