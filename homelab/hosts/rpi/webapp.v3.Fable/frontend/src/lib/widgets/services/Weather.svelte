<script lang="ts">
  // Reuses the weather bot's Open-Meteo preview — no new upstream, no API key.
  // The payload is a Discord webhook body: { payload: { embeds: [ { fields } ] } }.
  // Ported from webapp.v2.legacy/frontend/src/widgets/services.tsx (WeatherWidget).
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';

  let { options = {} }: WidgetProps = $props();

  let limit = $derived(opt(options, 'limit', 4));

  interface WeatherPreview {
    payload?: {
      embeds?: { title?: string; description?: string; fields?: { name: string; value: string }[] }[];
    };
  }

  interface Location { icon: string; place: string; high: string; low: string; detail: string }

  // Each field is one location: name "☁️ BELLEROSE, NY", value a **bold** temp line.
  function parseLocation(f: { name: string; value: string }): Location {
    const m = f.name.match(/^(\S+)\s+(.*)$/);
    const icon = m?.[1] ?? '';
    const place = (m?.[2] ?? f.name).replace(/,\s*[A-Z]{2}$/, '');
    const plain = f.value.replace(/\*\*/g, '');
    const temps = plain.match(/-?\d+°/g) ?? [];
    return { icon, place, high: temps[0] ?? '', low: temps[1] ?? '', detail: plain.split('\n')[0] };
  }

  const q = createQuery(() => ({
    queryKey: ['weather-preview'],
    queryFn: () => get<WeatherPreview>('/api/weather/preview', 40_000),
    refetchInterval: 30 * 60_000,
    retry: 0,
  }));

  let locations = $derived.by((): Location[] => {
    const embed = q.data?.payload?.embeds?.[0];
    // The bot pads its Discord grid with blank spacer fields — drop those.
    return (embed?.fields ?? [])
      .filter((f) => (f.name || '').replace(/[​\s]/g, '') !== '')
      .slice(0, limit)
      .map(parseLocation);
  });
</script>

{#if q.isError}
  <WidgetFrame title="Weather"><WidgetError message="weather bot unreachable" /></WidgetFrame>
{:else if q.isLoading}
  <WidgetFrame title="Weather"><WidgetLoading /></WidgetFrame>
{:else}
  <WidgetFrame title="Weather" meta="today" scroll>
    {#if locations.length === 0}
      <div class="t-dim">No forecast in the latest payload.</div>
    {/if}
    <div class="wx-grid">
      {#each locations as l (l.place)}
        <div class="wx">
          <span class="wx-icon" aria-hidden="true">{l.icon}</span>
          <span class="wx-place">{l.place}</span>
          <span class="wx-temp">{l.high}{#if l.low}<small> / {l.low}</small>{/if}</span>
        </div>
      {/each}
    </div>
  </WidgetFrame>
{/if}
