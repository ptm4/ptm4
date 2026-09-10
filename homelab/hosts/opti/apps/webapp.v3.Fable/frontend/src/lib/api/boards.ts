// Settings API hooks, and default wallpaper helpers used by Settings/Launchpad.
import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
import { get, put } from './client';
import type { UiSettings } from './types';

export const useSettings = () => createQuery(() => ({
  queryKey: ['ui-settings'],
  queryFn: () => get<UiSettings>('/api/ui/settings'),
  staleTime: 60_000,
}));

export function useSaveSettings() {
  const qc = useQueryClient();
  return createMutation(() => ({
    mutationFn: (patch: Partial<UiSettings>) => put<UiSettings>('/api/ui/settings', patch),
    onSuccess: (saved: UiSettings) => { qc.setQueryData(['ui-settings'], saved); },
  }));
}

// Wallpapers bundled with the build (static/wallpapers) — generated gradients, so
// they cost a couple of KB each and always exist offline.
export const DEFAULT_WALLPAPERS = [
  'graphite.svg', 'aurora.svg', 'dusk.svg', 'slate.svg', 'ember.svg', 'deep.svg', 'moss.svg',
];

export const wallpaperUrl = (w: string | null): string | null => {
  if (!w) return null;
  if (w.startsWith('user/')) return `/media/wallpapers/${w.slice(5)}`;
  return `/wallpapers/${w}`;
};
