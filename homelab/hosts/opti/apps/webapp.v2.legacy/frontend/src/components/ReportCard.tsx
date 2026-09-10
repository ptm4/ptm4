// One runner/security report as a card — port of v1's buildReportCard, with the
// enable/disable + run-now dispatcher controls.
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { post, ApiError } from '../lib/api';
import { toast } from '../lib/toast';
import { localeDateTime } from '../lib/format';
import { StatusBadge, dispatcherErrorMessage } from './report-bits';

export interface ReportMeta {
  name: string;
  label: string;
  agent: string | null;
  status: string;
  summary: string;
  run_at: string | null;
  stale: boolean;
  has_alert?: boolean;
  enabled: boolean;
}

export function ReportCard({
  report, apiBase, actions, onTail,
}: {
  report: ReportMeta;
  apiBase: 'runners' | 'reports';
  actions: React.ReactNode;
  /** open the live log drawer for this runner (runners only) */
  onTail?: (name: string, label: string) => void;
}) {
  const qc = useQueryClient();

  const toggle = useMutation({
    mutationFn: () =>
      post(`/api/${apiBase}/${encodeURIComponent(report.agent!)}/enabled`, { enabled: !report.enabled }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: [apiBase] }); },
    onError: (e) => {
      const err = e as ApiError;
      toast(dispatcherErrorMessage(err.status ?? 0, err.message), 'crit', { ttlMs: 8000 });
    },
  });

  const run = useMutation({
    mutationFn: () => post(`/api/${apiBase}/${encodeURIComponent(report.agent!)}/run`),
    onSuccess: () => {
      toast(`${report.label} queued`, 'ok');
      // v1 fired and forgot for ~90s; the drawer tails the runner's own log instead.
      onTail?.(report.name, report.label);
    },
    onError: (e) => {
      const err = e as ApiError;
      toast(dispatcherErrorMessage(err.status ?? 0, err.message), 'crit', { ttlMs: 8000 });
    },
  });

  return (
    <article className={`report-card glass card${report.enabled ? '' : ' disabled'}`} data-s={report.status}>
      <header>
        <StatusBadge status={report.status} />
        <h3>{report.label}</h3>
        {report.has_alert && <span className="badge badge-alert" title="Alert flagged in this report">ALERT</span>}
        {report.stale && <span className="badge badge-stale" title="No fresh run recently">STALE</span>}
      </header>
      <p className="report-summary">{report.summary || 'No summary available'}</p>
      <div className="report-meta">Last run: {localeDateTime(report.run_at)}</div>
      <footer className="report-actions">
        {actions}
        {report.agent && (
          <>
            <button
              className={`tb-btn toggle ${report.enabled ? 'on' : 'off'}`}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate()}
            >
              {report.enabled ? 'Enabled' : 'Disabled'}
            </button>
            <button className="tb-btn" disabled={run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? 'Queued…' : 'Run now'}
            </button>
          </>
        )}
      </footer>
    </article>
  );
}
