<script lang="ts">
  // Settings — the things v2 left as a stub: appearance (theme, accent, glass
  // defaults, reduce-glass), and the escape hatches (legacy UI, API docs).
  import { createQuery } from '@tanstack/svelte-query';
  import { ExternalLink, SunMoon, Palette } from '@lucide/svelte';
  import { get } from '$lib/api/client';
  import { ui, ACCENTS, type Accent } from '$lib/stores/theme.svelte';
  import { useSettings, useSaveSettings } from '$lib/api/boards';
  import { toast } from '$lib/stores/toast.svelte';
  import { sse } from '$lib/api/sse.svelte';
  import { relTime } from '$lib/format';
  import { LEGACY_PAGES } from '$lib/nav';
  import RulesEditor from './_parts/RulesEditor.svelte';

  const settings = useSettings();
  const saveSettings = useSaveSettings();
  const health = createQuery(() => ({
    queryKey: ['health'],
    queryFn: () => get<{ status: string; host: string; uptime: number }>('/api/health', 5000),
    refetchInterval: 60_000,
    retry: 0,
  }));


  async function save(patch: Parameters<typeof saveSettings.mutateAsync>[0]) {
    try {
      await saveSettings.mutateAsync(patch);
      toast('Settings saved', 'ok', { ttlMs: 2000 });
    } catch (e) {
      toast(`Could not save settings: ${(e as Error).message}`, 'crit');
    }
  }

  const ACCENT_HEX: Record<Accent, string> = { yellow: '#fabd2f', orange: '#fe8019', aqua: '#8ec07c' };
</script>

<div class="settings-page">
  <div class="grid">
    <RulesEditor />
    <section class="card c6">
      <div class="chead"><h3>Appearance</h3><span class="meta">this browser</span></div>
      <div class="form-rows">
        <div class="form-row">
          <span>Theme</span>
          <div class="seg">
            <button class="seg-btn" class:active={ui.theme === 'dark'} onclick={() => ui.setTheme('dark')}>Dark</button>
            <button class="seg-btn" class:active={ui.theme === 'light'} onclick={() => ui.setTheme('light')}>Light</button>
          </div>
          <span class="faint"><SunMoon size={13} aria-hidden="true" /></span>
        </div>
        <div class="form-row">
          <span>Accent</span>
          <div class="swatches">
            {#each ACCENTS as a (a)}
              <button class="swatch" class:on={ui.accent === a} style="background: {ACCENT_HEX[a]}" title={a} aria-label={a} onclick={() => ui.setAccent(a)}></button>
            {/each}
          </div>
          <span class="faint" style="text-transform: capitalize">{ui.accent} <Palette size={13} aria-hidden="true" /></span>
        </div>
      </div>
      <p class="faint" style="margin: 0; font-size: 11.5px">Theme is shared with the legacy pages (same <code>arch-theme</code> key). Warn stays orange whichever accent is picked — yellow is interactive, not a warning.</p>
    </section>

    <section class="card c6">
      <div class="chead"><h3>Standalone pages</h3><span class="meta">served by this dashboard, not part of it</span></div>
      <p class="faint" style="margin: 0 0 var(--s2); font-size: 11.5px">These kept their own URLs through the v3 rewrite. They used to take a rail slot each; they live here now.</p>
      <div class="w-actions">
        {#each LEGACY_PAGES as p (p.path)}
          <a class="tbtn" href={p.path}><ExternalLink /> {p.label}</a>
        {/each}
      </div>
    </section>

    <section class="card c6">
      <div class="chead"><h3>This dashboard</h3><span class="meta">v3.Fable</span></div>
      <div class="kv-rows">
        <div class="kv-row"><span>Backend</span><span>{health.data ? `${health.data.host} · up ${Math.round(health.data.uptime / 3600)}h` : health.isError ? 'unreachable' : '…'}</span></div>
        <div class="kv-row"><span>Live updates</span><span style="text-transform: capitalize">{sse.state === 'off' ? 'polling only' : sse.state}{sse.lastEventAt ? ` · last ${sse.lastEvent} ${relTime(new Date(sse.lastEventAt).toISOString())}` : ''}</span></div>
        <div class="kv-row"><span>Design</span><span>Fable synthesis · gruvbox</span></div>
      </div>
      <div class="w-actions">
        <a class="tbtn" href="/api/events/status" target="_blank" rel="noreferrer"><ExternalLink /> Event stream status</a>
        <a class="tbtn" href="/api/rules" target="_blank" rel="noreferrer"><ExternalLink /> Alert rules (JSON)</a>
      </div>
    </section>
  </div>
</div>

<style>
  .settings-page { display: flex; flex-direction: column; gap: var(--s3); }
  .swatches { display: flex; gap: 8px; }
  .swatch { width: 22px; height: 22px; border-radius: 999px; border: 2px solid transparent; cursor: pointer; padding: 0; }
  .swatch.on { border-color: var(--ink); box-shadow: 0 0 0 2px var(--surface); }
</style>
