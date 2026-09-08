<script lang="ts">
  // Local time + date. No network, no frame chrome — just a self-styled card,
  // matching v2's ClockWidget (webapp.v2.legacy/frontend/src/widgets/services.tsx).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';

  let { options = {} }: WidgetProps = $props();

  let showSeconds = $derived(opt(options, 'seconds', true));

  let now = $state(new Date());

  $effect(() => {
    const id = setInterval(() => { now = new Date(); }, showSeconds ? 1000 : 20_000);
    return () => clearInterval(id);
  });

  let timeStr = $derived(
    now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(showSeconds ? { second: '2-digit' } : {}) })
  );
  let dateStr = $derived(now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }));
</script>

<div class="w-card glass clock">
  <div class="clock-time">{timeStr}</div>
  <div class="clock-date">{dateStr}</div>
</div>

<style>
  .clock {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: var(--s1);
  }
</style>
