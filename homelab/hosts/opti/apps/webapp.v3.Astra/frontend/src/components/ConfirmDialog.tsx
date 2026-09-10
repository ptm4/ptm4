// Confirmation with an optional type-the-name gate — the v1 confirmAction()
// contract, as a hook so any component can `await confirm({...})`.
import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { Modal } from './Modal';

export interface ConfirmOptions {
  title: string;
  body: ReactNode;
  tone?: 'warn' | 'crit';
  confirmLabel?: string;
  /** when set, the confirm button unlocks only once this exact string is typed */
  requireTyped?: string | null;
}

export function useConfirm() {
  const [pending, setPending] = useState<{ opts: ConfirmOptions; resolve: (ok: boolean) => void } | null>(null);
  const [typed, setTyped] = useState('');

  const confirm = useCallback((opts: ConfirmOptions) => new Promise<boolean>((resolve) => {
    setTyped('');
    setPending({ opts, resolve });
  }), []);

  const close = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };

  const dialog = pending ? (
    <Modal open onClose={() => close(false)} title={pending.opts.title}>
      <div className="confirm-body">{pending.opts.body}</div>
      {pending.opts.requireTyped && (
        <label className="form-row confirm-typed">
          <span>Type <code>{pending.opts.requireTyped}</code></span>
          <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
      )}
      <div className="w-actions">
        <button className="tb-btn" onClick={() => close(false)}>Cancel</button>
        <button
          className={`tb-btn ${pending.opts.tone === 'crit' ? 'danger' : 'primary'}`}
          disabled={!!pending.opts.requireTyped && typed !== pending.opts.requireTyped}
          onClick={() => close(true)}
        >
          {pending.opts.confirmLabel ?? 'Confirm'}
        </button>
      </div>
    </Modal>
  ) : null;

  return { confirm, dialog };
}
