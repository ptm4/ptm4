// Lets a widget persist its own options from inside its body (e.g. the host
// tile's click-to-cycle graph range) without owning any board plumbing. The
// board page provides it; a widget rendered outside a board gets null and
// falls back to local state.
import { createContext } from 'react';

export interface WidgetContextValue {
  /** merge-and-save this widget's options into the board document */
  updateOptions: (options: Record<string, unknown>) => void;
}

export const WidgetCtx = createContext<WidgetContextValue | null>(null);
