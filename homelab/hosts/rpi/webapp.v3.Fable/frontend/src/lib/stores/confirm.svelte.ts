// Confirmation with an optional type-the-name gate — the v1 confirmAction()
// contract as an awaitable: `if (await confirm({...})) doIt()`. One <ConfirmHost/>
// in the root layout renders whatever is pending, so any component or plain
// function can ask without owning a dialog.

export interface ConfirmOptions {
  title: string;
  /** main copy (plain text; line breaks respected) */
  body: string;
  /** the ⚠ blast-radius line, rendered in the tone colour */
  danger?: string;
  /** a quiet footnote */
  note?: string;
  tone?: 'warn' | 'crit';
  confirmLabel?: string;
  /** when set, the confirm button unlocks only once this exact string is typed */
  requireTyped?: string | null;
}

interface Pending { opts: ConfirmOptions; resolve: (ok: boolean) => void }

let pending = $state<Pending | null>(null);

export const confirmState = {
  get pending() { return pending; },
  close(ok: boolean) {
    pending?.resolve(ok);
    pending = null;
  },
};

export function confirm(opts: ConfirmOptions): Promise<boolean> {
  // A second request while one is open cancels the first — nothing stacks.
  pending?.resolve(false);
  return new Promise<boolean>((resolve) => { pending = { opts, resolve }; });
}
