<script lang="ts">
  // Port of ChangesWidget from webapp.v2.legacy/frontend/src/widgets/hldb.tsx.
  // Backed by homelab.db on opti (routes/hldb.js -> :9100); opti is a single
  // point of failure so this renders an honest "unavailable" state (retry: 0)
  // rather than an error boundary when the upstream is down.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Pill } from '$lib/widgets/kit';

  interface ChangeEvent {
    at: string;
    host: string;
    kind: string;
    key: string;
    change: 'added' | 'removed' | 'changed';
    before?: Record<string, unknown> | null;
    after?: Record<string, unknown> | null;
  }
  interface ChangesResp { events?: ChangeEvent[]; event_count?: number; days?: number }

  const UNAVAILABLE = 'homelab-db unavailable (opti down or not configured)';
  const CHANGE_TONE: Record<string, string> = {
    added: 'ok', removed: 'crit', changed: 'warn',
  };

  let { options = {} }: WidgetProps = $props();

  let days = $derived(Number(opt(options, 'days', 7)));
  let host = $derived(opt(options, 'host', ''));

  const q = createQuery(() => ({
    queryKey: ['hldb-changes', days, host],
    queryFn: () => get<ChangesResp>(
      `/api/hldb/changes?days=${days}${host ? `&host=${host}` : ''}`, 20_000),
    refetchInterval: 10 * 60_000,
    retry: 0,
  }));

  let title = $derived(`Changes · ${days}d`);
  let events = $derived(q.data?.events ?? []);
</script>

{#if q.isError}
  <WidgetFrame {title}>
    <WidgetError message={UNAVAILABLE} />
  </WidgetFrame>
{:else}
  <WidgetFrame {title} meta={events.length ? `${events.length}` : undefined} scroll>
    {#if q.isLoading}
      <WidgetLoading />
    {/if}
    {#if !q.isLoading && events.length === 0}
      <div class="t-dim">Nothing changed{host ? ` on ${host}` : ''} in the last {days} days.</div>
    {/if}
    <div class="kv-rows">
      {#each events as e, i (`${e.at}-${e.key}-${i}`)}
        <div class="kv-row">
          <span class="mono">{e.host}</span>
          <span>
            <Pill tone={CHANGE_TONE[e.change]}>{e.change}</Pill>
            {e.kind === 'container' ? e.key : `${e.kind} ${e.key}`}
            {#if e.change === 'changed' && e.after?.state}
              <span class="t-dim"> → {String(e.after.state)}</span>
            {/if}
          </span>
          <span class="t-dim">{relTime(e.at)}</span>
        </div>
      {/each}
    </div>
  </WidgetFrame>
{/if}
