<script lang="ts">
  // The confirm tap for risky things. Two sources: a risky resource action (reboot,
  // update) and a page's own question (actions.ask — e.g. deleting a torrent). No login
  // in Pertal, so this is the guard against a stray tap; the backend refuses risky
  // requests without it (428).
  import { TriangleAlert } from '@lucide/svelte';
  import { actions } from '$lib/actions.svelte';

  let dialog = $state<HTMLDialogElement>();
  const open = $derived(!!actions.pending || !!actions.question);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });

  function cancel() {
    actions.cancel();
    actions.question = null;
  }
  function confirm() {
    if (actions.question) {
      const q = actions.question;
      actions.question = null;
      q.run();
    } else {
      actions.confirm();
    }
  }
</script>

<dialog bind:this={dialog} onclose={cancel} aria-labelledby="confirm-title">
  {#if actions.question}
    {@const q = actions.question}
    <div class="body">
      <TriangleAlert size={22} color="var(--warn)" />
      <div><h2 id="confirm-title">{q.title}</h2><p class="muted">{q.body}</p></div>
    </div>
    <div class="foot">
      <button class="btn" onclick={cancel}>Cancel</button>
      <button class="btn danger" onclick={confirm}>{q.label}</button>
    </div>
  {:else if actions.pending}
    {@const p = actions.pending}
    <div class="body">
      <TriangleAlert size={22} color="var(--warn)" />
      <div>
        <h2 id="confirm-title">{p.action.label} {p.resource.name}?</h2>
        <p class="muted">
          {#if p.action.kind === 'host.reboot'}
            {p.resource.name} goes offline for a few minutes{#if p.resource.id === 'opti'}, taking the vault, the bots, Samba and Pertal itself with it{/if}. Pertal will watch it come back.
          {:else if p.action.kind === 'container.update'}
            Pulls the newest image and recreates {p.resource.name}. It is briefly down while it restarts.
          {:else}
            This changes a live system.
          {/if}
        </p>
      </div>
    </div>
    <div class="foot">
      <button class="btn" onclick={cancel}>Cancel</button>
      <button class="btn danger" onclick={confirm}>{p.action.label}</button>
    </div>
  {/if}
</dialog>

<style>
  dialog {
    width: min(440px, calc(100vw - 32px));
    padding: 0;
    background: var(--surface);
    color: var(--ink);
    border: 1px solid var(--border-2);
    border-radius: var(--r-lg);
    box-shadow: var(--shadow);
  }
  dialog::backdrop { background: rgba(0, 0, 0, .5); }
  .body { display: flex; gap: var(--s3); padding: var(--s4); }
  .body p { margin: 6px 0 0; font-size: var(--fs-sm); }
  .foot { display: flex; justify-content: flex-end; gap: var(--s2); padding: var(--s3) var(--s4); border-top: 1px solid var(--border); }
</style>
