// The widget SDK contract. A registry entry is everything the board engine needs
// to place, size, configure and render one widget type — so adding a feature to
// this dashboard means adding an entry to registry.ts, not editing a page.
//
//   component  the renderer; a Svelte component receiving { options }
//   defaults   initial grid size when the widget is added
//   min        resize bounds enforced by gridstack
//   options    the configurable fields; drives the settings dialog with no
//              per-widget form code. `default` is applied when the option is unset.
import { getContext, type Component } from 'svelte';

export interface OptionDef {
  key: string;
  label: string;
  type: 'select' | 'number' | 'boolean' | 'text';
  choices?: { value: string; label: string }[];
  min?: number;
  max?: number;
  default?: unknown;
}

export interface WidgetProps {
  options?: Record<string, unknown>;
}

export interface WidgetDef {
  type: string;
  label: string;
  description: string;
  component: Component<WidgetProps>;
  defaults: { w: number; h: number };
  min?: { w: number; h: number };
  options?: OptionDef[];
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
