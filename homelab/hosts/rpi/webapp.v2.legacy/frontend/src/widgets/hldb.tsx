// Widgets backed by homelab.db on opti (routes/hldb.js -> :9100).
//
// These are the questions the file-backed read-models cannot answer, because the files
// they read keep no history: what changed and when, what a metric has done over months,
// and whether the data pipeline itself is still feeding.
//
// opti is a single point of failure and this dashboard runs on rpi, so every widget here
// renders an honest "unavailable" state rather than an error boundary when the upstream
// is down — retry: 0 for the same reason the bot proxies use it.
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { relTime } from '../lib/format';
import { Pill, Sparkline, WidgetError, WidgetFrame, WidgetLoading } from './kit';

// ── shared types ────────────────────────────────────────────────────────────
interface ChangeEvent {
  at: string;
  host: string;
  kind: string;
  key: string;
  change: 'added' | 'removed' | 'changed';
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}
interface ChangesResp { events?: ChangeEvent[]; event_count?: number; days?: number }

interface MetricPoint { at: string; value: number | null }
interface MetricsResp {
  metric?: string;
  days?: number;
  series?: { host: string; points: MetricPoint[] }[];
}

interface Dataset {
  id: string; label: string; stage: string; producer_host?: string | null;
  source: string; cadence_hours?: number | null; consumers?: string | null;
  notes?: string | null; last_source_at?: string | null; last_error?: string | null;
  age_hours?: number | null; stale?: boolean;
}
interface DataplaneResp {
  datasets?: Dataset[];
  database?: {
    history_from?: string; history_to?: string; runs?: number;
    rows?: Record<string, number>; schema_version?: number;
  };
}

const UNAVAILABLE = 'homelab-db unavailable (opti down or not configured)';

// ── what changed ────────────────────────────────────────────────────────────
const CHANGE_TONE: Record<string, string> = {
  added: 'ok', removed: 'crit', changed: 'warn',
};

