<script lang="ts">
  // Compact list of favourite services. Port of QuickLinksWidget from
  // webapp.v2.legacy/frontend/src/widgets/services.tsx.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame } from '$lib/widgets/kit';
  import { ALL_LINKS, iconUrl, isExternal } from '$lib/links';

  let { options: _options = {} }: WidgetProps = $props();

  const favs = ALL_LINKS.filter((l) => l.fav);
</script>

{#snippet head()}
  <a class="w-meta" href="/links">all {ALL_LINKS.length} &rarr;</a>
{/snippet}

<WidgetFrame title="Quick links" {head} scroll>
  <div class="qlinks">
    {#each favs as l (l.label)}
      <a
        class="qlink"
        href={l.url}
        target={isExternal(l.url) ? '_blank' : undefined}
        rel={isExternal(l.url) ? 'noreferrer' : undefined}
      >
        <img src={iconUrl(l.icon)} alt="" />
        {l.label}
      </a>
    {/each}
  </div>
</WidgetFrame>
