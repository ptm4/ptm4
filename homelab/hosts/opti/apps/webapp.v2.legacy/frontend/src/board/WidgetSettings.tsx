// Per-widget options form, generated from the registry's option definitions —
// no per-widget form code exists anywhere in the app.
import { Modal } from '../components/Modal';
import { WIDGET_BY_TYPE } from '../widgets/registry';
import type { WidgetInstance } from '../lib/api-types';

export function WidgetSettings({
  widget, onClose, onChange,
}: {
  widget: WidgetInstance | null;
  onClose: () => void;
  onChange: (id: string, options: Record<string, unknown>) => void;
}) {
  if (!widget) return null;
  const def = WIDGET_BY_TYPE[widget.type];
  const options = widget.options ?? {};

  const set = (key: string, value: unknown) => onChange(widget.id, { ...options, [key]: value });

  return (
    <Modal open onClose={onClose} title={`${def?.label ?? widget.type} settings`}>
      {!def?.options?.length && <p className="t-dim">This widget has no options.</p>}
      <div className="form-rows">
        {(def?.options ?? []).map((o) => (
          <label key={o.key} className="form-row">
            <span>{o.label}</span>
            {o.type === 'select' && (
              <select value={String(options[o.key] ?? o.choices?.[0]?.value ?? '')}
                onChange={(e) => set(o.key, e.target.value)}>
                {o.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            )}
            {o.type === 'number' && (
              <input type="number" min={o.min} max={o.max}
                value={Number(options[o.key] ?? o.min ?? 0)}
                onChange={(e) => set(o.key, Number(e.target.value))} />
            )}
            {o.type === 'boolean' && (
              <input type="checkbox" checked={options[o.key] !== false}
                onChange={(e) => set(o.key, e.target.checked)} />
            )}
            {o.type === 'text' && (
              <input type="text" value={String(options[o.key] ?? '')}
                onChange={(e) => set(o.key, e.target.value)} />
            )}
          </label>
        ))}
      </div>
    </Modal>
  );
}
