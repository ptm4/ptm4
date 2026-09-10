// Theme + accent — SAME localStorage key ('arch-theme') and value format ('dark'|'light')
// as every legacy/standalone page, so the whole dashboard flips together. The storage
// event keeps other open tabs (including legacy ones) in sync. The accent
// ('pocket-accent': yellow | orange | aqua) is v3-only.
import { browser } from '$app/environment';

const THEME_KEY = 'arch-theme';
const ACCENT_KEY = 'pocket-accent';

export type Theme = 'dark' | 'light';
export type Accent = 'yellow' | 'orange' | 'aqua';
export const ACCENTS: Accent[] = ['yellow', 'orange', 'aqua'];

function readTheme(): Theme {
  if (!browser) return 'dark';
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === 'dark' || t === 'light') return t;
  } catch { /* private mode */ }
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function readAccent(): Accent {
  if (!browser) return 'yellow';
  try {
    const a = localStorage.getItem(ACCENT_KEY);
    if (a === 'yellow' || a === 'orange' || a === 'aqua') return a;
  } catch { /* private mode */ }
  return 'yellow';
}

let theme = $state<Theme>(readTheme());
let accent = $state<Accent>(readAccent());

function apply() {
  if (!browser) return;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.accent = accent;
}

export const ui = {
  get theme() { return theme; },
  get accent() { return accent; },
  setTheme(t: Theme) {
    theme = t;
    try { localStorage.setItem(THEME_KEY, t); } catch { /* private mode */ }
    apply();
  },
  toggleTheme(): Theme {
    ui.setTheme(theme === 'dark' ? 'light' : 'dark');
    return theme;
  },
  setAccent(a: Accent) {
    accent = a;
    try { localStorage.setItem(ACCENT_KEY, a); } catch { /* private mode */ }
    apply();
  },
  cycleAccent(): Accent {
    ui.setAccent(ACCENTS[(ACCENTS.indexOf(accent) + 1) % ACCENTS.length]);
    return accent;
  },
};

// Call once from the root layout: applies the stored values (the inline script in
// app.html already did this before first paint; this keeps the store honest) and
// follows changes made in other tabs.
export function watchThemeAcrossTabs(): () => void {
  if (!browser) return () => {};
  apply();
  const onStorage = (e: StorageEvent) => {
    if (e.key === THEME_KEY && (e.newValue === 'dark' || e.newValue === 'light')) { theme = e.newValue; apply(); }
    if (e.key === ACCENT_KEY && (e.newValue === 'yellow' || e.newValue === 'orange' || e.newValue === 'aqua')) { accent = e.newValue; apply(); }
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}
