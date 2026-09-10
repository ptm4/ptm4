// Data — how every fact in the homelab gets from the thing that observes it to the
// thing that reads it, with live freshness on each hop.
//
// The map is not derived from scanning the filesystem: a machine can see that a file
// exists but not what it is for or who reads it. It comes from the curated `datasets`
// registry in homelab/tools/homelab-db/ingest.py, joined with real ingest state. That
// same registry renders generated/92-data-flows.md and answers the hl_dataplane MCP
// tool, so this page, the docs, and what an agent sees can never disagree.
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { relTime } from '../lib/format';

interface Dataset {
  id: string;
  label: string;
  stage: 'producer' | 'store' | 'db' | 'consumer';
  producer: string;
  producer_host?: string | null;
  source: string;
  format?: string | null;
  cadence_hours?: number | null;
  consumers?: string | null;
  retention?: string | null;
  notes?: string | null;
  last_source_at?: string | null;
  last_ingested?: string | null;
  last_rows?: number | null;
  last_error?: string | null;
  age_hours?: number | null;
  stale?: boolean;
}

interface DataplaneResp {
  datasets?: Dataset[];
  database?: {
    history_from?: string;
    history_to?: string;
    runs?: number;
    rows?: Record<string, number>;
    schema_version?: number;
  };
}

const STAGES: { key: Dataset['stage']; title: string; blurb: string }[] = [
  { key: 'producer', title: 'Producers', blurb: 'observe the homelab' },
  { key: 'store', title: 'Stores', blurb: 'where facts land' },
  { key: 'db', title: 'Index', blurb: 'queryable, with history' },
  { key: 'consumer', title: 'Consumers', blurb: 'read it back' },
];

function Freshness({ d }: { d: Dataset }) {
  if (d.last_error) return <span className="badge badge-stale" title={d.last_error}>error</span>;
  if (!d.last_source_at) {
    return <span className="t-dim" title="Nothing ingested from this source yet">—</span>;
  }
  const label = relTime(d.last_source_at);
  if (d.stale) {
    return (
      <span className="badge badge-stale" title={`Expected every ${d.cadence_hours}h`}>
        {label}
      </span>
    );
  }
  return <span className="t-dim">{label}</span>;
}

export default function DataFlowPage() {
  const q = useQuery({
    queryKey: ['hldb-dataplane-page'],
    queryFn: () => get<DataplaneResp>('/api/hldb/dataplane', 20_000),
    refetchInterval: 5 * 60_000,
    retry: 0,
  });

  const datasets = q.data?.datasets ?? [];
  const db = q.data?.database;
  const stale = datasets.filter((d) => d.stale || d.last_error);
  const rows = db?.rows ?? {};
  const totalRows = Object.values(rows).reduce((a, b) => a + b, 0);

  return (
    <div className="dataflow-page">
      <div className="board-bar">
        <span className="board-name">Data</span>
        {db && (
          <span className="t-dim">
            {totalRows.toLocaleString()} rows indexed · history {db.history_from} → {db.history_to}
          </span>
        )}
        <span className="spacer" />
        {stale.length > 0
          ? <span className="t-warn">{stale.length} feed{stale.length === 1 ? '' : 's'} stale</span>
          : <span className="t-dim">all feeds fresh</span>}
      </div>

      {q.isError && (
        <div className="glass card">
          <div className="w-head"><span className="w-title">homelab-db unavailable</span></div>
          <p className="t-dim">
            The database lives on opti and is served at <code>:9100</code>. If opti is up,
            check <code>homelab-db.service</code>; if this dashboard has never reached it,
            check <code>HOMELAB_DB_URL</code> and <code>HL_DB_TOKEN</code> in the webapp env.
          </p>
        </div>
      )}

      {q.isLoading && <div className="t-dim">Loading the data plane…</div>}

      {!q.isLoading && !q.isError && (
        <>
          <div className="flow-stages">
            {STAGES.map((stage) => {
              const items = datasets.filter((d) => d.stage === stage.key);
              if (items.length === 0) return null;
              return (
                <section className="flow-stage" key={stage.key}>
                  <header>
                    <h3>{stage.title}</h3>
                    <span className="t-dim">{stage.blurb}</span>
                  </header>
                  {items.map((d) => (
                    <article
                      className={`glass card flow-card${d.stale || d.last_error ? ' is-stale' : ''}`}
                      key={d.id}
                    >
                      <div className="flow-card-head">
                        <span className="w-title">{d.label}</span>
                        <Freshness d={d} />
                      </div>
                      <div className="mono t-dim flow-source">{d.source}</div>
                      <div className="flow-meta t-dim">
                        {d.producer_host && <span>{d.producer_host}</span>}
                        <span>{d.cadence_hours ? `every ${d.cadence_hours}h` : 'on demand'}</span>
                        {d.last_rows != null && <span>{d.last_rows.toLocaleString()} rows</span>}
                      </div>
                      {d.notes && <p className="flow-notes t-dim">{d.notes}</p>}
                    </article>
                  ))}
                </section>
              );
            })}
          </div>

          <div className="glass card">
            <div className="w-head">
              <span className="w-title">What is indexed</span>
              <span className="t-dim">
                schema v{db?.schema_version} · {db?.runs?.toLocaleString()} collector runs
              </span>
            </div>
            <table className="detail-table">
              <thead>
                <tr><th>Table</th><th>Rows</th><th>What it holds</th></tr>
              </thead>
              <tbody>
                {Object.entries(rows).map(([table, count]) => (
                  <tr key={table}>
                    <td className="mono">{table}</td>
                    <td>{count.toLocaleString()}</td>
                    <td className="t-dim">{TABLE_BLURB[table] ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

const TABLE_BLURB: Record<string, string> = {
  agent_runs: 'one row per collector run, per day',
  findings: 'every warning and error the collectors raised',
  collector_metrics: 'numeric series — the long-range trends',
  docs: 'runbooks, rules and skills, chunked and full-text indexed',
  change_events: 'containers and mounts appearing, changing, vanishing',
  arch_nodes: 'the curated architecture graph',
  raw_documents: 'JSON that has no purpose-built table yet, still queryable',
  vitals_samples: 'durable per-minute host vitals',
};
