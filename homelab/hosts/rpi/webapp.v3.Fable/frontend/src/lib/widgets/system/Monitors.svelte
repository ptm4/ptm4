<script lang="ts">
  // Monitors widget — Uptime Kuma monitor grid. Direct port of MonitorsWidget
  // from webapp.v2.legacy/frontend/src/widgets/system.tsx (registry type 'monitors').
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';
  import { useUptime } from '$lib/api/queries';

  let { options = {} }: WidgetProps = $props();

  const q = useUptime();

  let meta = $derived(q.data ? `${q.data.up}/${q.data.total} up` : undefined);
</script>

{#if q.isError || q.data?.ok === false}
  <WidgetFrame title="Monitors">
    <WidgetError message="Uptime Kuma unavailable" />
  </WidgetFrame>
{:else}
  <WidgetFrame title="Monitors" {meta} scroll>
    {#if q.isLoading}
      <WidgetLoading />
    {/if}
    <div class="mon-grid">
      {#each q.data?.monitors ?? [] as m (m.name)}
        <span class="mon" title={m.ms != null ? `${m.ms} ms` : m.status}>
          <span class="cdot" data-s={m.status === 'up' ? 'ok' : m.status === 'down' ? 'crit' : 'warn'}></span>
          {m.name}
        </span>
      {/each}
    </div>
  </WidgetFrame>
{/if}
