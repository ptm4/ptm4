<script lang="ts">
  // Containers — fleet container status. Compact mode is the big-number summary
  // with a per-host breakdown; the full mode is the flat table. Both link to the
  // Containers page, which holds the interactive version. Reads /api/containers
  // (useContainers, 60s cadence, 15s timeout) — presentation, not new collection.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading } from '$lib/widgets/kit';
  import { useContainers } from '$lib/api/queries';
  import { durSince } from '$lib/format';

  let { options = {} }: WidgetProps = $props();

  const q = useContainers();
  let compact = $derived(opt(options, 'compact', true) === true);

  let hosts = $derived(q.data?.hosts ?? []);
  let total = $derived(hosts.reduce((n, h) => n + h.containers.length, 0));
  let up = $derived(hosts.reduce((n, h) => n + h.containers.filter((c) => c.up).length, 0));
  let updates = $derived(hosts.reduce((n, h) => n + h.containers.filter((c) => c.update_available).length, 0));

  // Flat row list for the table and the dot strip; keyed by host/name.
  let rows = $derived(hosts.flatMap((h) => h.containers.map((c) => ({ key: `${h.host}/${c.name}`, host: h.host, c }))));
</script>

{#snippet openLink()}
  <a class="w-meta" href="/containers">open →</a>
{/snippet}

{#snippet countLink()}
  <a class="w-meta" href="/containers">{up}/{total} up · open →</a>
{/snippet}

{#if q.isLoading}
  <WidgetFrame title="Containers"><WidgetLoading /></WidgetFrame>
{:else if q.isError}
  <WidgetFrame title="Containers"><WidgetError message="containers unavailable" /></WidgetFrame>
{:else if compact}
  <WidgetFrame title="Containers" head={openLink}>
    <div class="big-metric" data-s={up === total ? 'ok' : 'crit'}>{up}/{total}<small> up</small></div>
    <div class="kv-rows">
      {#each hosts.filter((h) => h.containers.length > 0) as h (h.host)}
        {@const downList = h.containers.filter((c) => !c.up).map((c) => c.name)}
        <div class="kv-row">
          <span>{h.host}</span>
          <span>
            {h.containers.length - downList.length}/{h.containers.length}
            {#if downList.length > 0}<span class="t-crit"> · down: {downList.join(', ')}</span>{/if}
          </span>
        </div>
      {/each}
    </div>
    <div class="w-foot">
      <span class="cstrip">
        {#each rows as r (r.key)}
          <span class="cdot" data-s={r.c.up ? 'ok' : 'crit'} title={`${r.c.name} (${r.host})`}></span>
        {/each}
      </span>
      {#if updates > 0}<span class="chip">{updates} update{updates > 1 ? 's' : ''}</span>{/if}
    </div>
  </WidgetFrame>
{:else}
  <WidgetFrame title="Containers" head={countLink} scroll>
    <table class="ctable">
      <tbody>
        {#each rows as r (r.key)}
          <tr>
            <td><span class="cdot" data-s={r.c.up ? 'ok' : 'crit'}></span></td>
            <td class="mono">{r.c.name}</td>
            <td class="t-dim">{r.host}</td>
            <td class="t-dim">{r.c.status_since ? durSince(r.c.status_since) : (r.c.status ?? '')}</td>
            <td>{#if r.c.update_available}<span class="chip" data-s="warn">update</span>{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </WidgetFrame>
{/if}

<style>
  a.w-meta { text-decoration: none; }
  a.w-meta:hover { color: var(--accent); }
</style>
