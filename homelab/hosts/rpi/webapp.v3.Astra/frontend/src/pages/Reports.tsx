// Runners page — the scheduled collectors (doctor, hardware, software, network,
// coldcopy) with enable/run controls, latest-report viewer and per-run history.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { toast } from '../lib/toast';
import { Modal } from '../components/Modal';
import { ReportCard, type ReportMeta } from '../components/ReportCard';
import { ReportBody, type ReportDoc } from '../components/report-bits';
import { LogTail } from '../components/LogTail';
import { localeDateTime, relTime } from '../lib/format';

interface RunnersResp { runners: ReportMeta[]; }
interface AgentsResp { hosts: { reachable: boolean; drift_count?: number }[]; }
interface HistoryResp { history: { date: string; size: number; mtime: string | null }[]; }

type ModalState =
  | { kind: 'none' }
  | { kind: 'report'; name: string; label: string; date?: string }
  | { kind: 'history'; name: string; label: string };

export default function ReportsPage() {
  const [modal, setModal] = useState<ModalState>({ kind: 'none' });
  const [tail, setTail] = useState<{ name: string; label: string } | null>(null);

  const runners = useQuery({
    queryKey: ['runners'],
    queryFn: () => get<RunnersResp>('/api/runners'),
    refetchInterval: 5 * 60_000,
  });

  const agents = useQuery({
    queryKey: ['agents-strip'],
    queryFn: () => get<AgentsResp>('/api/agents', 15_000),
    refetchInterval: 5 * 60_000,
  });

  const unreachable = agents.data?.hosts.filter((h) => !h.reachable).length ?? 0;
  const drift = agents.data?.hosts.reduce((n, h) => n + (h.drift_count || 0), 0) ?? 0;

  return (
    <div className="reports-page">
      <div className="agents-strip glass card">
        🛰️ Architecture agents
        {agents.data && (
          <>
            {' — '}{agents.data.hosts.length} host(s)
            {unreachable > 0 && <> · <span className="t-crit">{unreachable} unreachable</span></>}
            {drift > 0 && <> · <span className="t-warn">{drift} drift</span></>}
          </>
        )}
        {' — '}<a href="/agents/">view status →</a>
      </div>

      {runners.isError && (
        <div className="glass card t-crit">Cannot reach /api/runners — is the backend running?</div>
      )}
      {runners.data?.runners.length === 0 && (
        <div className="glass card">
          No runner reports yet. Run them from opti (GitHub Actions or the dispatcher).
        </div>
      )}

      <div className="report-grid">
        {(runners.data?.runners ?? []).map((r) => (
          <ReportCard
            key={r.name}
            report={r}
            apiBase="runners"
            onTail={(name, label) => setTail({ name, label })}
            actions={
              <>
                <button className="tb-btn" onClick={() => setModal({ kind: 'report', name: r.name, label: r.label })}>
                  View latest
                </button>
                <button className="tb-btn" onClick={() => setModal({ kind: 'history', name: r.name, label: r.label })}>
                  History
                </button>
                <button className="tb-btn" onClick={() => setTail({ name: r.name, label: r.label })}>
                  Log
                </button>
              </>
            }
          />
        ))}
      </div>

      {tail && <LogTail name={tail.name} label={tail.label} onClose={() => setTail(null)} />}

      {modal.kind === 'report' && (
        <ReportModal
          name={modal.name}
          label={modal.label}
          date={modal.date}
          onClose={() => setModal({ kind: 'none' })}
        />
      )}
      {modal.kind === 'history' && (
        <HistoryModal
          name={modal.name}
          label={modal.label}
          onOpenDate={(date) => setModal({ kind: 'report', name: modal.name, label: modal.label, date })}
          onClose={() => setModal({ kind: 'none' })}
        />
      )}
    </div>
  );
}

export function ReportModal({
  name, label, date, onClose, apiBase = 'runners',
}: {
  name: string; label: string; date?: string; onClose: () => void; apiBase?: 'runners' | 'reports';
}) {
  const url = date ? `/api/runners/${name}/report/${date}` : `/api/${apiBase}/${name}`;
  const q = useQuery({ queryKey: ['report', url], queryFn: () => get<ReportDoc>(url) });

  if (q.isError) {
    toast(`Could not load report: ${name}`, 'crit');
    onClose();
    return null;
  }

  const suffix = date ? ` — ${date}` : q.data?.run_at ? ` — ${localeDateTime(q.data.run_at)}` : '';
  return (
    <Modal open onClose={onClose} title={`${label}${suffix}`} wide>
      {q.isLoading ? <div className="spin" /> : q.data ? <ReportBody data={q.data} /> : null}
    </Modal>
  );
}

function HistoryModal({
  name, label, onOpenDate, onClose,
}: {
  name: string; label: string; onOpenDate: (date: string) => void; onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ['history', name],
    queryFn: () => get<HistoryResp>(`/api/runners/${name}/history`),
  });

  return (
    <Modal open onClose={onClose} title={`${label} — history`}>
      {q.isLoading && <div className="spin" />}
      {q.data && q.data.history.length === 0 && <p>No dated snapshots for this runner yet.</p>}
      {q.data && q.data.history.length > 0 && (
        <table className="detail-table">
          <tbody>
            {q.data.history.map((h) => (
              <tr key={h.date}>
                <td><button className="link-btn" onClick={() => onOpenDate(h.date)}>{h.date}</button></td>
                <td>{(h.size / 1024).toFixed(1)} KB</td>
                <td>{relTime(h.mtime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
