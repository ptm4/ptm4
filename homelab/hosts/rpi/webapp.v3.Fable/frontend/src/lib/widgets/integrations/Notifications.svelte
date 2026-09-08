<script lang="ts">
  // Open findings — unacknowledged items from the doctor/security reports.
  // Ported from webapp.v2.legacy/frontend/src/widgets/integrations.tsx (NotificationsWidget).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Pill } from '$lib/widgets/kit';
  import { useNotifications } from '$lib/api/queries';
  import { relTime } from '$lib/format';

  let { options = {} }: WidgetProps = $props();

  let limit = $derived(opt(options, 'limit', 6));
  const q = useNotifications(() => false);

  let items = $derived((q.data?.items ?? []).slice(0, limit));
</script>

{#snippet unackedPill()}
  {#if q.data}
    <Pill tone={q.data.unacked ? 'warn' : 'ok'}>{q.data.unacked} open</Pill>
  {/if}
{/snippet}

{#if q.isError}
  <WidgetFrame title="Open findings">
    <WidgetError message="reports unavailable" />
  </WidgetFrame>
{:else}
  <WidgetFrame title="Open findings" head={unackedPill} scroll>
    {#if q.isLoading}
      <WidgetLoading />
    {/if}
    {#if q.data?.unacked === 0}
      <div class="t-dim">Everything acknowledged.</div>
    {/if}
    <ul class="feed">
      {#each items as n (n.id)}
        <li data-sev={n.severity}>
          <span class="feed-dot"></span>
          <span class="feed-msg">{n.message}</span>
          <span class="feed-meta">{n.host ? `${n.host} · ` : ''}{n.source} · {relTime(n.ts)}</span>
        </li>
      {/each}
    </ul>
  </WidgetFrame>
{/if}
