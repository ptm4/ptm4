<script lang="ts">
  // A board page: renders the grid, owns edit mode, and persists changes with
  // optimistic-concurrency (`rev`). Local edits apply instantly; the save is
  // debounced so a drag doesn't write once per animation frame.
  import { onDestroy } from 'svelte';
  import { page } from '$app/state';
  import { useQueryClient } from '@tanstack/svelte-query';
  import { Pencil, Plus, Paintbrush, Check, RotateCcw, RefreshCw } from '@lucide/svelte';
  import { useBoard, useSaveBoard, useSettings, applyBoardStyle } from '$lib/api/boards';
  import { ApiError } from '$lib/api/client';
  import { app } from '$lib/stores/ui.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import BoardGrid from '$lib/board/BoardGrid.svelte';
  import AddWidgetDrawer from '$lib/board/AddWidgetDrawer.svelte';
  import WidgetSettings from '$lib/board/WidgetSettings.svelte';
  import BoardSettings from '$lib/board/BoardSettings.svelte';
  import { WIDGET_BY_TYPE } from '$lib/widgets/registry';
  import type { BoardDoc, GlassSettings, GridItem } from '$lib/api/types';

  const SAVE_DEBOUNCE_MS = 800;

  let slug = $derived(page.params.slug ?? 'home');
  const boardQ = useBoard(() => slug);
  const settingsQ = useSettings();
  const save = useSaveBoard(() => slug);
  const qc = useQueryClient();

  // `draft` is the live document while editing; null means "showing the server's".
  let draft = $state<BoardDoc | null>(null);
  let addOpen = $state(false);
  let styleOpen = $state(false);
  let configuring = $state<string | null>(null);
  let saveTimer: number | null = null;

  let board = $derived(draft ?? boardQ.data ?? null);
  let editMode = $derived(app.editMode);

  // Switching boards drops any draft from the previous one.
  $effect(() => { slug; draft = null; app.setEdit(false); });

  // Wallpaper + glass are global CSS variables: board choice wins, global settings
  // fill in, and this re-runs on every draft change so editing previews live.
  $effect(() => {
    if (!board) return;
    applyBoardStyle(
      board.wallpaper ?? settingsQ.data?.wallpaper ?? null,
      board.glass ?? settingsQ.data?.glass ?? null,
      settingsQ.data?.reduce_glass ?? false,
    );
  });
  onDestroy(() => {
    if (saveTimer) window.clearTimeout(saveTimer);
    app.setEdit(false);
    if (typeof document !== 'undefined') applyBoardStyle(null, null, false);
  });

  // The always-available refresh: invalidate every data query at once (the board
  // document itself is deliberately excluded — an unsaved draft must survive).
  function refreshAll() {
    qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'board' });
    toast('Refreshing every widget…', 'info', { ttlMs: 2000 });
  }

  function queueSave(next: BoardDoc) {
    draft = next;
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      save.mutate(next, {
        onSuccess: (saved) => { draft = saved; },
        onError: (e) => {
          const err = e as ApiError;
          if (err.status === 409) {
            toast('This board changed in another tab — reloading it', 'warn');
            draft = null;
            boardQ.refetch();
          } else {
            toast(`Could not save the board: ${err.message}`, 'crit', { ttlMs: 8000 });
          }
        },
      });
    }, SAVE_DEBOUNCE_MS);
  }

  function onLayoutChange(layouts: Record<string, GridItem[]>) {
    if (!board) return;
    const clean: Record<string, GridItem[]> = {};
    for (const [bp, items] of Object.entries(layouts)) {
      clean[bp] = (items ?? []).map(({ i, x, y, w, h }) => ({ i, x, y, w, h }));
    }
    if (JSON.stringify(clean) === JSON.stringify(board.layouts)) return;
    queueSave({ ...board, layouts: clean });
  }

  function addWidget(type: string) {
    if (!board) return;
    const def = WIDGET_BY_TYPE[type];
    const id = `w-${type}-${Math.random().toString(36).slice(2, 7)}`;
    const maxY = Math.max(0, ...(board.layouts.lg ?? []).map((l) => l.y + l.h));
    const options: Record<string, unknown> = {};
    for (const o of def.options ?? []) if (o.default !== undefined) options[o.key] = o.default;
    queueSave({
      ...board,
      widgets: [...board.widgets, { id, type, options }],
      layouts: {
        ...board.layouts,
        lg: [...(board.layouts.lg ?? []), { i: id, x: 0, y: maxY, w: def.defaults.w, h: def.defaults.h }],
        sm: [...(board.layouts.sm ?? []), { i: id, x: 0, y: maxY, w: Math.min(2, def.defaults.w), h: def.defaults.h }],
      },
    });
    toast(`${def.label} added`, 'ok');
  }

  function removeWidget(id: string) {
    if (!board) return;
    const layouts = Object.fromEntries(
      Object.entries(board.layouts).map(([bp, items]) => [bp, items.filter((l) => l.i !== id)]),
    );
    queueSave({ ...board, widgets: board.widgets.filter((w) => w.id !== id), layouts });
  }

  function setWidgetOptions(id: string, options: Record<string, unknown>) {
    if (!board) return;
    queueSave({ ...board, widgets: board.widgets.map((w) => (w.id === id ? { ...w, options } : w)) });
  }

  function setStyle(patch: { wallpaper?: string | null; glass?: GlassSettings }) {
    if (!board) return;
    queueSave({ ...board, ...patch });
  }

  let configuringWidget = $derived(board?.widgets.find((w) => w.id === configuring) ?? null);
