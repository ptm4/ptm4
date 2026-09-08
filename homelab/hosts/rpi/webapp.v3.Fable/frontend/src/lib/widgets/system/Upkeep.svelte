<script lang="ts">
  // Services & upkeep — systemd timers across the fleet, last-fired times.
  // Reads /api/timers (useTimers, 5min cadence, 15s timeout) — presentation,
  // not new collection. Direct port of v2's UpkeepWidget (widgets/system.tsx).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetLoading, WidgetError } from '$lib/widgets/kit';
  import { useTimers } from '$lib/api/queries';

  let { options = {} }: WidgetProps = $props();

  const q = useTimers();

  let rows = $derived(
    (q.data?.hosts ?? []).flatMap((h) => h.timers.map((t) => ({ ...t, host: h.host }))),
  );
</script>

{#if q.isError}
  <WidgetFrame title="Services & upkeep"><WidgetError message="timers unavailable" /></WidgetFrame>
{:else}
  <WidgetFrame title="Services & upkeep" meta={`${rows.length} timers`} scroll>
    {#if q.isLoading}<WidgetLoading />{/if}
    <div class="kv-rows">
      {#each rows as t (`${t.host}/${t.unit}`)}
        <div class="kv-row">
          <span class="mono">{t.unit.replace(/\.timer$/, '')}</span>
          <span class="t-dim">{t.host} · {t.passed ?? '—'}</span>
        </div>
      {/each}
      {#if rows.length === 0 && !q.isLoading}
        <div class="t-dim">No timers reported.</div>
      {/if}
    </div>
  </WidgetFrame>
{/if}
