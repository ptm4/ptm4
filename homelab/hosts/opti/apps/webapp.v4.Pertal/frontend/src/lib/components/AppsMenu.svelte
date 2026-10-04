<script lang="ts">
  import { internalLink } from "$lib/console";
  // Top-bar "Apps" button: a quick grid of every launchpad link, with the same live
  // reachability dots. The full page (/launchpad) is one click further.
  import { LayoutGrid } from '@lucide/svelte';
  import { api, type LinkGroup } from '$lib/api';

  let open = $state(false);
  let groups = $state<LinkGroup[]>([]);
  let loadedAt = 0;
  let root = $state<HTMLDivElement>();

  async function toggle() {
    open = !open;
    if (open && Date.now() - loadedAt > 60_000) {
      try { groups = (await api.links()).groups; loadedAt = Date.now(); } catch { /* keep last */ }
    }
  }
  $effect(() => {
    if (!open) return;
    const close = (e: Event) => { if (root && !root.contains(e.target as Node)) open = false; };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') open = false; };
    addEventListener('pointerdown', close);
    addEventListener('keydown', esc);
    return () => { removeEventListener('pointerdown', close); removeEventListener('keydown', esc); };
  });
</script>

<div class="apps" bind:this={root}>
  <button class="btn ghost trigger" class:on={open} aria-expanded={open} aria-haspopup="true" onclick={toggle} title="Apps">
    <LayoutGrid size={17} /><span class="lbl">Apps</span>
  </button>
  {#if open}
    <div class="menu" role="menu">
      {#each groups as g (g.group)}
        <div class="group faint">{g.group}</div>
        <div class="grid">
          {#each g.links as l (l.url)}
            <a class="app" href={l.url} target={internalLink(l.url) ? undefined : "_blank"} rel={internalLink(l.url) ? undefined : "noreferrer"} role="menuitem" onclick={() => (open = false)} class:down={l.reach && !l.reach.up}
              title={l.reach ? (l.reach.up ? `up · ${l.reach.ms} ms` : `down · ${l.reach.error}`) : l.label}>
              <img src="/icons/apps/{l.icon}" alt="" width="26" height="26" />
              <span>{l.label}</span>
            </a>
          {/each}
        </div>
      {:else}
        <div class="faint pad">Loading…</div>
      {/each}
      <a class="all" href="/launchpad" onclick={() => (open = false)}>Open the full launchpad →</a>
    </div>
  {/if}
</div>

<style>
  .apps { position: relative; }
  .trigger { gap: 6px; }
  .trigger.on { background: var(--surface-2); }
  .menu {
    position: absolute; right: 0; top: calc(100% + 8px); z-index: 50;
    width: min(460px, calc(100vw - 16px)); max-height: min(72vh, 620px); overflow: auto;
    padding: 6px 10px 10px; background: var(--surface); border: 1px solid var(--border-2);
    border-radius: var(--r-lg); box-shadow: var(--shadow);
  }
  .group { padding: 8px 4px 4px; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; }
  .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
  .app {
    display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 4px;
    border-radius: var(--r); color: var(--ink-2); text-decoration: none; font-size: 11px; text-align: center;
  }
  .app span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .app:hover { background: var(--surface-2); color: var(--ink); text-decoration: none; }
  .app img { border-radius: 6px; }
  .app.down img { filter: grayscale(1); opacity: .5; }
  .app.down span { color: var(--crit); }
  .all { display: block; margin-top: 8px; padding: 8px 4px 0; border-top: 1px solid var(--border); font-size: var(--fs-sm); }
  .pad { padding: 12px; }
  @media (max-width: 900px) {
    .lbl { display: none; }
    .menu { position: fixed; left: 8px; right: 8px; top: calc(var(--topbar-h) + 4px); width: auto; }
    .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }
</style>
