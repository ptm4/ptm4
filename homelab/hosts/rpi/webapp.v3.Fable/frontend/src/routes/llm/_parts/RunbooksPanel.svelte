<script lang="ts">
  // Runbook CRUD — the markdown files /api/llama/ask grounds answers against.
  // Deletes go through the shared confirm dialog (v2 deleted on click with no
  // confirmation; this is a deliberate improvement, not a behaviour gap).
  import { Save, Trash2 } from '@lucide/svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { get, put, del } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';

  interface RunbookRow { name: string; bytes?: number }

  let { runbooks, runbooksError }: { runbooks: RunbookRow[]; runbooksError: boolean } = $props();

  const qc = useQueryClient();

  let editing = $state<string | null>(null);
  let draft = $state('');

  const saveRunbook = createMutation(() => ({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      put(`/api/llama/runbooks/${encodeURIComponent(name)}`, { content }, 15_000),
    onSuccess: () => {
      toast('Runbook saved', 'ok');
      qc.invalidateQueries({ queryKey: ['llama-runbooks'] });
      editing = null;
    },
    onError: (e: Error) => toast(`Save failed: ${e.message}`, 'crit'),
  }));

  const deleteRunbook = createMutation(() => ({
    mutationFn: (name: string) => del(`/api/llama/runbooks/${encodeURIComponent(name)}`, 15_000),
    onSuccess: () => {
      toast('Runbook deleted', 'ok');
      qc.invalidateQueries({ queryKey: ['llama-runbooks'] });
    },
    onError: (e: Error) => toast(`Delete failed: ${e.message}`, 'crit'),
  }));

  // Load a runbook's body when the editor opens on a given name.
  $effect(() => {
    const name = editing;
    if (!name) return;
    let alive = true;
    get<{ content?: string }>(`/api/llama/runbooks/${encodeURIComponent(name)}`, 15_000)
      .then((d) => { if (alive) draft = d.content ?? ''; })
      .catch(() => { if (alive) draft = ''; });
    return () => { alive = false; };
  });

  async function requestDelete(name: string) {
    const ok = await confirm({
      title: `Delete ${name}?`,
      body: 'This removes the runbook file — the ask endpoint will no longer ground answers against it.',
      tone: 'crit',
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    deleteRunbook.mutate(name);
    if (editing === name) editing = null;
  }
</script>

<section class="glass card">
  <div class="w-head">
    <span class="w-title">Runbooks</span>
    <span class="w-meta">{runbooks.length} files</span>
  </div>
  {#if runbooksError}<p class="t-dim">llama-ctl unreachable.</p>{/if}
  <div class="kv-rows">
    {#each runbooks as r (r.name)}
      <div class="kv-row">
        <span class="mono">{r.name}</span>
        <span>
          <button class="link-btn" onclick={() => (editing = r.name)}>edit</button>
          {' · '}
          <button class="link-btn" onclick={() => requestDelete(r.name)}>delete</button>
        </span>
      </div>
    {/each}
  </div>
  {#if editing}
    <div class="runbook-editor">
      <div class="w-head"><span class="w-title">{editing}</span></div>
      <textarea rows={16} bind:value={draft}></textarea>
      <div class="w-actions">
        <button
          class="tbtn primary"
          disabled={saveRunbook.isPending}
          onclick={() => editing && saveRunbook.mutate({ name: editing, content: draft })}
        >
          <Save size={14} aria-hidden="true" /> Save
        </button>
        <button class="tbtn" onclick={() => (editing = null)}>Cancel</button>
        <button class="tbtn danger" onclick={() => editing && requestDelete(editing)}>
          <Trash2 size={14} aria-hidden="true" /> Delete
        </button>
      </div>
    </div>
  {/if}
</section>

<style>
  .link-btn {
    background: none;
    border: none;
    padding: 0;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .link-btn:hover { text-decoration: underline; }
</style>
