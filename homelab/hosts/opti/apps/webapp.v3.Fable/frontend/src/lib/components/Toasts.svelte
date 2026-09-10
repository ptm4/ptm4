<script lang="ts">
  import { toasts } from '$lib/stores/toast.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each toasts.list as t (t.id)}
    <button type="button" class="toast" data-s={t.tone} onclick={() => toasts.dismiss(t.id)} title="Dismiss">{t.message}</button>
  {/each}
</div>
