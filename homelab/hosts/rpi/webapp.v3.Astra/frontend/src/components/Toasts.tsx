import { useToasts } from '../lib/toast';

export function Toasts() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);
  if (!toasts.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast glass-strong" data-s={t.tone} onClick={() => dismiss(t.id)}>
          {t.message}
        </div>
      ))}
    </div>
  );
}
