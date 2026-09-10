<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import Modal from '$lib/components/Modal.svelte';
  import { get } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { localeDateTime } from '$lib/format';
  import type { ReportApiBase, ReportDoc } from '$lib/reports';
  import ReportBody from './ReportBody.svelte';

  let { name, label, date, apiBase = 'runners', onclose }: {
    name: string;
    label: string;
    date?: string;
    apiBase?: ReportApiBase;
    onclose: () => void;
  } = $props();

  let url = $derived(date ? `/api/runners/${name}/report/${date}` : `/api/${apiBase}/${name}`);
  const q = createQuery(() => ({ queryKey: ['report', url], queryFn: () => get<ReportDoc>(url) }));

  $effect(() => {
    if (q.isError) {
      toast(`Could not load report: ${name}`, 'crit');
      onclose();
    }
  });

  let suffix = $derived(date ? ` — ${date}` : q.data?.run_at ? ` — ${localeDateTime(q.data.run_at)}` : '');
</script>

<Modal open title="{label}{suffix}" wide {onclose}>
  {#if q.isLoading}<div class="spin"></div>{:else if q.data}<ReportBody data={q.data} />{/if}
</Modal>
