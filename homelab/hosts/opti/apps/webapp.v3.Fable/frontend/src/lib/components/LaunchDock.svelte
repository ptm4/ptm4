<script lang="ts">
  // Favourite services as a dock — the Launchpad's pins, with their health dots.
  import { ArrowRight } from '@lucide/svelte';
  import { useServices, fallbackServices } from '$lib/api/services';
  import { useSettings } from '$lib/api/boards';
  import { iconUrl } from '$lib/links';

  const q = useServices();
  const settings = useSettings();
  let data = $derived(q.data ?? (q.isError ? fallbackServices() : null));
  let favIds = $derived<string[]>(settings.data?.favorites ?? (data?.services.filter((s) => s.fav).map((s) => s.id) ?? []));
  let favs = $derived((data?.services ?? []).filter((s) => favIds.includes(s.id)));
</script>

<div class="dock">
  {#each favs as s (s.id)}
    <a class="d" href={s.url} target={s.url.startsWith('/') ? undefined : '_blank'} rel="noreferrer" title="{s.label}{s.state === 'down' ? ' — down' : ''}" data-s={s.state}>
      <img src={iconUrl(s.icon)} alt="" width="26" height="26" /><span>{s.label.split(' (')[0]}</span><i></i>
    </a>
  {/each}
  <a class="d more" href="/launchpad"><ArrowRight size={16} /><span>all {data?.services.length ?? ''}</span></a>
</div>

<style>
  .dock { display: flex; gap: 6px; overflow-x: auto; padding: 2px; scrollbar-width: thin; }
  .d { position: relative; flex: none; display: flex; flex-direction: column; align-items: center; gap: 4px; width: 78px; padding: 8px 4px 6px; border: 1px solid var(--border); border-radius: var(--r); background: var(--surface); color: var(--ink-2); text-decoration: none; font-size: 10.5px; text-align: center; }
  .d:hover { border-color: var(--accent-muted); color: var(--ink); text-decoration: none; }
  .d span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .d i { position: absolute; top: 6px; right: 6px; width: 6px; height: 6px; border-radius: 99px; background: var(--surface-3); }
  .d[data-s="up"] i { background: var(--ok); } .d[data-s="down"] i { background: var(--crit); box-shadow: 0 0 5px var(--crit); }
  .d.more { justify-content: center; color: var(--accent); }
</style>
