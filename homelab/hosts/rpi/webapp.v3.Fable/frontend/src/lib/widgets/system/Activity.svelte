<script lang="ts">
  // Activity feed — findings, watchdog actions and backups from the latest
  // reports. Direct port of ActivityWidget in webapp.v2.legacy/frontend/src/widgets/system.tsx.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';
  import { useActivity } from '$lib/api/queries';
  import { relTime } from '$lib/format';

  let { options = {} }: WidgetProps = $props();

  let limit = $derived(opt(options, 'limit', 20));
  const q = useActivity(() => limit);
</script>

<WidgetFrame title="Activity" meta="from latest reports" scroll>
  {#if q.isLoading}
    <WidgetLoading />
  {:else if q.isError}
    <WidgetError message="activity unavailable" />
  {:else}
    <ul class="feed">
      {#each q.data?.events ?? [] as e, i (i)}
        <li data-sev={e.severity}>
          <span class="feed-dot"></span>
          <span class="feed-msg">{e.message}</span>
          <span class="feed-meta">{e.host ? `${e.host} · ` : ''}{e.source} · {relTime(e.ts)}</span>
        </li>
      {/each}
      {#if (q.data?.events.length ?? 0) === 0}
        <li class="t-dim">Nothing reported.</li>
      {/if}
    </ul>
  {/if}
</WidgetFrame>
