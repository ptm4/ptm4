<script lang="ts">
  // Settings hub. Each section is its own route so it can be linked to directly;
  // add a section here and it shows up in the tabs. Maintenance holds the host-level
  // enable/disable switches (auto-updates first).
  import type { Snippet } from 'svelte';
  import { page } from '$app/state';

  let { children }: { children: Snippet } = $props();

  const SECTIONS = [
    { path: '/settings', label: 'General', meta: 'appearance, alert rules, standalone pages' },
    { path: '/settings/maintenance', label: 'Maintenance', meta: 'host switches — every change is audited' },
  ];
  let current = $derived(SECTIONS.find((s) => s.path === page.url.pathname) ?? SECTIONS[0]);
</script>

<div class="settings-hub">
  <div class="shead">
    <h2>Settings</h2>
    <span class="meta">{current.meta}</span>
    <div class="bot-tabs right">
      {#each SECTIONS as s (s.path)}
        <a class="bot-tab" class:active={current.path === s.path} href={s.path}>{s.label}</a>
      {/each}
    </div>
  </div>
  {@render children()}
</div>

<style>
  .settings-hub { display: flex; flex-direction: column; gap: var(--s3); }
  .bot-tab { text-decoration: none; }
</style>
