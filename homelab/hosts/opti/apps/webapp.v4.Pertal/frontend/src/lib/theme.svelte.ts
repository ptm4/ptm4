// Theme = family (gruvbox | github) × mode (dark | light | system). Applied as
// data-family / data-mode on <html>; app.html applies the saved choice before paint.
export type Family = 'gruvbox' | 'github';
export type Mode = 'dark' | 'light' | 'system';

const FAMILY_KEY = 'pertal-theme-family';
const MODE_KEY = 'pertal-theme-mode';

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

class Theme {
  family = $state<Family>(read(FAMILY_KEY, ['gruvbox', 'github'] as const, 'gruvbox'));
  mode = $state<Mode>(read(MODE_KEY, ['dark', 'light', 'system'] as const, 'system'));
  resolved = $state<'dark' | 'light'>('dark');

  constructor() {
    const mq = matchMedia('(prefers-color-scheme: light)');
    mq.addEventListener('change', () => this.apply());
    this.apply();
  }

  set(family: Family, mode: Mode) {
    this.family = family;
    this.mode = mode;
    try {
      localStorage.setItem(FAMILY_KEY, family);
      localStorage.setItem(MODE_KEY, mode);
    } catch { /* private mode: still applies for this session */ }
    this.apply();
  }

  apply() {
    this.resolved = this.mode === 'system'
      ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
      : this.mode;
    const d = document.documentElement;
    d.dataset.family = this.family;
    d.dataset.mode = this.resolved;
    const meta = document.querySelector('meta[name="theme-color"]');
    meta?.setAttribute('content', getComputedStyle(d).getPropertyValue('--bg').trim() || '#1d2021');
  }
}

export const theme = new Theme();
