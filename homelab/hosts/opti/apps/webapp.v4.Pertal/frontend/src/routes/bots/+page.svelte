<script lang="ts">
  // Bots: the Discord bot fleet, one tab per bot (ported from v3.Fable's Bots page).
  // The active tab lives in the URL (?tab=<id>) so a reload or a link lands on the same bot.
  // Every save / send / re-roll is a Pertal job, so it also shows in Activity.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { CloudSun, HeartPulse, Clapperboard, Trophy, Crosshair } from '@lucide/svelte';
  import { BOTS, BOT_BY_ID } from '$lib/bots';
  import BotPanel from './_parts/BotPanel.svelte';

  const ICONS: Record<string, any> = { 'cloud-sun': CloudSun, 'heart-pulse': HeartPulse, clapperboard: Clapperboard, trophy: Trophy, crosshair: Crosshair };
  const tab = $derived(page.url.searchParams.get('tab') ?? BOTS[0].id);

  function select(id: string) {
    const url = new URL(page.url);
    url.searchParams.set('tab', id);
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<svelte:head><title>Bots · Pertal</title></svelte:head>

<div class="head">
  <h1>Bots</h1>
  <div class="seg tabs" role="group" aria-label="Bot">
    {#each BOTS as b (b.id)}
      {@const Ic = ICONS[b.icon]}
      <button type="button" aria-pressed={tab === b.id} onclick={() => select(b.id)}><Ic size={14} aria-hidden="true" /> {b.label}</button>
    {/each}
  </div>
</div>

{#key tab}
  <BotPanel bot={BOT_BY_ID[tab] ?? BOTS[0]} />
{/key}

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .tabs { flex-wrap: wrap; }
  .tabs button { display: inline-flex; align-items: center; gap: 5px; }
</style>
