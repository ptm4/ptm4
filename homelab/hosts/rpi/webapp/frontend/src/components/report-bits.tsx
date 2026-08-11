// Shared rendering for runner/security reports: status badges, finding lists,
// key/value tables and the full-report body — React ports of v1's
// renderAgentReport / renderFindingList / renderReportData / kvTable.
// JSX auto-escaping replaces the 195 manual escHtml() calls of v1.
import type { ReactNode } from 'react';
import { Markdown } from './Markdown';
import { localeDateTime } from '../lib/format';

export interface Finding {
  severity?: string;
  message?: string;
}

export interface ReportDoc {
  status?: string;
  summary?: string;
  run_at?: string;
  findings?: Finding[];
  recommendations?: Finding[];
  log?: string;
  hosts?: { host?: string; summary?: string; metrics?: Record<string, unknown> }[];
  [key: string]: unknown;
}

export function StatusBadge({ status }: { status?: string }) {
  const s = (status || 'unknown').toLowerCase();
  return <span className="status-badge" data-s={s}>{s === 'unknown' ? '?' : s.toUpperCase()}</span>;
}

export function FindingList({ items }: { items: Finding[] }) {
  return (
    <div className="findings-list">
      {items.map((f, i) => (
        <div key={i} className="finding" data-sev={(f.severity || 'info').toLowerCase()}>
          <span className="finding-sev">{(f.severity || 'info').toUpperCase()}</span>
          <span className="finding-msg">{f.message || ''}</span>
        </div>
      ))}
    </div>
  );
}

export function KvTable({ obj }: { obj: Record<string, unknown> }) {
  return (
    <table className="detail-table">
      <tbody>
        {Object.entries(obj).map(([k, v]) => (
          <tr key={k}>
            <td>{k}</td>
            <td>{v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const SKIP = new Set(['tool', 'run_at', 'status', 'summary', 'findings',
  'recommendations', 'log', 'hosts', 'name', 'label']);

// Full report body. Always shows what the run produced — never a bare "all clear":
// an OK report still shows its summary, findings, the markdown log (new collectors),
// or a structured dump of the data (legacy collectors without a log).
export function ReportBody({ data }: { data: ReportDoc }) {
  const findings = data.findings ?? [];
  const recs = data.recommendations ?? [];
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) if (!SKIP.has(k)) rest[k] = v;

  let structured: ReactNode = null;
  if (!data.log) {
    structured = (
      <>
        {(data.hosts ?? []).map((h, i) => (
          <section key={i}>
            <h3 className="detail-section-title">{h.host || 'host'}</h3>
            {h.summary && <p className="report-summary">{h.summary}</p>}
            {h.metrics && <KvTable obj={h.metrics} />}
          </section>
        ))}
        {Object.keys(rest).length > 0 && (
          <>
            <h3 className="detail-section-title">Details</h3>
            <KvTable obj={rest} />
          </>
        )}
      </>
    );
  }

  return (
    <div className="report-body">
      <div className="report-status-line">
        <StatusBadge status={data.status} />
        {data.run_at && <span className="report-runat">ran {localeDateTime(data.run_at)}</span>}
      </div>
      {data.summary && <p className="report-summary">{data.summary}</p>}
      {findings.length > 0 && (<><h3 className="detail-section-title">Findings</h3><FindingList items={findings} /></>)}
      {recs.length > 0 && (<><h3 className="detail-section-title">Recommendations / watch list</h3><FindingList items={recs} /></>)}
      {data.log ? <Markdown source={data.log} /> : structured}
    </div>
  );
}

// Human, diagnosable message for a failed dispatcher call (v1's dispatcherError).
export function dispatcherErrorMessage(status: number, detail: string): string {
  switch (status) {
    case 503: return `Dispatcher not configured — set DISPATCHER_URL in the webapp's .env on the Pi. ${detail}`;
    case 502: return `Backend reached, but could not connect to the dispatcher on opti (network/firewall, or wrong DISPATCHER_URL). ${detail}`;
    case 401: return `Dispatcher rejected the request (401) — HL_DISPATCH_TOKEN mismatch between the webapp and opti. ${detail}`;
    default: return `Request failed (HTTP ${status}). ${detail}`;
  }
}
