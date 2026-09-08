<script lang="ts">
  // Price watch — the opti-rebuild part tracker. pricewatch on opti scrapes
  // Newegg/eBay/Amazon four times a day; this shows current price vs target with
  // a per-item trend sparkline. Buy windows (price at/below target) get the green
  // pill — that is the whole point. Port of v2 PriceWatchWidget.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import { relTime } from '$lib/format';
  import { opt, type WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Sparkline, Pill } from '$lib/widgets/kit';

  interface PriceItem {
    id: string;
    label?: string;
    category?: string;
    retailer: string;
    url?: string;
    price: number | null;
    in_stock?: number | null;
    target_price?: number | null;
    error?: string | null;
  }
  interface PriceReport {
    run_at?: string;
    summary?: string;
    items?: PriceItem[];
    history?: Record<string, { d: string; p: number }[]>;
    below_target?: string[];
  }

  const money = (v: number) => (v >= 1000 ? `$${Math.round(v).toLocaleString()}` : `$${v.toFixed(2)}`);

  let { options = {} }: WidgetProps = $props();
  let category = $derived(String(opt(options, 'category', '')));

  const q = createQuery(() => ({
    queryKey: ['pricewatch'],
    queryFn: () => get<PriceReport>('/api/pricewatch', 12_000),
    refetchInterval: 15 * 60_000,
    retry: 0,
  }));

  let report = $derived(q.data);
  let items = $derived((report?.items ?? []).filter((it) => !category || it.category === category));
  let history = $derived(report?.history ?? {});
</script>

{#if q.isLoading}
  <WidgetFrame title="Price watch"><WidgetLoading /></WidgetFrame>
{:else if q.isError || !report}
  <WidgetFrame title="Price watch"><WidgetError message="pricewatch report unavailable" /></WidgetFrame>
{:else}
  <WidgetFrame title="Price watch" scroll meta={report.run_at ? relTime(report.run_at) : undefined}>
    <div class="kv-rows">
      {#each items as it (it.id)}
        {@const series = (history[it.id] ?? []).map((pt) => pt.p)}
        {@const below = it.price != null && it.target_price != null && it.price <= it.target_price}
        <div class="kv-row">
          <span>
            {#if it.url}
              <a href={it.url} target="_blank" rel="noreferrer">{it.label ?? it.id}</a>
            {:else}
              {it.label ?? it.id}
            {/if}
            <span class="t-dim"> · {it.retailer}</span>
          </span>
          <span class="pw-val">
            {#if series.length > 1}
              <Sparkline values={series} width={64} height={18} label="{it.label ?? it.id} price trend" format={money} />
            {/if}
            {#if it.price == null}
              <Pill tone="warn">{it.error ? 'fetch failed' : 'no price'}</Pill>
            {:else if below}
              <Pill tone="ok">{money(it.price)} · buy</Pill>
            {:else}
              <span>
                {money(it.price)}
                {#if it.target_price != null}
                  <span class="t-dim"> / {money(it.target_price)}</span>
                {/if}
              </span>
            {/if}
          </span>
        </div>
      {/each}
      {#if items.length === 0}
        <div class="t-dim">no tracked items{category ? ` in ${category}` : ''}</div>
      {/if}
    </div>
  </WidgetFrame>
{/if}

<style>
  .pw-val {
    display: flex;
    align-items: center;
    gap: 8px;
  }
</style>
