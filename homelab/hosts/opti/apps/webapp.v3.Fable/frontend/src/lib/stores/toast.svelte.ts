// Toast store — the v1/v2 toast() contract (message + tone, auto-expiring) as a
// runes store any component or mutation can call.

export type ToastTone = 'ok' | 'warn' | 'crit' | 'info';

export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
  sticky?: boolean;
}

let nextId = 1;
let list = $state<Toast[]>([]);

export const toasts = {
  get list() { return list; },
  push(message: string, tone: ToastTone = 'info', opts: { sticky?: boolean; ttlMs?: number } = {}): number {
    const id = nextId++;
    list = [...list, { id, message, tone, sticky: opts.sticky }];
    if (!opts.sticky) {
      setTimeout(() => { list = list.filter((t) => t.id !== id); }, opts.ttlMs ?? 5000);
    }
    return id;
  },
  dismiss(id: number) {
    list = list.filter((t) => t.id !== id);
  },
};

export const toast = (message: string, tone: ToastTone = 'info', opts?: { sticky?: boolean; ttlMs?: number }) =>
  toasts.push(message, tone, opts);
