<script lang="ts">
  import Modal from './Modal.svelte';
  import { confirmState } from '$lib/stores/confirm.svelte';

  let typed = $state('');
  let p = $derived(confirmState.pending);
  $effect(() => { if (p) typed = ''; });
  let unlocked = $derived(!p?.opts.requireTyped || typed === p.opts.requireTyped);
</script>

{#if p}
  <Modal open title={p.opts.title} onclose={() => confirmState.close(false)}>
    <div class="confirm-body">
      <p style="white-space: pre-line; margin: 0 0 var(--s3)">{p.opts.body}</p>
      {#if p.opts.danger}<p class="confirm-danger" data-tone={p.opts.tone ?? 'warn'}>⚠ {p.opts.danger}</p>{/if}
      {#if p.opts.note}<p class="faint" style="font-size: 12px; margin: 0 0 var(--s3)">{p.opts.note}</p>{/if}
    </div>
    {#if p.opts.requireTyped}
      <label class="form-row confirm-typed">
        <span>Type <code>{p.opts.requireTyped}</code></span>
        <!-- svelte-ignore a11y_autofocus -->
        <input class="input" autofocus bind:value={typed} onkeydown={(e) => { if (e.key === 'Enter' && unlocked) confirmState.close(true); }} />
      </label>
    {/if}
    <div class="w-actions">
      <button class="tbtn" onclick={() => confirmState.close(false)}>Cancel</button>
      <button class="tbtn {p.opts.tone === 'crit' ? 'danger' : 'primary'}" disabled={!unlocked} onclick={() => confirmState.close(true)}>
        {p.opts.confirmLabel ?? 'Confirm'}
      </button>
    </div>
  </Modal>
{/if}

<style>
  .confirm-danger { margin: 0 0 var(--s3); padding: 8px 10px; border-radius: var(--r-sm); font-size: 12.5px; line-height: 1.5; }
  .confirm-danger[data-tone="crit"] { color: var(--crit); background: var(--crit-dim); }
  .confirm-danger[data-tone="warn"] { color: var(--warn); background: var(--warn-dim); }
  .confirm-typed { margin-bottom: var(--s3); }
  .confirm-typed code { font-family: var(--mono); color: var(--accent); }
  .confirm-typed .input { flex: 1; }
</style>
