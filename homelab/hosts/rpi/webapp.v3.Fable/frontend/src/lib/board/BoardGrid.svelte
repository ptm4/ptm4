<script lang="ts">
  // The board: gridstack owns positions, Svelte owns the DOM inside each item. The
  // persisted document ({i,x,y,w,h} per breakpoint) is the source of truth — this
  // component maps it onto gridstack nodes and reads it back on change.
  //
  // Exactly two breakpoints, matching the two layouts a board document stores
  // (lg = 12 columns, sm = 2 columns). Breakpoint selection is measured here,
  // not delegated to gridstack's responsive mode, because gridstack would compute
  // its own sm layout instead of loading the one the document carries.
  //
  // Drag/resize only in edit mode (static grid otherwise), so a normal visit can't
  // nudge the layout.
  import { onMount } from 'svelte';
  import { GridStack, type GridItemHTMLElement, type GridStackNode } from 'gridstack';
  import { Settings2, X } from '@lucide/svelte';
  import type { BoardDoc, GridItem } from '$lib/api/types';
  import { WIDGET_BY_TYPE } from '$lib/widgets/registry';
  import WidgetHost from './WidgetHost.svelte';

  type Bp = 'lg' | 'sm';
  const COLS: Record<Bp, number> = { lg: 12, sm: 2 };
  const BREAK = 760;
  const ROW_HEIGHT = 62;
  const MARGIN = 12;

  let {
    board,
    editMode = false,
    onLayoutChange,
    onRemove,
    onConfigure,
    onOptionsChange,
  }: {
    board: BoardDoc;
    editMode?: boolean;
    onLayoutChange: (layouts: Record<string, GridItem[]>) => void;
    onRemove: (id: string) => void;
    onConfigure: (id: string) => void;
    onOptionsChange: (id: string, options: Record<string, unknown>) => void;
  } = $props();

  let host: HTMLDivElement;
  let gridEl: HTMLDivElement;
  let grid: GridStack | null = null;
  let bp: Bp = 'lg';
  let applying = false;
  const items = new Map<string, GridItemHTMLElement>();
  const pending: GridItemHTMLElement[] = [];

  // A widget with no layout entry (added at another breakpoint, or a preset that
  // predates it) still has to render — give it a default-sized slot at the end.
  function nodeFor(id: string, b: Bp) {
    const inst = board.widgets.find((x) => x.id === id);
    const def = inst ? WIDGET_BY_TYPE[inst.type] : undefined;
    const existing = board.layouts[b] ?? board.layouts.lg ?? [];
    const found = existing.find((l) => l.i === id);
    const cols = COLS[b];
    // Registry minimums describe the 12-column grid. Never let them exceed the
    // stored size, or a stat tile saved at w:1 on the 2-column layout gets widened
    // to its lg minimum and every neighbour re-stacks beneath it.
    const w = found ? Math.min(found.w, cols) : Math.min(def?.defaults.w ?? 4, cols);
    const h = found ? found.h : (def?.defaults.h ?? 3);
    const minW = def?.min?.w != null ? Math.min(def.min.w, cols, w) : undefined;
    const minH = def?.min?.h != null ? Math.min(def.min.h, h) : undefined;
    if (found) return { id, x: Math.min(found.x, cols - w), y: found.y, w, h, minW, minH };
    const idx = board.widgets.findIndex((x) => x.id === id);
    return { id, x: 0, y: 1000 + idx, w, h, minW, minH };
  }

  function register(el: GridItemHTMLElement) {
    const id = el.dataset.id!;
    items.set(id, el);
    if (!grid) { pending.push(el); return; }
    applying = true;
    grid.makeWidget(el, nodeFor(id, bp));
    applying = false;
  }
  function unregister(el: GridItemHTMLElement) {
    items.delete(el.dataset.id!);
    if (grid && el.gridstackNode) grid.removeWidget(el, false, false);
  }
  function gridItem(el: HTMLElement) {
    register(el as GridItemHTMLElement);
    return { destroy() { unregister(el as GridItemHTMLElement); } };
  }

  function applyLayout() {
    if (!grid) return;
    applying = true;
    grid.batchUpdate();
    for (const [id, el] of items) grid.update(el, nodeFor(id, bp));
    grid.batchUpdate(false);
    applying = false;
  }

  function readLayout(): GridItem[] {
    return (grid!.save(false) as GridStackNode[]).map((n) => ({
      i: String(n.id), x: n.x ?? 0, y: n.y ?? 0, w: n.w ?? 1, h: n.h ?? 1,
    }));
  }

  function bpFor(width: number): Bp { return width >= BREAK ? 'lg' : 'sm'; }

  onMount(() => {
    bp = bpFor(host.getBoundingClientRect().width);
    grid = GridStack.init({
      column: COLS[bp],
      cellHeight: ROW_HEIGHT,
      margin: MARGIN,
      float: false,
      animate: true,
      auto: false,
      staticGrid: !editMode,
      alwaysShowResizeHandle: 'mobile',
      draggable: { cancel: '.w-actions,.w-edit-bar,button,a,input,select,textarea,.spark-box' },
      resizable: { handles: 'se' },
    }, gridEl)!;
    grid.batchUpdate();
    for (const el of pending.splice(0)) grid.makeWidget(el, nodeFor(el.dataset.id!, bp));
    grid.batchUpdate(false);

    grid.on('change', () => {
      if (applying || !editMode || !grid || grid.isIgnoreChangeCB()) return;
      // Write back only the breakpoint being edited; the other keeps its own geometry.
      onLayoutChange({ ...board.layouts, [bp]: readLayout() });
    });

    const ro = new ResizeObserver(() => {
      const next = bpFor(host.getBoundingClientRect().width);
      if (next !== bp && grid) {
        bp = next;
        applying = true;
        grid.column(COLS[bp], 'none');
        applying = false;
        applyLayout();
      }
    });
    ro.observe(host);

    return () => { ro.disconnect(); grid?.destroy(false); grid = null; };
  });

  $effect(() => { grid?.setStatic(!editMode); });

  // External layout changes (reload, 409 recovery, a widget added) re-apply the
  // document. The stringify guard keeps a drag's own write-back from bouncing.
  let lastApplied = '';
  $effect(() => {
    const key = JSON.stringify(board.layouts);
    if (key !== lastApplied) {
      lastApplied = key;
      if (grid) applyLayout();
    }
  });
</script>

<div bind:this={host} class="board-host">
  <div class="grid-stack board" class:editing={editMode} bind:this={gridEl}>
    {#each board.widgets as w (w.id)}
      <div class="grid-stack-item board-item" data-id={w.id} use:gridItem>
        <div class="grid-stack-item-content">
          {#if editMode}
            <div class="w-edit-bar">
              <button class="w-edit-btn" title="Configure" onclick={() => onConfigure(w.id)}><Settings2 /></button>
              <button class="w-edit-btn danger" title="Remove" onclick={() => onRemove(w.id)}><X /></button>
            </div>
          {/if}
          <WidgetHost widget={w} {onOptionsChange} />
        </div>
      </div>
    {/each}
  </div>
</div>
