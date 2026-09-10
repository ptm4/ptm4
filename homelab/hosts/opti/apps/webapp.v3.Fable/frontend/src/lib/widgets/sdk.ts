// The widget prop/context contract shared by the surviving standalone widgets
// (HostVitals, hldb/Changes, hldb/LongTrends — used by routes/host/[name]).
import { getContext } from 'svelte';

export interface WidgetProps {
  options?: Record<string, unknown>;
}

// Lets a widget persist its own options from inside its body (e.g. the host
// tile's click-to-cycle graph range) without owning any board plumbing. The
// board grid provides it; a widget rendered outside a board gets null and
// falls back to local state.
export interface WidgetContext {
  /** the widget instance id on the board */
  readonly id: string;
  /** merge-and-save these options into the board document */
  updateOptions: (options: Record<string, unknown>) => void;
}

export const WIDGET_CTX = Symbol('widget');

export function getWidgetContext(): WidgetContext | null {
  try { return getContext<WidgetContext>(WIDGET_CTX) ?? null; } catch { return null; }
}

// Resolve an option with the registry default, then the widget's own fallback.
export function opt<T>(options: Record<string, unknown> | undefined, key: string, fallback: T): T {
  const v = options?.[key];
  return (v === undefined || v === null || v === '') ? fallback : (v as T);
}
