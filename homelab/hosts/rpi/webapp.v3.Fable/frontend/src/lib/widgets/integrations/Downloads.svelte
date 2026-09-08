<script lang="ts">
  // qBittorrent reachability behind gluetun's VPN namespace, read off the
  // linkcheck report the fleet already polls. Read-only — actionable stuff
  // lives behind the "qBittorrent →" link.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetLoading, WidgetError } from '$lib/widgets/kit';
  import { useLinkcheck } from '$lib/api/queries';

  let { options: _options = {} }: WidgetProps = $props();

  const QBT_ORIGIN = 'http://noblenumbat.lan:8081';

  const q = useLinkcheck();
  let qbt = $derived(q.data?.origins[QBT_ORIGIN]);
</script>

{#snippet head()}
  <a class="w-meta" href={`${QBT_ORIGIN}/`} target="_blank" rel="noreferrer">qBittorrent →</a>
{/snippet}

<WidgetFrame title="Downloads" {head}>
  {#if q.isLoading}
    <WidgetLoading />
  {:else if q.isError}
    <WidgetError message="linkcheck unavailable" />
  {:else}
    <div class="kv-rows">
      <div class="kv-row">
        <span>qBittorrent</span>
        <span class={qbt?.up ? '' : 't-crit'}>{qbt == null ? '…' : qbt.up ? 'reachable' : 'down'}</span>
      </div>
    </div>
    <div class="t-dim">
      Behind gluetun&apos;s network namespace — if this is down, check the VPN widget first.
    </div>
  {/if}
</WidgetFrame>
