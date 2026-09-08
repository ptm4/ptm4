<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import Modal from '$lib/components/Modal.svelte';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';

  interface HistoryResp { history: { date: string; size: number; mtime: string | null }[] }

  let { name, label, onOpenDate, onclose }: {
    name: string;
    label: string;
    onOpenDate: (date: string) => void;
    onclose: () => void;
  } = $props();

  const q = createQuery(() => ({
    queryKey: ['history', name],
    queryFn: () => get<HistoryResp>(`/api/runners/${name}/history`),
  }));
</script>

<Modal open title="{label} — history" {onclose}>
  {#if q.isLoading}<div class="spin"></div>{/if}
  {#if q.isError}<p class="err">Could not load the history — {(q.error as Error).message}</p>{/if}
  {#if q.data && q.data.history.length === 0}<p class="dim">No dated snapshots for this runner yet.</p>{/if}
  {#if q.data && q.data.history.length > 0}
    <table class="detail-table">
      <tbody>
        {#each q.data.history as h (h.date)}
          <tr>
            <td><button class="link-btn" onclick={() => onOpenDate(h.date)}>{h.date}</button></td>
            <td>{(h.size / 1024).toFixed(1)} KB</td>
            <td>{relTime(h.mtime)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Modal>