export function ChangesWidget({ options }: { options?: Record<string, unknown> }) {
  const days = Number(options?.days ?? 7);
  const host = (options?.host as string) || '';
  const q = useQuery({
    queryKey: ['hldb-changes', days, host],
    queryFn: () => get<ChangesResp>(
      `/api/hldb/changes?days=${days}${host ? `&host=${host}` : ''}`, 20_000),
    refetchInterval: 10 * 60_000,
    retry: 0,
  });

  const title = `Changes · ${days}d`;
  if (q.isError) return <WidgetFrame title={title}><WidgetError message={UNAVAILABLE} /></WidgetFrame>;

  const events = q.data?.events ?? [];
  return (
    <WidgetFrame title={title} meta={events.length ? `${events.length}` : undefined} scroll>
      {q.isLoading && <WidgetLoading />}
      {!q.isLoading && events.length === 0 && (
        <div className="t-dim">Nothing changed{host ? ` on ${host}` : ''} in the last {days} days.</div>
      )}
      <div className="kv-rows">
        {events.map((e, i) => (
          <div className="kv-row" key={`${e.at}-${e.key}-${i}`}>
            <span className="mono">{e.host}</span>
            <span>
              <Pill tone={CHANGE_TONE[e.change]}>{e.change}</Pill>{' '}
              {e.kind === 'container' ? e.key : `${e.kind} ${e.key}`}
              {e.change === 'changed' && e.after?.state ? (
                <span className="t-dim"> → {String(e.after.state)}</span>
              ) : null}
            </span>
            <span className="t-dim">{relTime(e.at)}</span>
          </div>
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── long-range trends ───────────────────────────────────────────────────────
// The board's host-vitals sparkline tops out at 48h (in-memory rings on rpi). This
// reads collector_metrics, which goes back to June 2026 at 30-minute resolution.
const METRIC_LABEL: Record<string, string> = {
  disk_used_pct: 'Root disk used',
  pool_used_pct: 'ZFS pool used',
  mem_used_gib: 'Memory used',
  pending_count: 'Pending updates',
  gateway_avg_ms: 'Gateway latency',
  internet_avg_ms: 'Internet latency',
  containers_count: 'Containers running',
};

const UNIT: Record<string, string> = {
  disk_used_pct: '%', pool_used_pct: '%', mem_used_gib: ' GiB',
  gateway_avg_ms: ' ms', internet_avg_ms: ' ms',
};

export function LongTrendsWidget({ options }: { options?: Record<string, unknown> }) {
  const metric = (options?.metric as string) || 'pool_used_pct';
  const days = Number(options?.days ?? 90);
  const host = (options?.host as string) || '';

  const q = useQuery({
    queryKey: ['hldb-metrics', metric, days, host],
    queryFn: () => get<MetricsResp>(
      `/api/hldb/metrics?metric=${metric}&days=${days}${host ? `&host=${host}` : ''}`, 20_000),
    refetchInterval: 30 * 60_000,
    retry: 0,
  });

  const label = METRIC_LABEL[metric] || metric;
  const title = `${label} · ${days}d`;
  if (q.isError) return <WidgetFrame title={title}><WidgetError message={UNAVAILABLE} /></WidgetFrame>;

  const series = (q.data?.series ?? []).filter((s) => s.points.length > 1);
  const unit = UNIT[metric] ?? '';
  return (
    <WidgetFrame title={title} scroll>
      {q.isLoading && <WidgetLoading />}
      {!q.isLoading && series.length === 0 && (
        <div className="t-dim">No history for {metric} yet.</div>
      )}
      {series.map((s) => {
        const values = s.points.map((p) => p.value);
        const times = s.points.map((p) => Math.floor(Date.parse(p.at) / 1000));
        const last = [...values].reverse().find((v) => v != null);
        const first = values.find((v) => v != null);
        const delta = last != null && first != null ? last - first : null;
        return (
          <div className="kv-row" key={s.host}>
            <span className="mono">{s.host}</span>
            <Sparkline
              values={values}
              times={times}
              showDay
              label={label}
              format={(v) => `${v.toFixed(1)}${unit}`}
            />
            <span>
              {last != null ? `${last.toFixed(1)}${unit}` : '—'}
              {delta != null && Math.abs(delta) >= 0.1 && (
                <small className="t-dim">
                  {' '}{delta > 0 ? '+' : ''}{delta.toFixed(1)}
                </small>
              )}
            </span>
          </div>
        );
      })}
    </WidgetFrame>
  );
}

// ── pipeline health ─────────────────────────────────────────────────────────
// Watches the thing that watches everything else: a feed that quietly stops looks
// exactly like a quiet homelab, which is the failure this makes loud.
export function DbHealthWidget() {
  const q = useQuery({
    queryKey: ['hldb-dataplane'],
    queryFn: () => get<DataplaneResp>('/api/hldb/dataplane', 20_000),
    refetchInterval: 5 * 60_000,
    retry: 0,
  });

  if (q.isError) {
    return <WidgetFrame title="Homelab DB"><WidgetError message={UNAVAILABLE} /></WidgetFrame>;
  }

  const datasets = q.data?.datasets ?? [];
  const db = q.data?.database;
  const stale = datasets.filter((d) => d.stale || d.last_error);
  const feeds = datasets.filter((d) => d.cadence_hours);
  const rows = db?.rows ?? {};
  const totalRows = Object.values(rows).reduce((a, b) => a + b, 0);

  return (
    <WidgetFrame
      title="Homelab DB"
      meta={<a href="/data">data flows →</a>}
      scroll
    >
      {q.isLoading && <WidgetLoading />}
      {!q.isLoading && (
        <>
          <div className="kv-rows">
            <div className="kv-row">
              <span>Feeds</span>
              <span>
                {stale.length === 0
                  ? <Pill tone="ok">{feeds.length} fresh</Pill>
                  : <Pill tone="warn">{stale.length} of {feeds.length} stale</Pill>}
              </span>
            </div>
            <div className="kv-row">
              <span>Indexed</span>
              <span>{totalRows.toLocaleString()} rows</span>
            </div>
            <div className="kv-row">
              <span>History</span>
              <span className="t-dim">{db?.history_from ?? '—'} → {db?.history_to ?? '—'}</span>
            </div>
          </div>
          {stale.length > 0 && (
            <div className="kv-rows">
              {stale.map((d) => (
                <div className="kv-row" key={d.id}>
                  <span className="mono">{d.id}</span>
                  <span className="t-dim">
                    {d.last_error
                      ? d.last_error.slice(0, 60)
                      : `${relTime(d.last_source_at)} (expects ${d.cadence_hours}h)`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </WidgetFrame>
  );
}
