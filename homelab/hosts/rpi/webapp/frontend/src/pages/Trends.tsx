// Trends — the 6h vitals ring buffer finally gets a real viewer. v1 only ever
// showed this data as 26px sparklines; the samples were always there.
// Daily-resolution pool/disk history comes from /api/trends (dated doctor reports).
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { useVitalsRange, type VitalsRange } from '../lib/queries';
import { fmtBytesPerSec } from '../lib/format';
import type { VitalsSample } from '../lib/api-types';

const HOSTS = ['rpi', 'opti', 'noblenumbat'];
const RANGES = ['1h', '3h', '9h', '24h', '48h'] as const;

type MetricKey = 'cpu_pct' | 'mem_pct' | 'temp_c' | 'rx_bps' | 'tx_bps' | 'load1';

const METRICS: { key: MetricKey; label: string; unit: string; color: string }[] = [
  { key: 'cpu_pct', label: 'CPU', unit: '%', color: 'var(--c-network)' },
  { key: 'mem_pct', label: 'Memory', unit: '%', color: 'var(--brand)' },
  { key: 'temp_c', label: 'Temperature', unit: '°C', color: 'var(--c-media)' },
  { key: 'rx_bps', label: 'Network in', unit: '/s', color: 'var(--c-apps)' },
  { key: 'tx_bps', label: 'Network out', unit: '/s', color: 'var(--accent)' },
  { key: 'load1', label: 'Load (1m)', unit: '', color: 'var(--brand)' },
];

interface TrendsResp {
  days: number;
  pool: { date: string; used_pct: number; pool_name: string | null }[];
  disks: Record<string, { date: string; used_pct: number }[]>;
}

const RANGE_KEY = 'trends-range';
const HOST_KEY = 'trends-host';

