<script lang="ts">
  // Board appearance: wallpaper picker (bundled + uploaded), glass opacity/blur and
  // wallpaper dim. Every change previews live (the page writes the CSS variables)
  // and is persisted when the board itself is saved. A board with no wallpaper is
  // flat — the v3 default.
  import { useQueryClient } from '@tanstack/svelte-query';
  import { Upload, Trash2 } from '@lucide/svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { DEFAULT_WALLPAPERS, useWallpapers, wallpaperUrl } from '$lib/api/boards';
  import { toast } from '$lib/stores/toast.svelte';
  import type { GlassSettings } from '$lib/api/types';

  const DEFAULT_GLASS: GlassSettings = { opacity: 0.62, blur: 14, dim: 0.35 };

  let { open = $bindable(false), wallpaper, glass, onChange }: {
    open?: boolean;
    wallpaper: string | null;
    glass: GlassSettings | null;
    onChange: (patch: { wallpaper?: string | null; glass?: GlassSettings }) => void;
  } = $props();

  let g = $derived(glass ?? DEFAULT_GLASS);
  const uploads = useWallpapers();
  const qc = useQueryClient();
  let fileInput: HTMLInputElement;

  async function upload(file: File) {
    const body = new FormData();
    body.append('file', file);
    try {
      const res = await fetch('/api/ui/wallpapers', { method: 'POST', body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      toast('Wallpaper uploaded', 'ok');
      qc.invalidateQueries({ queryKey: ['wallpapers'] });
      onChange({ wallpaper: `user/${data.file}` });
    } catch (e) {
      toast(`Upload failed: ${(e as Error).message}`, 'crit');
    }
  }

  async function remove(file: string) {
    try {
      await fetch(`/api/ui/wallpapers/${file}`, { method: 'DELETE' });
      qc.invalidateQueries({ queryKey: ['wallpapers'] });
      if (wallpaper === `user/${file}`) onChange({ wallpaper: null });
    } catch (e) {
      toast(`Delete failed: ${(e as Error).message}`, 'crit');
    }
  }

  const pct = (v: number) => `${Math.round(v * 100)}%`;
</script>

<Modal bind:open title="Board appearance">
  <h3 class="detail-section-title">Wallpaper</h3>
  <div class="wp-grid">
    <button class="wp-swatch" class:active={wallpaper === null} onclick={() => onChange({ wallpaper: null })} title="No wallpaper (flat)"><span>flat</span></button>
    {#each DEFAULT_WALLPAPERS as w (w)}
      <button class="wp-swatch" class:active={wallpaper === w} style="background-image: url('{wallpaperUrl(w)}')" onclick={() => onChange({ wallpaper: w })} title={w.replace('.svg', '')} aria-label={w}></button>
    {/each}
    {#each uploads.data?.user ?? [] as f (f)}
      <span class="wp-user">
        <button class="wp-swatch" class:active={wallpaper === `user/${f}`} style="background-image: url('{wallpaperUrl(`user/${f}`)}')" onclick={() => onChange({ wallpaper: `user/${f}` })} title={f} aria-label={f}></button>
        <button class="wp-del" title="Delete" onclick={() => remove(f)}><Trash2 /></button>
      </span>
    {/each}
  </div>
  <div class="w-actions">
    <button class="tbtn" onclick={() => fileInput.click()}><Upload /> Upload image</button>
    <input bind:this={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden
      onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) upload(f); e.currentTarget.value = ''; }} />
  </div>

  <h3 class="detail-section-title">Glass <span class="faint" style="font-weight:400; text-transform:none; letter-spacing:0">— only applies with a wallpaper</span></h3>
  <div class="form-rows">
    <label class="form-row"><span>Card opacity</span>
      <input type="range" min="0.15" max="1" step="0.01" value={g.opacity} oninput={(e) => onChange({ glass: { ...g, opacity: Number(e.currentTarget.value) } })} />
      <span class="slider-value">{pct(g.opacity)}</span></label>
    <label class="form-row"><span>Blur</span>
      <input type="range" min="0" max="40" step="1" value={g.blur} oninput={(e) => onChange({ glass: { ...g, blur: Number(e.currentTarget.value) } })} />
      <span class="slider-value">{g.blur}px</span></label>
    <label class="form-row"><span>Wallpaper dim</span>
      <input type="range" min="0" max="0.9" step="0.01" value={g.dim} oninput={(e) => onChange({ glass: { ...g, dim: Number(e.currentTarget.value) } })} />
      <span class="slider-value">{pct(g.dim)}</span></label>
  </div>
</Modal>
