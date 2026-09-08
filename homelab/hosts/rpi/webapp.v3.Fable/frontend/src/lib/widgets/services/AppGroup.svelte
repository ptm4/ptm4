<script lang="ts">
  // Port of v2 widgets/services.tsx: AppTile + AppGroupWidget (registry type
  // 'app-group'). Renders a whole bookmark group as an icon grid; each tile's
  // health dot comes from the server-side /api/linkcheck probe report.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { opt } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError } from '$lib/widgets/kit';
  import { useLinkcheck } from '$lib/api/queries';
  import { LINK_GROUPS, iconUrl, isExternal, type AppLink } from '$lib/links';

  let { options = {} }: WidgetProps = $props();

  let groupName = $derived(opt(options, 'group', 'Infrastructure'));
  const check = useLinkcheck();
  let group = $derived(LINK_GROUPS.find((g) => g.group === groupName));

  function tileState(link: AppLink, probe?: { up: boolean; error?: string }) {
    return !link.checkOrigin ? 'none' : probe == null ? 'unknown' : probe.up ? 'ok' : 'crit';
  }
</script>

{#if !group}
  <WidgetFrame title={groupName}>
    <WidgetError message="unknown group" />
  </WidgetFrame>
{:else}
  <WidgetFrame title={groupName} scroll>
    <div class="links-grid tight">
      {#each group.links as l (l.label)}
        {@const probe = l.checkOrigin ? check.data?.origins[l.checkOrigin] : undefined}
        {@const state = tileState(l, probe)}
        <a
          class="app-tile glass"
          href={l.url}
          target={isExternal(l.url) ? '_blank' : undefined}
          rel={isExternal(l.url) ? 'noreferrer' : undefined}
          title={probe && !probe.up ? `down: ${probe.error ?? 'no response'}` : l.label}
        >
          <img src={iconUrl(l.icon)} alt="" />
          <span class="app-label">{l.label}</span>
          {#if state !== 'none'}<span class="app-dot" data-s={state}></span>{/if}
        </a>
      {/each}
    </div>
  </WidgetFrame>
{/if}