</script>

{#if boardQ.isLoading}
  <div class="spin"></div>
{:else if boardQ.isError || !board}
  <div class="card t-crit">Could not load the “{slug}” board{boardQ.error ? ` — ${(boardQ.error as Error).message}` : ''}.</div>
{:else}
  <div class="board-page">
    <div class="board-bar board-head">
      <div>
        <h1 class="board-title">{board.name}</h1>
        <div class="board-sub">
          {board.widgets.length} widgets
          {board.updated_at ? ` · saved ${new Date(board.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
          {save.isPending ? ' · saving…' : ''}
        </div>
      </div>
      <span class="spacer"></span>
      {#if editMode}
        <button class="tbtn" onclick={() => (addOpen = true)}><Plus /> Add widget</button>
        <button class="tbtn" onclick={() => (styleOpen = true)}><Paintbrush /> Appearance</button>
        <button class="tbtn" onclick={() => { draft = null; boardQ.refetch(); }}><RotateCcw /> Reload</button>
        <button class="tbtn primary" onclick={() => app.setEdit(false)}><Check /> Done</button>
      {:else}
        <button class="tbtn" title="Refetch every widget's data now" onclick={refreshAll}><RefreshCw /> Refresh</button>
        <button class="tbtn" onclick={() => app.setEdit(true)}><Pencil /> Edit board</button>
      {/if}
    </div>

    <BoardGrid
      {board}
      {editMode}
      {onLayoutChange}
      onRemove={removeWidget}
      onConfigure={(id) => (configuring = id)}
      onOptionsChange={setWidgetOptions}
    />

    {#if board.widgets.length === 0}
      <div class="card page-stub">
        <div>
          <h2>This board is empty</h2>
          <p>Turn on <b>Edit board</b> and add a widget to get started.</p>
        </div>
      </div>
    {/if}

    <AddWidgetDrawer bind:open={addOpen} onAdd={addWidget} />
    <BoardSettings bind:open={styleOpen} wallpaper={board.wallpaper} glass={board.glass} onChange={setStyle} />
    <WidgetSettings widget={configuringWidget} onClose={() => (configuring = null)} onChange={setWidgetOptions} />
  </div>
{/if}
