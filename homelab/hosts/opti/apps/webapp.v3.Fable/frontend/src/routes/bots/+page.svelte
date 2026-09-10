<script lang="ts">
  // The Discord bot fleet — five bots, one panel. Every bot speaks the same control
  // API (status/config/send/preview), so the panel is driven by the field table in
  // $lib/bots.ts. The active tab lives in the URL (?tab=<id>) so a reload or a link
  // lands on the same bot, matching the v2 page's useSearchParams behaviour.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { BOTS, BOT_BY_ID } from '$lib/bots';
  import BotPanel from './_parts/BotPanel.svelte';

  let tab = $derived(page.url.searchParams.get('tab') ?? BOTS[0].id);

  function selectTab(id: string) {
    const url = new URL(page.url);
    url.searchParams.set('tab', id);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="bot-tabs">
  {#each BOTS as b (b.id)}
    <button type="button" class="bot-tab" class:active={tab === b.id} onclick={() => selectTab(b.id)}>
      <span aria-hidden="true">{b.icon}</span> {b.label}
    </button>
  {/each}
</div>

{#key tab}
  <BotPanel bot={BOT_BY_ID[tab] ?? BOTS[0]} />
{/key}
