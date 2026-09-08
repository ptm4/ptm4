// Widget building blocks: the card frame every widget renders into, plus the
// small primitives (meter, sparkline, pill, stat) the v1 tiles used.
import { useState } from 'react';
import type { ReactNode } from 'react';
import { toneFor } from '../lib/format';

export function WidgetFrame({
  title, meta, children, scroll, href,
}: {
  title?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  scroll?: boolean;
  href?: string;
}) {
  const body = (
    <>
      {title && (
        <div className="w-head">
          <span className="w-title">{title}</span>
          {meta && <span className="w-meta">{meta}</span>}
        </div>
      )}
      <div className={`w-body${scroll ? ' scroll' : ''}`}>{children}</div>
    </>
  );
  return href
    ? <a className="w-card glass w-link" href={href}>{body}</a>
    : <div className="w-card glass">{body}</div>;
}

export function Meter({ pct, tone }: { pct: number | null | undefined; tone?: string }) {
  if (pct == null) return null;
  return (
    <div className="meter">
      <span data-tone={tone || toneFor(pct)} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

export function Pill({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className="pill" data-s={tone}>{children}</span>;
}

export function Vital({
  label, value, sub, pct,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  pct?: number | null;
}) {
  return (
    <div className="vital">
      <div className="vital-label">{label}</div>
      <div className="vital-value">{value}{sub && <small>{sub}</small>}</div>
      <Meter pct={pct} />
    </div>
  );
}

// Inline SVG sparkline — port of v1's hand-rolled sparkline(). Nulls break the
// line rather than being interpolated: a gap is the honest "we don't know".
// Pass `times` (epoch seconds, parallel to values) to make it interactive: a
// pointer over the chart snaps to the nearest sample and shows value + time.
export function Sparkline({
  values, times, width = 120, height = 26, label, format, showDay,
}: {
  values: (number | null)[];
  times?: (number | null)[];
  width?: number;
  height?: number;
  label?: string;
  format?: (v: number) => string;
  /** include the weekday in the hover time — for ranges spanning days */
  showDay?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const present = values.filter((v): v is number => v != null);
  if (present.length < 2) return null;
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const step = width / Math.max(1, values.length - 1);
  const yFor = (v: number) => height - ((v - min) / span) * (height - 2) - 1;

  // Snap to the nearest sample that actually exists (gaps stay gaps).
  const snap = (frac: number): number | null => {
    const i = Math.max(0, Math.min(values.length - 1, Math.round(frac * (values.length - 1))));
    for (let d = 0; d < values.length; d++) {
      if (values[i - d] != null) return i - d;
      if (values[i + d] != null) return i + d;
    }
    return null;
  };

  const segments: string[] = [];
  let current: string[] = [];
  values.forEach((v, i) => {
    if (v == null) {
      if (current.length > 1) segments.push(current.join(' '));
      current = [];
      return;
    }
    const x = (i * step).toFixed(1);
    const y = (height - ((v - min) / span) * (height - 2) - 1).toFixed(1);
    current.push(`${current.length ? 'L' : 'M'}${x},${y}`);
  });
  if (current.length > 1) segments.push(current.join(' '));

  // A soft fill under each run gives the line body on a glass card — a bare
  // 1.5px stroke reads as a stray scratch at this size.
  const gid = `sparkfill-${label?.replace(/\W+/g, '') ?? 'x'}-${Math.round(min)}-${Math.round(max)}`;

  const interactive = !!times;
  const hv = hover != null && values[hover] != null ? hover : null;
  const fmt = format ?? ((v: number) => `${Math.round(v * 10) / 10}`);
  const timeStr = (t: number | null | undefined) =>
    t ? new Date(t * 1000).toLocaleString([], {
      ...(showDay ? { weekday: 'short' } : {}), hour: '2-digit', minute: '2-digit',
    }) : '';

  return (
    <span
      className="spark-box"
      onPointerMove={interactive ? (e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        setHover(snap((e.clientX - rect.left) / rect.width));
      } : undefined}
      onPointerLeave={interactive ? () => setHover(null) : undefined}
    >
      <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        {segments.map((d, i) => {
          const first = d.slice(1).split(' ')[0].split(',')[0];
          const lastPoint = d.split(' ').at(-1)!.replace('L', '').split(',')[0];
          return (
            <g key={i}>
              <path d={`${d} L${lastPoint},${height} L${first},${height} Z`} fill={`url(#${gid})`} stroke="none" />
              <path d={d} fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            </g>
          );
        })}
        {hv != null && (
          <line x1={hv * step} y1="0" x2={hv * step} y2={height}
            stroke="currentColor" strokeOpacity="0.35" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {hv != null && (
        <>
          <span className="spark-dot" style={{
            left: `${(hv * step / width) * 100}%`,
            top: `${(yFor(values[hv]!) / height) * 100}%`,
          }} />
          <span className="spark-tip" style={{ left: `${Math.min(78, Math.max(6, (hv * step / width) * 100))}%` }}>
            {fmt(values[hv]!)}{times?.[hv] ? ` · ${timeStr(times[hv])}` : ''}
          </span>
        </>
      )}
    </span>
  );
}

export function WidgetError({ message }: { message: string }) {
  return <div className="w-error">{message}</div>;
}

export function WidgetLoading() {
  return (
    <div className="w-loading">
      <div className="sk sk-line w60" />
      <div className="sk sk-line w80" />
      <div className="sk sk-line w40" />
    </div>
  );
}
