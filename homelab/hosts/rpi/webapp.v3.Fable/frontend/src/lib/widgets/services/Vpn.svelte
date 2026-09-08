<script lang="ts">
  // Gluetun's health is the health of the five containers sharing its netns — if
  // gluetun is down they are all down by design, not five separate faults.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Pill } from '$lib/widgets/kit';
  import { useContainers } from '$lib/api/queries';

  let { options = {} }: WidgetProps = $props();

  const q = useContainers();

  const BEHIND = ['qbittorrent', 'sabnzbd', 'prowlarr', 'flaresolverr', 'slskd'];

  let nn = $derived(q.data?.hosts.find((h) => h.host === 'noblenumbat'));
  let gluetun = $derived(nn?.containers.find((c) => c.name === 'gluetun'));
  let behindRows = $derived((nn?.containers ?? []).filter((c) => BEHIND.includes(c.name)));
</script>

{#if q.isError}
  <WidgetFrame title="VPN"><WidgetError message={q.error instanceof Error ? q.error.message : 'failed to load'} /></WidgetFrame>
{:else if q.isLoading}
  <WidgetFrame title="VPN"><WidgetLoading /></WidgetFrame>
{:else}
  <WidgetFrame title="VPN">
    {#snippet head()}
      <Pill tone={gluetun ? (gluetun.up ? 'ok' : 'crit') : undefined}>
        {gluetun ? (gluetun.up ? 'up' : 'down') : 'unknown'}
      </Pill>
    {/snippet}
    {#if !gluetun}
      <div class="t-dim">gluetun not in the latest report</div>
    {/if}
    <div class="kv-rows">
      {#each behindRows as c (c.name)}
        <div class="kv-row">
          <span class="mono">{c.name}</span>
          <span class={c.up ? '' : 't-crit'}>{c.up ? 'up' : 'down'}</span>
        </div>
      {/each}
    </div>
  </WidgetFrame>
{/if}
