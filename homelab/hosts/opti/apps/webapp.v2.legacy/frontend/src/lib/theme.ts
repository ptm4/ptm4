// Theme sync — SAME localStorage key ('arch-theme') and value format ('dark'|'light')
// as every legacy/standalone page, so the whole dashboard flips together. The storage
// event keeps other open tabs (including legacy ones) in sync.

const KEY = 'arch-theme';

export type Theme = 'dark' | 'light';

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === 'dark' || t === 'light') return t;
  } catch { /* private mode */ }
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
}

export function setTheme(t: Theme): void {
  try { localStorage.setItem(KEY, t); } catch { /* private mode */ }
  applyTheme(t);
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark';
  setTheme(next);
  return next;
}

export function watchThemeAcrossTabs(): void {
  window.addEventListener('storage', (e) => {
    if (e.key === KEY && (e.newValue === 'dark' || e.newValue === 'light')) {
      applyTheme(e.newValue);
    }
  });
}
