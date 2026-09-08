<script lang="ts">
  // Ported from webapp.v2.legacy/frontend/src/widgets/system.tsx — NetworkWidget
  // (registry type 'network'). Per-host reachability from the latest
  // `network-latest` runner report.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetLoading } from '$lib/widgets/kit';
  import { relTime } from '$lib/format';
  import { useRunnerReport } from '$lib/api/queries';

  let {}: WidgetProps = $props();

  const q = useRunnerReport(() => 'network-latest');
  let hosts = $derived(q.data?.hosts ?? []);
</script>

<WidgetFrame title="Network" meta={q.data?.run_at ? relTime(q.data.run_at) : undefined}>
  {#if q.isLoading}
    <WidgetLoading />
  {/if}
  <div class="kv-rows">
    {#each hosts as h (h.host)}
      {@const m = (h.metrics ?? {}) as Record<string, any>}
      {@const detail = m.ping_ms != null ? `${m.ping_ms} ms`
        : m.reachable === false ? 'unreachable'
        : (h.summary ?? '')}
      <div class="kv-row">
        <span>{h.host}</span>
        <span class={h.status === 'ok' ? '' : 't-warn'}>{detail}</span>
      </div>
    {/each}
    {#if hosts.length === 0 && !q.isLoading}
      <div class="t-dim">No network report yet.</div>
    {/if}
  </div>
</WidgetFrame>
