// The board: a responsive react-grid-layout whose serialized layout IS the
// persisted document ({i,x,y,w,h} per breakpoint). Drag/resize are enabled only
// in edit mode, so a normal visit can't nudge the layout.
//
// RGL v2 notes (it differs from every v1 example on the web):
//   - neither responsive helper worked for this board: <ResponsiveGridLayout>
//     ignored the `cols`/`breakpoints` props (a 12-column board rendered in 4
//     columns), and useResponsiveLayout() kept its mount-time breakpoint when the
//     window was resized. Breakpoint selection is nine lines, so it lives here
//     and a plain <GridLayout> does the rendering.
//   - there is no WidthProvider; width is measured below. The library's
//     useContainerWidth() did not follow the container across a viewport change
//     (verified 2026-08-11: a phone-width window kept the desktop grid width).
//   - drag/resize are configured with dragConfig/resizeConfig objects, not the
//     v1 isDraggable/isResizable/draggableCancel props.
import { useEffect, useRef, useState } from 'react';
import {
  GridLayout, verticalCompactor,
  type Layout, type LayoutItem, type ResponsiveLayouts,
} from 'react-grid-layout';
import { Settings2, X } from 'lucide-react';
import type { BoardDoc, WidgetInstance } from '../lib/api-types';
import { WIDGET_BY_TYPE } from '../widgets/registry';
import { WidgetCtx } from './widget-ctx';
import { WidgetError } from '../widgets/kit';

// Exactly two breakpoints, matching the two layouts a board document stores.
// A third (md) was worse than useless: boards carry no md geometry, so it fell
// back to the 12-column lg coordinates, clamped every x into 8 columns, and
// compaction then stacked the whole board into one column on a normal laptop.
const COLS = { lg: 12, sm: 2 };
const BREAKPOINTS = { lg: 760, sm: 0 };
const ROW_HEIGHT = 62;
const MARGIN: [number, number] = [12, 12];

function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const apply = () => setWidth(el.getBoundingClientRect().width);
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    window.addEventListener('resize', apply);
    return () => { ro.disconnect(); window.removeEventListener('resize', apply); };
  }, []);

  return { ref, width };
}

function WidgetHost({
  widget, onOptionsChange,
}: {
  widget: WidgetInstance;
  onOptionsChange: (id: string, options: Record<string, unknown>) => void;
}) {
  const def = WIDGET_BY_TYPE[widget.type];
  if (!def) {
    return (
      <div className="w-card glass">
        <WidgetError message={`unknown widget type '${widget.type}'`} />
      </div>
    );
  }
  const Component = def.component;
  return (
    <WidgetCtx.Provider value={{ updateOptions: (options) => onOptionsChange(widget.id, options) }}>
      <Component options={widget.options} />
    </WidgetCtx.Provider>
  );
}

export function BoardGrid({
  board, editMode, onLayoutChange, onRemove, onConfigure, onOptionsChange,
}: {
  board: BoardDoc;
  editMode: boolean;
  onLayoutChange: (layouts: ResponsiveLayouts) => void;
  onRemove: (id: string) => void;
  onConfigure: (id: string) => void;
  onOptionsChange: (id: string, options: Record<string, unknown>) => void;
}) {
  const { ref, width } = useMeasuredWidth();

  // A widget with no layout entry (added at another breakpoint, or a preset that
  // predates it) still has to render — give it a default-sized slot at the end.
  const layouts: ResponsiveLayouts = {};
  for (const bp of Object.keys(COLS) as (keyof typeof COLS)[]) {
    const existing = board.layouts[bp] ?? board.layouts.lg ?? [];
    const byId = new Map(existing.map((l) => [l.i, l]));
    layouts[bp] = board.widgets.map((w, idx): LayoutItem => {
      const def = WIDGET_BY_TYPE[w.type];
      const found = byId.get(w.id);
      const minW = def?.min?.w != null ? Math.min(def.min.w, COLS[bp]) : undefined;
      if (found) return { ...found, w: Math.min(found.w, COLS[bp]), minW, minH: def?.min?.h };
      return {
        i: w.id,
        x: 0,
        y: 1000 + idx,
        w: Math.min(def?.defaults.w ?? 4, COLS[bp]),
        h: def?.defaults.h ?? 3,
        minW,
        minH: def?.min?.h,
      };
    });
  }

  // Largest breakpoint whose min-width the measured container clears.
  const bp = (Object.keys(BREAKPOINTS) as (keyof typeof COLS)[])
    .sort((a, b) => BREAKPOINTS[b] - BREAKPOINTS[a])
    .find((k) => width >= BREAKPOINTS[k]) ?? 'sm';

  const handleLayoutChange = (layout: Layout) => {
    if (!editMode) return;
    // Write back only the breakpoint being edited; the other keeps its own geometry.
    onLayoutChange({ ...layouts, [bp]: layout });
  };

  return (
    <div ref={ref}>
      {width > 0 && (
        <GridLayout
          className={`board${editMode ? ' editing' : ''}`}
          width={width}
          layout={layouts[bp]}
          gridConfig={{
            cols: COLS[bp],
            rowHeight: ROW_HEIGHT,
            margin: MARGIN,
            containerPadding: [0, 0],
          }}
          compactor={verticalCompactor}
          dragConfig={{ enabled: editMode, cancel: '.w-actions,button,a,input,select,textarea' }}
          resizeConfig={{ enabled: editMode }}
          onLayoutChange={handleLayoutChange}
        >
          {board.widgets.map((w) => (
            <div key={w.id} className="board-item">
              {editMode && (
                <div className="w-edit-bar">
                  <button className="w-edit-btn" title="Configure" onClick={() => onConfigure(w.id)}><Settings2 /></button>
                  <button className="w-edit-btn danger" title="Remove" onClick={() => onRemove(w.id)}><X /></button>
                </div>
              )}
              <WidgetHost widget={w} onOptionsChange={onOptionsChange} />
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  );
}
