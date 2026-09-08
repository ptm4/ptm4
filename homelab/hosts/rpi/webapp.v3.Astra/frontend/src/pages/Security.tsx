// Security page — the security-agent reports (journal hunter, persistence auditor…)
// off /api/reports, same card grammar as the Runners page.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { ReportCard, type ReportMeta } from '../components/ReportCard';
import { ReportModal } from './Reports';

interface ReportsResp { reports: ReportMeta[]; message?: string; }

export default function SecurityPage() {
  const [detail, setDetail] = useState<{ name: string; label: string } | null>(null);

  const q = useQuery({
    queryKey: ['reports'],
    queryFn: () => get<ReportsResp>('/api/reports'),
    refetchInterval: 5 * 60_000,
  });

  return (
    <div className="reports-page">
      {q.isError && <div className="glass card t-crit">Cannot reach /api/reports — is the backend running?</div>}
      {q.data?.reports.length === 0 && (
        <div className="glass card">{q.data.message ?? 'No security reports yet.'}</div>
      )}

      <div className="report-grid">
        {(q.data?.reports ?? []).map((r) => (
          <ReportCard
            key={r.name}
            report={r}
            apiBase="reports"
            actions={
              <button className="tb-btn" onClick={() => setDetail({ name: r.name, label: r.label })}>
                View details
              </button>
            }
          />
        ))}
      </div>

      {detail && (
        <ReportModal name={detail.name} label={detail.label} apiBase="reports" onClose={() => setDetail(null)} />
      )}
    </div>
  );
}
