<script lang="ts">
  // Live log drawer for a runner. The dispatcher already writes <name>.log next to
  // the reports; this polls the tail while it's open, so "Run now" shows progress
  // instead of a 90-second silence.
  import { createQuery } from '@tanstack/svelte-query';
  import Modal from './Modal.svelte';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';

  interface LogResp { name: string; exists: boolean; lines: string[]; mtime?: string; size: number }

  let { name, label, onclose }: { name: string; label: string; onclose: () => void } = $props();

  const q = createQuery(() => ({
    queryKey: ['runner-log', name],
    queryFn: () => get<LogResp>(`/api/runners/${name}/log?lines=300`, 15_000),
    refetchInterval: 3000,
  }));

  let pre: HTMLPreElement | undefined = $state();
  $effect(() => {
    q.dataUpdatedAt;
    if (pre) pre.scrollTop = pre.scrollHeight;
  });
</script>

<Modal open title="{label} — live log" wide {onclose}>
  {#if q.isError}
    <p class="err">Could not read the log — {(q.error as Error).message}</p>
  {:else if q.data && !q.data.exists}
    <p class="dim">No log file for this runner yet. It writes one on its next run; the report itself updates either way.</p>
  {:else if q.data?.exists}
    <div class="log-meta">{(q.data.size / 1024).toFixed(1)} KB · updated {relTime(q.data.mtime)} · polling every 3s</div>
    <pre class="log-tail" bind:this={pre}>{q.data.lines.join('\n')}</pre>
  {:else}
    <div class="spin"></div>
  {/if}
</Modal>
