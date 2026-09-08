<script lang="ts">
  // Discord bots — per-bot enabled state, last post result and next scheduled
  // post. Answers "did the 7AM weather post actually fire?" at a glance.
  // Reads /api/<bot.id>/status for each bot in the registry (5min cadence,
  // 10s timeout, no retry — a paused/unreachable bot container is routine).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { createQueries } from '@tanstack/svelte-query';
  import { WidgetFrame } from '$lib/widgets/kit';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';
  import { BOTS, type BotStatus } from '$lib/bots';

  let { options: _options = {} }: WidgetProps = $props();

  const results = createQueries(() => ({
    queries: BOTS.map((b) => ({
      queryKey: ['bot-status', b.id],
      queryFn: () => get<BotStatus>(`/api/${b.id}/status`, 10_000),
      refetchInterval: 5 * 60_000,
      retry: 0,
    })),
  }));
</script>

{#snippet manageLink()}
  <a class="w-meta" href="/bots">manage →</a>
{/snippet}

<WidgetFrame title="Discord bots" head={manageLink} scroll>
  <div class="kv-rows">
    {#each BOTS as b, i (b.id)}
      {@const r = results[i]}
      {@const failed = /fail/i.test(r.data?.last_status ?? '')}
      <div class="kv-row bot-row">
        <span><span aria-hidden="true">{b.icon}</span> {b.label}</span>
        <span>
          {#if r.isError}
            <span class="t-crit">unreachable</span>
          {:else if r.isLoading}
            &hellip;
          {:else if r.data?.enabled === false}
            <span class="t-dim">paused</span>
          {:else}
            <span class={failed ? 't-crit' : ''}>{r.data?.last_status ?? 'no posts yet'}</span>
            <span class="t-dim"> &middot; next {relTime(r.data?.next_post_at)}</span>
          {/if}
        </span>
      </div>
    {/each}
  </div>
</WidgetFrame>

<style>
  a.w-meta { text-decoration: none; }
  a.w-meta:hover { color: var(--accent); }
</style>