export default function TrendsPage() {
  const [host, setHostState] = useState(() => {
    try { const v = localStorage.getItem(HOST_KEY); return v && HOSTS.includes(v) ? v : 'rpi'; }
    catch { return 'rpi'; }
  });
  const [range, setRangeState] = useState<VitalsRange>(() => {
    try {
      const v = localStorage.getItem(RANGE_KEY) as VitalsRange | null;
      return v && (RANGES as readonly string[]).includes(v) ? v : '1h';
    } catch { return '1h'; }
  });
  const setHost = (h: string) => {
    setHostState(h);
    try { localStorage.setItem(HOST_KEY, h); } catch { /* private mode */ }
  };
  const setRange = (r: VitalsRange) => {
    setRangeState(r);
    try { localStorage.setItem(RANGE_KEY, r); } catch { /* private mode */ }
  };

  const series = useVitalsRange(host, range);
  const daily = useQuery({
    queryKey: ['trends', 30],
    queryFn: () => get<TrendsResp>('/api/trends?days=30', 15_000),
    refetchInterval: 10 * 60_000,
  });

  const samples = series.data?.samples ?? [];

  return (
    <div className="trends-page">
      <div className="board-bar">
        <div className="seg">
          {HOSTS.map((h) => (
            <button key={h} className={`seg-btn${h === host ? ' active' : ''}`} onClick={() => setHost(h)}>{h}</button>
          ))}
        </div>
        <span className="spacer" />
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r} className={`seg-btn${r === range ? ' active' : ''}`}
              onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
      </div>

      {series.data?.error && <div className="glass card t-crit">{series.data.error}</div>}
      {samples.length < 2 && !series.isLoading && (
        <div className="glass card t-dim">
          Not enough samples yet — the poller keeps 6h at 30s intervals and fills in
          as it runs.
        </div>
      )}

      <div className="chart-grid">
        {METRICS.map((m) => (
          <section className="glass card" key={m.key}>
            <div className="w-head">
              <span className="w-title">{m.label}</span>
              <span className="w-meta">{latestLabel(samples, m.key, m.unit)}</span>
            </div>
            <Chart samples={samples} metric={m.key} color={m.color} unit={m.unit}
              longRange={range === '24h' || range === '48h'} />
          </section>
        ))}
      </div>

      <section className="glass card">
        <div className="w-head">
          <span className="w-title">Storage over time</span>
          <span className="w-meta">{daily.data?.days ?? 0} days of doctor snapshots</span>
        </div>
        {(daily.data?.pool.length ?? 0) > 1 ? (
          <DailyChart
            series={daily.data!.pool.map((p) => ({ x: p.date, y: p.used_pct }))}
            color="var(--c-storage)"
            unit="%"
            label={`pool ${daily.data!.pool.at(-1)?.pool_name ?? ''}`}
          />
        ) : <p className="t-dim">No pool history yet.</p>}
        <div className="kv-rows">
          {Object.entries(daily.data?.disks ?? {}).map(([h, rows]) => (
            <div className="kv-row" key={h}>
              <span>{h} disk</span>
              <span>{rows.at(-1)?.used_pct ?? '—'}%</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function latestLabel(samples: VitalsSample[], key: MetricKey, unit: string): string {
  for (let i = samples.length - 1; i >= 0; i--) {
    const v = samples[i][key];
    if (v != null) return key.endsWith('_bps') ? fmtBytesPerSec(v) : `${Math.round(v * 10) / 10}${unit}`;
  }
  return '—';
}

// Line chart with a filled area and an interactive crosshair: hover snaps to the
// nearest real sample and shows value + wall-clock time. Nulls break the path —
// a gap is "we don't know", never an interpolated line across a poll failure.
function Chart({
  samples, metric, color, unit, longRange,
}: {
  samples: VitalsSample[]; metric: MetricKey; color: string; unit: string; longRange?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600, H = 140, PAD = 4;
  const values = samples.map((s) => s[metric]);
  const present = values.filter((v): v is number => v != null);
  if (present.length < 2) return <div className="t-dim">no data</div>;

  const min = Math.min(...present, metric.endsWith('_pct') ? 0 : Math.min(...present));
  const max = Math.max(...present, metric.endsWith('_pct') ? 100 : Math.max(...present));
  const span = max - min || 1;
  const step = W / Math.max(1, values.length - 1);
  const yFor = (v: number) => H - PAD - ((v - min) / span) * (H - PAD * 2);

  const segs: string[] = [];
  let cur: string[] = [];
  values.forEach((v, i) => {
    if (v == null) { if (cur.length > 1) segs.push(cur.join(' ')); cur = []; return; }
    cur.push(`${cur.length ? 'L' : 'M'}${(i * step).toFixed(1)},${yFor(v).toFixed(1)}`);
  });
  if (cur.length > 1) segs.push(cur.join(' '));

  const fmt = (v: number) => metric.endsWith('_bps') ? fmtBytesPerSec(v) : `${Math.round(v * 10) / 10}${unit}`;

  const snap = (frac: number): number | null => {
    const i = Math.max(0, Math.min(values.length - 1, Math.round(frac * (values.length - 1))));
    for (let d = 0; d < values.length; d++) {
      if (values[i - d] != null) return i - d;
      if (values[i + d] != null) return i + d;
    }
    return null;
  };
  const hv = hover != null && values[hover] != null ? hover : null;
  const hvTime = hv != null
    ? new Date(samples[hv].t * 1000).toLocaleString([], {
        ...(longRange ? { weekday: 'short' } : {}), hour: '2-digit', minute: '2-digit',
      })
    : '';

  return (
    <div className="chart"
      onPointerMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        setHover(snap((e.clientX - rect.left) / rect.width));
      }}
      onPointerLeave={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={metric}>
        <line x1="0" y1={yFor(max)} x2={W} y2={yFor(max)} className="grid" />
        <line x1="0" y1={yFor(min + span / 2)} x2={W} y2={yFor(min + span / 2)} className="grid" />
        <line x1="0" y1={yFor(min)} x2={W} y2={yFor(min)} className="grid" />
        {segs.map((d, i) => (
          <path key={i} d={d} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        ))}
        {hv != null && (
          <line x1={hv * step} y1="0" x2={hv * step} y2={H}
            stroke={color} strokeOpacity="0.5" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {hv != null && (
        <>
          <span className="spark-dot" style={{
            left: `${(hv * step / W) * 100}%`,
            top: `${(yFor(values[hv]!) / H) * 100}%`,
            background: color,
          }} />
          <span className="spark-tip chart-tip" style={{ left: `${Math.min(80, Math.max(4, (hv * step / W) * 100))}%` }}>
            {fmt(values[hv]!)} · {hvTime}
          </span>
        </>
      )}
      <div className="chart-axis"><span>{fmt(max)}</span><span>{fmt(min)}</span></div>
    </div>
  );
}

function DailyChart({
  series, color, unit, label,
}: {
  series: { x: string; y: number }[]; color: string; unit: string; label: string;
}) {
  const W = 600, H = 120, PAD = 4;
  const ys = series.map((p) => p.y);
  const min = Math.min(...ys), max = Math.max(...ys);
  const span = max - min || 1;
  const step = W / Math.max(1, series.length - 1);
  const d = series.map((p, i) =>
    `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${(H - PAD - ((p.y - min) / span) * (H - PAD * 2)).toFixed(1)}`).join(' ');

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
        <path d={d} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="chart-axis">
        <span>{max.toFixed(1)}{unit}</span>
        <span>{min.toFixed(1)}{unit}</span>
      </div>
      <div className="t-dim">{series[0].x} → {series.at(-1)!.x} · {label}</div>
    </div>
  );
}
