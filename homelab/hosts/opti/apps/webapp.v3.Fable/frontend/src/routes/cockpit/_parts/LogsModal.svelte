<script lang="ts">
  // Per-container live log viewer: Dozzle deep-linked into a wide modal by the
  // container id its SSE feed gave us (/dozzle/container/<id>).
  import Modal from '$lib/components/Modal.svelte';

  let { id, name, host, onclose }: { id: string; name: string; host: string; onclose: () => void } = $props();
</script>

<Modal open title="{name} — live logs ({host})" wide {onclose}>
  <iframe class="ct-logs-frame" src="/dozzle/container/{id}" title="{name} logs"></iframe>
</Modal>
