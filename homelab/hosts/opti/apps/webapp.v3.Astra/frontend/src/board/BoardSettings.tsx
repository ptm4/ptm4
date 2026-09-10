// Board appearance: wallpaper picker (bundled + uploaded), glass opacity/blur and
// wallpaper dim. Every change previews live by writing the CSS variables, and is
// only persisted when the board itself is saved.
import { useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Upload, Trash2 } from 'lucide-react';
import * as Slider from '@radix-ui/react-slider';
import { Modal } from '../components/Modal';
import { DEFAULT_WALLPAPERS, useWallpapers, wallpaperUrl } from '../lib/boards';
import { toast } from '../lib/toast';
import type { GlassSettings } from '../lib/api-types';

const DEFAULT_GLASS: GlassSettings = { opacity: 0.58, blur: 14, dim: 0.35 };

export function BoardSettings({
  open, onClose, wallpaper, glass, onChange,
}: {
  open: boolean;
  onClose: () => void;
  wallpaper: string | null;
  glass: GlassSettings | null;
  onChange: (patch: { wallpaper?: string | null; glass?: GlassSettings }) => void;
}) {
  const g = glass ?? DEFAULT_GLASS;
  const uploads = useWallpapers();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
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
  };

  const remove = async (file: string) => {
    try {
      await fetch(`/api/ui/wallpapers/${file}`, { method: 'DELETE' });
      qc.invalidateQueries({ queryKey: ['wallpapers'] });
      if (wallpaper === `user/${file}`) onChange({ wallpaper: null });
    } catch (e) {
      toast(`Delete failed: ${(e as Error).message}`, 'crit');
    }
  };

  const swatch = (value: string | null, label: string) => (
    <button
      key={value ?? 'none'}
      className={`wp-swatch${wallpaper === value ? ' active' : ''}`}
      style={value ? { backgroundImage: `url("${wallpaperUrl(value)}")` } : undefined}
      onClick={() => onChange({ wallpaper: value })}
      title={label}
    >
      {!value && <span>none</span>}
    </button>
  );

  return (
    <Modal open={open} onClose={onClose} title="Board appearance">
      <h3 className="detail-section-title">Wallpaper</h3>
      <div className="wp-grid">
        {swatch(null, 'No wallpaper')}
        {DEFAULT_WALLPAPERS.map((w) => swatch(w, w.replace('.svg', '')))}
        {(uploads.data?.user ?? []).map((f) => (
          <span key={f} className="wp-user">
            {swatch(`user/${f}`, f)}
            <button className="wp-del" title="Delete" onClick={() => remove(f)}><Trash2 /></button>
          </span>
        ))}
      </div>
      <div className="w-actions">
        <button className="tb-btn" onClick={() => fileRef.current?.click()}>
          <Upload /> Upload image
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }}
        />
      </div>

      <h3 className="detail-section-title">Glass</h3>
      <div className="form-rows">
        <GlassSlider label="Card opacity" value={g.opacity} min={0.15} max={1} step={0.01}
          onChange={(v) => onChange({ glass: { ...g, opacity: v } })} format={(v) => `${Math.round(v * 100)}%`} />
        <GlassSlider label="Blur" value={g.blur} min={0} max={40} step={1}
          onChange={(v) => onChange({ glass: { ...g, blur: v } })} format={(v) => `${v}px`} />
        <GlassSlider label="Wallpaper dim" value={g.dim} min={0} max={0.9} step={0.01}
          onChange={(v) => onChange({ glass: { ...g, dim: v } })} format={(v) => `${Math.round(v * 100)}%`} />
      </div>
    </Modal>
  );
}

function GlassSlider({
  label, value, min, max, step, onChange, format,
}: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; format: (v: number) => string;
}) {
  return (
    <div className="form-row slider-row">
      <span>{label}</span>
      <Slider.Root className="slider" value={[value]} min={min} max={max} step={step}
        onValueChange={([v]) => onChange(v)}>
        <Slider.Track className="slider-track"><Slider.Range className="slider-range" /></Slider.Track>
        <Slider.Thumb className="slider-thumb" aria-label={label} />
      </Slider.Root>
      <span className="slider-value">{format(value)}</span>
    </div>
  );
}
