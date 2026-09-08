<script lang="ts">
  import Modal from '$lib/components/Modal.svelte';
  import { WIDGETS } from '$lib/widgets/registry';

  let { open = $bindable(false), onAdd }: { open?: boolean; onAdd: (type: string) => void } = $props();
</script>

<Modal bind:open title="Add a widget" wide>
  <div class="widget-catalog">
    {#each WIDGETS as w (w.type)}
      <button class="catalog-item" onclick={() => { onAdd(w.type); open = false; }}>
        <span class="catalog-title">{w.label}</span>
        <span class="catalog-desc">{w.description}</span>
        <span class="catalog-size">{w.defaults.w}×{w.defaults.h}</span>
      </button>
    {/each}
  </div>
</Modal>
