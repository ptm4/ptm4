<script lang="ts">
  // Streams — active stream-station slots (from the streams-station backend),
  // with a jump to the full player. Ported from v2 StreamsWidget
  // (webapp.v2.legacy/frontend/src/widgets/integrations.tsx).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';

  // No configurable options for this widget (see registry.ts 'streams' entry).
  let {}: WidgetProps = $props();

  interface StreamSlot { slot?: number; channel?: string; platform?: string; state?: string; url?: string | null; running?: boolean; title?: string }
  interface StreamStatus { slots?: StreamSlot[] }

  const q = createQuery(() => ({
    queryKey: ['streams-status'],
    queryFn: () => get<StreamStatus>('/api/streams/status', 12_000),
    refetchInterval: 60_000,
    retry: 0,
  }));

  // stream-station reports `state` (idle|starting|running|ended); v2 filtered on a
  // `running` boolean that never existed, so this widget was permanently empty.
  let active = $derived((q.data?.slots ?? []).filter((s) => s.state === 'running' || s.state === 'starting' || s.running));
</script>

{#snippet openLink()}
  <a href="/streams/">open →</a>
{/snippet}

{#if q.isError}
  <WidgetFrame title="Streams"><WidgetError message="stream station unreachable" /></WidgetFrame>
{:else}
  <WidgetFrame title="Streams" head={openLink}>
    {#if q.isLoading}
      <WidgetLoading />
    {:else if active.length === 0}
      <div class="t-dim">No active streams.</div>
    {/if}
    <div class="kv-rows">
      {#each active as s, i (s.slot ?? i)}
        <div class="kv-row">
          <span class="mono">slot {s.slot ?? i + 1}</span>
          <span>{s.channel ?? s.title ?? '—'}{s.platform ? ` · ${s.platform}` : ''}</span>
        </div>
      {/each}
    </div>
  </WidgetFrame>
{/if}
