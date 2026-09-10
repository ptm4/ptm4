<script lang="ts">
  // Primary navigation. Groups come from lib/nav.ts; the Hosts group carries a live
  // health pip from the vitals rollup so the rail doubles as a fleet glance.
  import { page } from '$app/state';
  import { ExternalLink } from '@lucide/svelte';
  import { NAV, HOSTS, SETTINGS_ITEM } from '$lib/nav';
  import { useVitals, useNotifications } from '$lib/api/queries';
  import { app } from '$lib/stores/ui.svelte';

  const vitals = useVitals();
  const notif = useNotifications();

  const isActive = (path: string) =>
    path === '/' ? page.url.pathname === '/' : page.url.pathname === path || page.url.pathname.startsWith(path + '/');

  function hostTone(name: string): 'ok' | 'crit' | 'unknown' {
    const h = vitals.data?.hosts?.[name];
    if (!h) return 'unknown';
    if (h.error || !h.latest) return 'crit';
    return 'ok';
  }

  const SettingsIcon = SETTINGS_ITEM.icon;
</script>

{#if app.railOpen}
  <div class="rail-scrim" role="presentation" onclick={() => app.setRail(false)}></div>
{/if}

<nav class="rail" class:open={app.railOpen} aria-label="Primary">
  <a class="brand" href="/" onclick={() => app.setRail(false)}>
    <span class="dot"></span> Pert’s Pocket <span class="ver">v3</span>
  </a>

  {#each NAV as g (g.title)}
    <div class="ngroup">
      <h3>{g.title}</h3>
      {#each g.items as it (it.path)}
        {@const Icon = it.icon}
        {#if it.external}
          <a class="nlink" href={it.path}><Icon aria-hidden="true" /> {it.label} <ExternalLink class="ext" aria-hidden="true" /></a>
        {:else}
          <a class="nlink" class:on={isActive(it.path)} href={it.path} onclick={() => app.setRail(false)}>
            <Icon aria-hidden="true" /> {it.label}
            {#if it.path === '/incidents' && (notif.data?.unacked ?? 0) > 0}
              <span class="cnt" data-s={(notif.data?.unacked ?? 0) > 5 ? 'crit' : 'warn'}>{notif.data?.unacked}</span>
            {:else if it.key}
              <span class="k">{it.key}</span>
            {/if}
          </a>
        {/if}
      {/each}
    </div>
  {/each}

  <div class="ngroup">
    <h3>Hosts</h3>
    {#each HOSTS as h (h.name)}
      {@const Icon = h.icon}
      <a class="nlink" class:on={isActive(`/host/${h.name}`)} href="/host/{h.name}" onclick={() => app.setRail(false)}>
        <Icon aria-hidden="true" /> {h.label}
        <span class="pip" data-s={h.intermittent && hostTone(h.name) !== 'ok' ? 'off' : hostTone(h.name)} title={h.role}></span>
      </a>
    {/each}
  </div>

  <div class="ngroup rail-foot">
    <a class="nlink" class:on={isActive('/settings')} href="/settings" onclick={() => app.setRail(false)}>
      <SettingsIcon aria-hidden="true" /> Settings
    </a>
  </div>
</nav>
