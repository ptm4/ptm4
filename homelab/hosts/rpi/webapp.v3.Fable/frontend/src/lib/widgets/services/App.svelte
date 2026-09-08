<script lang="ts">
  // Port of v2 AppWidget (registry type 'app') from webapp.v2.legacy/frontend/src/widgets/services.tsx.
  // A single service icon tile with a health dot driven by the server-side linkcheck probe.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError } from '$lib/widgets/kit';
  import { useLinkcheck } from '$lib/api/queries';
  import { ALL_LINKS, iconUrl, isExternal } from '$lib/links';

  let { options = {} }: WidgetProps = $props();

  let label = $derived(opt(options, 'label', ''));
  let check = useLinkcheck();
  let link = $derived(ALL_LINKS.find((l) => l.label === label));

  // 'none' — this link has no origin to probe (always shown plain); 'unknown' —
  // has an origin but the linkcheck report hasn't loaded yet; 'ok'/'crit' — probed.
  let state = $derived.by(() => {
    if (!link?.checkOrigin) return 'none';
    const probe = check.data?.origins[link.checkOrigin];
    return probe == null ? 'unknown' : probe.up ? 'ok' : 'crit';
  });
  let probeError = $derived.by(() => {
    if (!link?.checkOrigin) return undefined;
    return check.data?.origins[link.checkOrigin]?.error;
  });
  let probeUp = $derived.by(() => {
    if (!link?.checkOrigin) return true;
    return check.data?.origins[link.checkOrigin]?.up ?? true;
  });
</script>

{#if !link}
  <WidgetFrame title="App"><WidgetError message={`unknown app '${label}'`} /></WidgetFrame>
{:else}
  <div class="w-card w-bare">
    <a
      class="app-tile glass"
      href={link.url}
      target={isExternal(link.url) ? '_blank' : undefined}
      rel={isExternal(link.url) ? 'noreferrer' : undefined}
      title={!probeUp ? `down: ${probeError ?? 'no response'}` : link.label}
    >
      <img src={iconUrl(link.icon)} alt="" />
      <span class="app-label">{link.label}</span>
      {#if state !== 'none'}<span class="app-dot" data-s={state}></span>{/if}
    </a>
  </div>
{/if}
