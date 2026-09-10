<script lang="ts">
  // Settings — the things v2 left as a stub: appearance (theme, accent, glass
  // defaults, reduce-glass), and the escape hatches (legacy UI, API docs).
  import { createQuery } from '@tanstack/svelte-query';
  import { ExternalLink, SunMoon, Palette } from '@lucide/svelte';
  import { get } from '$lib/api/client';
  import { ui, ACCENTS, type Accent } from '$lib/stores/theme.svelte';
  import { useSettings, useSaveSettings, DEFAULT_WALLPAPERS, wallpaperUrl } from '$lib/api/boards';
  import { toast } from '$lib/stores/toast.svelte';
  import { sse } from '$lib/api/sse.svelte';
  import { relTime } from '$lib/format';
  import RulesEditor from './_parts/RulesEditor.svelte';

  const settings = useSettings();
  const saveSettings = useSaveSettings();
  const health = createQuery(() => ({
    queryKey: ['health'],
    queryFn: () => get<{ status: string; host: string; uptime: number }>('/api/health', 5000),
    refetchInterval: 60_000,
    retry: 0,
  }));

  let g = $derived(settings.data?.glass ?? { opacity: 0.62, blur: 14, dim: 0.35 });

  async function save(patch: Parameters<typeof saveSettings.mutateAsync>[0]) {
    try {
      await saveSettings.mutateAsync(patch);
      toast('Settings saved', 'ok', { ttlMs: 2000 });
    } catch (e) {
      toast(`Could not save settings: ${(e as Error).message}`, 'crit');
    }
  }

  const pct = (v: number) => `${Math.round(v * 100)}%`;
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
      <div class="chead"><h3>Board defaults</h3><span class="meta">used by boards without their own appearance</span></div>
      {#if settings.data}
        <div class="wp-grid">
          <button class="wp-swatch" class:active={settings.data.wallpaper === null} onclick={() => save({ wallpaper: null })} title="Flat (no wallpaper)"><span>flat</span></button>
          {#each DEFAULT_WALLPAPERS as w (w)}
            <button class="wp-swatch" class:active={settings.data.wallpaper === w} style="background-image: url('{wallpaperUrl(w)}')" onclick={() => save({ wallpaper: w })} title={w.replace('.svg', '')} aria-label={w}></button>
          {/each}
        </div>
        <div class="form-rows">
          <label class="form-row"><span>Card opacity</span>
            <input type="range" min="0.15" max="1" step="0.01" value={g.opacity} onchange={(e) => save({ glass: { ...g, opacity: Number(e.currentTarget.value) } })} />
            <span class="slider-value">{pct(g.opacity)}</span></label>
          <label class="form-row"><span>Blur</span>
            <input type="range" min="0" max="40" step="1" value={g.blur} onchange={(e) => save({ glass: { ...g, blur: Number(e.currentTarget.value) } })} />
            <span class="slider-value">{g.blur}px</span></label>
          <label class="form-row"><span>Wallpaper dim</span>
            <input type="range" min="0" max="0.9" step="0.01" value={g.dim} onchange={(e) => save({ glass: { ...g, dim: Number(e.currentTarget.value) } })} />
            <span class="slider-value">{pct(g.dim)}</span></label>
          <label class="form-row"><span>Reduce glass</span>
            <input type="checkbox" checked={settings.data.reduce_glass} onchange={(e) => save({ reduce_glass: e.currentTarget.checked })} />
            <span class="faint">solid cards, no blur (also follows the OS reduce-transparency setting)</span></label>
        </div>
      {:else if settings.isError}
        <p class="err">Could not load settings.</p>
      {:else}
        <div class="spin"></div>
      {/if}
    </section>

    <section class="card c6">
      <div class="chead"><h3>This dashboard</h3><span class="meta">v3.Fable</span></div>
      <div class="kv-rows">
        <div class="kv-row"><span>Backend</span><span>{health.data ? `${health.data.host} · up ${Math.round(health.data.uptime / 3600)}h` : health.isError ? 'unreachable' : '…'}</span></div>
        <div class="kv-row"><span>Live updates</span><span style="text-transform: capitalize">{sse.state === 'off' ? 'polling only' : sse.state}{sse.lastEventAt ? ` · last ${sse.lastEvent} ${relTime(new Date(sse.lastEventAt).toISOString())}` : ''}</span></div>
        <div class="kv-row"><span>Design</span><span>Fable synthesis · gruvbox</span></div>
      </div>
      <div class="w-actions">
        <a class="tbtn" href="/legacy/"><ExternalLink /> Legacy UI (v1)</a>
        <a class="tbtn" href="/agentic/"><ExternalLink /> Agentic workspace</a>
        <a class="tbtn" href="/api/events/status" target="_blank" rel="noreferrer"><ExternalLink /> Event stream status</a>
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
