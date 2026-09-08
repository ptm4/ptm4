// Toast store — the v1 toast() contract (message + tone, auto-expiring) as a
// zustand store any component or mutation can call.
import { create } from 'zustand';

export type Tone = 'ok' | 'warn' | 'crit' | 'info';

export interface Toast {
  id: number;
  message: string;
  tone: Tone;
  sticky?: boolean;
}

interface ToastState {
  toasts: Toast[];
  push: (message: string, tone?: Tone, opts?: { sticky?: boolean; ttlMs?: number }) => number;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push(message, tone = 'info', opts = {}) {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, message, tone, sticky: opts.sticky }] }));
    if (!opts.sticky) {
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
      }, opts.ttlMs ?? 5000);
    }
    return id;
  },
  dismiss(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));

export const toast = (message: string, tone: Tone = 'info', opts?: { sticky?: boolean; ttlMs?: number }) =>
  useToasts.getState().push(message, tone, opts);
