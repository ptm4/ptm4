// A board page: renders the grid, owns edit mode, and persists changes with
// optimistic-concurrency (`rev`). Local edits apply instantly; the save is
// debounced so a drag doesn't write once per animation frame.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import type { ResponsiveLayouts } from 'react-grid-layout';
import { Pencil, Plus, Paintbrush, Check, RotateCcw, RefreshCw } from 'lucide-react';
import { useBoard, useSaveBoard, useSettings, applyBoardStyle } from '../lib/boards';
import { useUi } from '../lib/ui-store';
import { toast } from '../lib/toast';
import { ApiError } from '../lib/api';
import { BoardGrid } from '../board/BoardGrid';
import { AddWidgetDrawer } from '../board/AddWidgetDrawer';
import { WidgetSettings } from '../board/WidgetSettings';
import { BoardSettings } from '../board/BoardSettings';
import { WIDGET_BY_TYPE } from '../widgets/registry';
import type { BoardDoc, GlassSettings } from '../lib/api-types';

const SAVE_DEBOUNCE_MS = 800;

export default function BoardPage({ slug: fixedSlug }: { slug?: string }) {
  const params = useParams();
  const slug = fixedSlug ?? params.slug ?? 'home';

  const boardQ = useBoard(slug);
  const settingsQ = useSettings();
  const save = useSaveBoard(slug);
  const editMode = useUi((s) => s.editMode);
  const setEditMode = useUi((s) => s.setEditMode);
  const qc = useQueryClient();

  // The always-available refresh: invalidate every data query at once (the board
  // document itself is deliberately excluded — an unsaved draft must survive).
  const qcRefreshAll = useCallback(() => {
    qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'board' });
    toast('Refreshing every widget…', 'info', { ttlMs: 2000 });
  }, [qc]);

  // `draft` is the live document while editing; null means "showing the server's".
  const [draft, setDraft] = useState<BoardDoc | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [styleOpen, setStyleOpen] = useState(false);
  const [configuring, setConfiguring] = useState<string | null>(null);
  const saveTimer = useRef<number | null>(null);

  const board = draft ?? boardQ.data ?? null;

  // Wallpaper + glass are global CSS variables: board choice wins, global settings
  // fill in, and the effect re-runs on every draft change so editing previews live.
  useEffect(() => {
    if (!board) return;
    applyBoardStyle(
      board.wallpaper ?? settingsQ.data?.wallpaper ?? null,
      board.glass ?? settingsQ.data?.glass ?? null,
      settingsQ.data?.reduce_glass ?? false,
    );
  }, [board?.wallpaper, board?.glass, settingsQ.data, board]);

  // Leaving edit mode (or the page) must not strand an unsaved draft.
  useEffect(() => () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); }, []);

  const queueSave = useCallback((next: BoardDoc) => {
    setDraft(next);
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      save.mutate(next, {
        onSuccess: (saved) => setDraft(saved),
        onError: (e) => {
          const err = e as ApiError;
          if (err.status === 409) {
            toast('This board changed in another tab — reloading it', 'warn');
            setDraft(null);
            boardQ.refetch();
          } else {
            toast(`Could not save the board: ${err.message}`, 'crit', { ttlMs: 8000 });
          }
        },
      });
    }, SAVE_DEBOUNCE_MS);
  }, [save, boardQ]);

  const onLayoutChange = useCallback((layouts: ResponsiveLayouts) => {
    if (!board) return;
    // Strip RGL's runtime extras (minW/static/moved) — the document stores geometry only.
    const clean: Record<string, { i: string; x: number; y: number; w: number; h: number }[]> = {};
    for (const [bp, items] of Object.entries(layouts)) {
      clean[bp] = (items ?? []).map(({ i, x, y, w, h }) => ({ i, x, y, w, h }));
    }
    const same = JSON.stringify(clean) === JSON.stringify(board.layouts);
    if (same) return;
    queueSave({ ...board, layouts: clean });
  }, [board, queueSave]);

  const addWidget = (type: string) => {
    if (!board) return;
    const def = WIDGET_BY_TYPE[type];
    const id = `w-${type}-${Math.random().toString(36).slice(2, 7)}`;
    const maxY = Math.max(0, ...(board.layouts.lg ?? []).map((l) => l.y + l.h));
    queueSave({
      ...board,
      widgets: [...board.widgets, { id, type, options: {} }],
      layouts: {
        ...board.layouts,
        lg: [...(board.layouts.lg ?? []), { i: id, x: 0, y: maxY, w: def.defaults.w, h: def.defaults.h }],
        sm: [...(board.layouts.sm ?? []), { i: id, x: 0, y: maxY, w: Math.min(2, def.defaults.w), h: def.defaults.h }],
      },
    });
    toast(`${def.label} added`, 'ok');
  };

  const removeWidget = (id: string) => {
    if (!board) return;
    const layouts = Object.fromEntries(
      Object.entries(board.layouts).map(([bp, items]) => [bp, items.filter((l) => l.i !== id)]),
    );
    queueSave({ ...board, widgets: board.widgets.filter((w) => w.id !== id), layouts });
  };

  const setWidgetOptions = (id: string, options: Record<string, unknown>) => {
    if (!board) return;
    queueSave({
      ...board,
      widgets: board.widgets.map((w) => (w.id === id ? { ...w, options } : w)),
    });
  };

  const setStyle = (patch: { wallpaper?: string | null; glass?: GlassSettings }) => {
    if (!board) return;
    queueSave({ ...board, ...patch });
  };

  const configuringWidget = useMemo(
    () => board?.widgets.find((w) => w.id === configuring) ?? null,
    [board, configuring],
  );

  if (boardQ.isLoading) return <div className="spin" />;
  if (boardQ.isError || !board) {
    return <div className="glass card t-crit">Could not load the “{slug}” board.</div>;
  }

  return (
    <div className="board-page">
      <div className="board-bar board-head">
        <div className="board-head-text">
          <h2 className="board-title">{board.name}</h2>
          <div className="board-sub t-dim">
            {board.widgets.length} widgets
            {board.updated_at ? ` · saved ${new Date(board.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
            {save.isPending ? ' · saving…' : ''}
          </div>
        </div>
        <span className="spacer" />
        {editMode ? (
          <>
            <button className="tb-btn" onClick={() => setAddOpen(true)}><Plus /> Add widget</button>
            <button className="tb-btn" onClick={() => setStyleOpen(true)}><Paintbrush /> Appearance</button>
            <button className="tb-btn" onClick={() => { setDraft(null); boardQ.refetch(); }}>
              <RotateCcw /> Reload
            </button>
            <button className="tb-btn primary" onClick={() => setEditMode(false)}><Check /> Done</button>
          </>
        ) : (
          <>
            <button className="tb-btn" title="Refetch every widget's data now"
              onClick={() => { qcRefreshAll(); }}><RefreshCw /> Refresh</button>
            <button className="tb-btn" onClick={() => setEditMode(true)}><Pencil /> Edit board</button>
          </>
        )}
      </div>

      <BoardGrid
        board={board}
        editMode={editMode}
        onLayoutChange={onLayoutChange}
        onRemove={removeWidget}
        onConfigure={setConfiguring}
        onOptionsChange={setWidgetOptions}
      />

      {board.widgets.length === 0 && (
        <div className="glass card page-stub">
          <div>
            <h2>This board is empty</h2>
            <p>Turn on <b>Edit board</b> and add a widget to get started.</p>
          </div>
        </div>
      )}

      <AddWidgetDrawer open={addOpen} onClose={() => setAddOpen(false)} onAdd={addWidget} />
      <BoardSettings
        open={styleOpen}
        onClose={() => setStyleOpen(false)}
        wallpaper={board.wallpaper}
        glass={board.glass}
        onChange={setStyle}
      />
      <WidgetSettings
        widget={configuringWidget}
        onClose={() => setConfiguring(null)}
        onChange={setWidgetOptions}
      />
    </div>
  );
}
