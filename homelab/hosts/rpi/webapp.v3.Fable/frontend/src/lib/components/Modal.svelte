<script lang="ts">
  import { Dialog } from 'bits-ui';
  import { X } from '@lucide/svelte';
  import type { Snippet } from 'svelte';

  let {
    open = $bindable(false),
    title,
    wide = false,
    onclose,
    children,
    actions,
  }: {
    open?: boolean;
    title: string;
    wide?: boolean;
    onclose?: () => void;
    children?: Snippet;
    actions?: Snippet;
  } = $props();
</script>

<Dialog.Root bind:open onOpenChange={(v) => { if (!v) onclose?.(); }}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay" />
    <Dialog.Content class="modal {wide ? 'wide' : ''}">
      <div class="modal-head">
        <Dialog.Title class="modal-title">{title}</Dialog.Title>
        {#if actions}{@render actions()}{/if}
        <Dialog.Close class="tbtn icon" aria-label="Close"><X /></Dialog.Close>
      </div>
      <div class="modal-body">
        {@render children?.()}
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
