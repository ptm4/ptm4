// Notification center — the topbar bell and its drawer. Findings that already
// exist in the reports become an inbox you can clear, so the dashboard is the
// pager instead of something you have to remember to go read.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, Check, CheckCheck } from 'lucide-react';
import { get, post } from '../lib/api';
import { relTime } from '../lib/format';
import { Modal } from './Modal';

export interface Notification {
  id: string;
  source: string;
  severity: string;
  host: string | null;
  message: string;
  ts: string | null;
  acked: boolean;
}

interface NotificationsResp { items: Notification[]; unacked: number; total: number }

export function useNotifications(all = false) {
  return useQuery({
    queryKey: ['notifications', all],
    queryFn: () => get<NotificationsResp>(`/api/notifications${all ? '?all=1' : ''}`, 15_000),
    refetchInterval: 5 * 60_000,
  });
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [showAcked, setShowAcked] = useState(false);
  const q = useNotifications(showAcked);
  const qc = useQueryClient();

  const ack = useMutation({
    mutationFn: ({ id, acked }: { id: string; acked: boolean }) =>
      post(`/api/notifications/${id}/ack`, { acked }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const ackAll = useMutation({
    mutationFn: () => post('/api/notifications/ack-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const unacked = q.data?.unacked ?? 0;

  return (
    <>
      <button className="tb-btn" onClick={() => setOpen(true)} title="Notifications">
        <Bell />
        {unacked > 0 && <span className="bell-badge" data-s={unacked > 5 ? 'crit' : 'warn'}>{unacked}</span>}
      </button>

      {open && (
        <Modal open onClose={() => setOpen(false)} title={`Notifications — ${unacked} open`} wide>
          <div className="w-actions notif-actions">
            <label className="t-dim">
              <input type="checkbox" checked={showAcked} onChange={(e) => setShowAcked(e.target.checked)} />
              {' '}show acknowledged
            </label>
            <span className="spacer" />
            <button className="tb-btn" disabled={ackAll.isPending || unacked === 0}
              onClick={() => ackAll.mutate()}>
              <CheckCheck /> Acknowledge all
            </button>
          </div>

          {q.data?.items.length === 0 && (
            <p className="t-dim">Nothing open — every finding has been acknowledged.</p>
          )}

          <div className="notif-list">
            {(q.data?.items ?? []).map((n) => (
              <div key={n.id} className={`notif${n.acked ? ' acked' : ''}`} data-sev={n.severity}>
                <span className="notif-sev">{n.severity.toUpperCase()}</span>
                <div className="notif-body">
                  <div>{n.message}</div>
                  <div className="t-dim notif-meta">
                    {n.host ? `${n.host} · ` : ''}{n.source} · {relTime(n.ts)}
                  </div>
                </div>
                <button className="tb-btn" title={n.acked ? 'Un-acknowledge' : 'Acknowledge'}
                  disabled={ack.isPending}
                  onClick={() => ack.mutate({ id: n.id, acked: !n.acked })}>
                  <Check />
                </button>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}
