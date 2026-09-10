import { Modal } from '../components/Modal';
import { WIDGETS } from '../widgets/registry';

export function AddWidgetDrawer({
  open, onClose, onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (type: string) => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Add a widget" wide>
      <div className="widget-catalog">
        {WIDGETS.map((w) => (
          <button key={w.type} className="catalog-item glass" onClick={() => { onAdd(w.type); onClose(); }}>
            <span className="catalog-title">{w.label}</span>
            <span className="catalog-desc">{w.description}</span>
            <span className="catalog-size">{w.defaults.w}×{w.defaults.h}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
