// Board + settings API hooks, and the CSS-variable application of wallpaper/glass.
// Persistence is optimistic-concurrency via `rev`: a stale rev gets a 409 with the
// current document (backend/routes/ui.js).
import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
import { get, post, put, del } from './client';
import type { BoardDoc, BoardSummary, GlassSettings, UiSettings } from './types';

export const useBoards = () => createQuery(() => ({
  queryKey: ['boards'],
  queryFn: () => get<{ boards: BoardSummary[] }>('/api/ui/boards'),
  staleTime: 60_000,
}));

export const useBoard = (slug: () => string) => createQuery(() => ({
  queryKey: ['board', slug()],
  queryFn: () => get<BoardDoc>(`/api/ui/boards/${slug()}`),
  staleTime: Infinity,   // the editor owns this document; refetch only on demand
}));

export const useSettings = () => createQuery(() => ({
  queryKey: ['ui-settings'],
  queryFn: () => get<UiSettings>('/api/ui/settings'),
  staleTime: 60_000,
}));

export function useSaveBoard(slug: () => string) {
  const qc = useQueryClient();
  return createMutation(() => ({
    mutationFn: (doc: BoardDoc) => put<BoardDoc>(`/api/ui/boards/${slug()}`, {
      rev: doc.rev,
      name: doc.name,
      wallpaper: doc.wallpaper,
      glass: doc.glass,
      widgets: doc.widgets,
      layouts: doc.layouts,
    }),
    onSuccess: (saved: BoardDoc) => {
      qc.setQueryData(['board', slug()], saved);
      qc.invalidateQueries({ queryKey: ['boards'] });
    },
  }));
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return createMutation(() => ({
    mutationFn: (patch: Partial<UiSettings>) => put<UiSettings>('/api/ui/settings', patch),
    onSuccess: (saved: UiSettings) => { qc.setQueryData(['ui-settings'], saved); },
  }));
}

export function useCreateBoard() {
  const qc = useQueryClient();
  return createMutation(() => ({
    mutationFn: (name: string) => post<BoardDoc>('/api/ui/boards', { name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['boards'] }); },
  }));
}

export function useDeleteBoard() {
  const qc = useQueryClient();
  return createMutation(() => ({
    mutationFn: (slug: string) => del(`/api/ui/boards/${slug}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['boards'] }); },
  }));
}

export const useWallpapers = () => createQuery(() => ({
  queryKey: ['wallpapers'],
  queryFn: () => get<{ user: string[] }>('/api/ui/wallpapers'),
}));

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

// Wallpaper + glass are plain CSS variables on <html>, so the whole app (and any
// live preview during editing) follows a single write. Boards own this; every
// other page runs flat (applyBoardStyle(null, null) on leaving a board).
export function applyBoardStyle(wallpaper: string | null, glass: GlassSettings | null, reduceGlass = false) {
  const root = document.documentElement;
  const url = wallpaperUrl(wallpaper);
  root.style.setProperty('--wallpaper-url', url ? `url("${url}")` : 'none');
  // Write the board's INTENT, never the final values: tokens.css derives per-theme
  // finals from these, so light mode can veil a dark wallpaper properly.
  if (glass && url) {
    root.style.setProperty('--board-glass-opacity', String(glass.opacity));
    root.style.setProperty('--board-blur', `${glass.blur}px`);
    root.style.setProperty('--board-dim', String(glass.dim));
  } else {
    root.style.removeProperty('--board-glass-opacity');
    root.style.removeProperty('--board-blur');
    root.style.removeProperty('--board-dim');
  }
  root.classList.toggle('reduce-glass', reduceGlass);
}
