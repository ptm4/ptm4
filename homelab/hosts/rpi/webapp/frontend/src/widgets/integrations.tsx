// Integration widgets — the "more" from the redesign plan, all built on data the
// homelab already produces: bot fleet state, the notification inbox, active
// streams, and the Leetify rating trend.
import { useQueries, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { get } from '../lib/api';
import { relTime } from '../lib/format';
import { BOTS, type BotStatus } from '../lib/bots';
import { useNotifications } from '../components/Notifications';
import { WidgetFrame, WidgetError, WidgetLoading, Sparkline, Pill } from './kit';

// ── bots feed ───────────────────────────────────────────────────────────────
// Answers "did the 7AM weather post actually fire?" at a glance.
export function BotsWidget() {
  const results = useQueries({
    queries: BOTS.map((b) => ({
      queryKey: ['bot-status', b.id],
      queryFn: () => get<BotStatus>(`/api/${b.id}/status`, 10_000),
      refetchInterval: 5 * 60_000,
      retry: 0,
    })),
  });

  return (
    <WidgetFrame title="Discord bots" meta={<Link to="/bots">manage →</Link>} scroll>
      <div className="kv-rows">
        {BOTS.map((b, i) => {
          const r = results[i];
          const failed = /fail/i.test(r.data?.last_status ?? '');
          return (
            <div className="kv-row bot-row" key={b.id}>
              <span><span aria-hidden>{b.icon}</span> {b.label}</span>
              <span>
                {r.isError ? <span className="t-crit">unreachable</span>
                  : r.isLoading ? '…'
                  : r.data?.enabled === false ? <span className="t-dim">paused</span>
                  : (
                    <>
                      <span className={failed ? 't-crit' : ''}>{r.data?.last_status ?? 'no posts yet'}</span>
                      <span className="t-dim"> · next {relTime(r.data?.next_post_at)}</span>
                    </>
                  )}
              </span>
            </div>
          );
        })}
      </div>
    </WidgetFrame>
  );
}

// ── notifications ───────────────────────────────────────────────────────────
export function NotificationsWidget({ options }: { options?: Record<string, unknown> }) {
  const limit = (options?.limit as number) ?? 6;
  const q = useNotifications(false);

  if (q.isError) return <WidgetFrame title="Open findings"><WidgetError message="reports unavailable" /></WidgetFrame>;

  const items = (q.data?.items ?? []).slice(0, limit);
  return (
    <WidgetFrame
      title="Open findings"
      meta={q.data ? <Pill tone={q.data.unacked ? 'warn' : 'ok'}>{q.data.unacked} open</Pill> : undefined}
      scroll
    >
      {q.isLoading && <WidgetLoading />}
      {q.data?.unacked === 0 && <div className="t-dim">Everything acknowledged.</div>}
      <ul className="feed">
        {items.map((n) => (
          <li key={n.id} data-sev={n.severity}>
            <span className="feed-dot" />
            <span className="feed-msg">{n.message}</span>
            <span className="feed-meta">{n.host ? `${n.host} · ` : ''}{n.source} · {relTime(n.ts)}</span>
          </li>
        ))}
      </ul>
    </WidgetFrame>
  );
}

// ── streams ─────────────────────────────────────────────────────────────────
interface StreamSlot { slot?: number; channel?: string; platform?: string; running?: boolean; title?: string }
interface StreamStatus { slots?: StreamSlot[] }

export function StreamsWidget() {
  const q = useQuery({
    queryKey: ['streams-status'],
    queryFn: () => get<StreamStatus>('/api/streams/status', 12_000),
    refetchInterval: 60_000,
    retry: 0,
  });

  if (q.isError) return <WidgetFrame title="Streams"><WidgetError message="stream station unreachable" /></WidgetFrame>;

  const active = (q.data?.slots ?? []).filter((s) => s.running);
  return (
    <WidgetFrame title="Streams" meta={<a href="/streams/">open →</a>}>
      {q.isLoading && <WidgetLoading />}
      {!q.isLoading && active.length === 0 && <div className="t-dim">No active streams.</div>}
      <div className="kv-rows">
        {active.map((s, i) => (
          <div className="kv-row" key={i}>
            <span className="mono">slot {s.slot ?? i + 1}</span>
            <span>{s.channel ?? s.title ?? '—'}{s.platform ? ` · ${s.platform}` : ''}</span>
          </div>
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── leetify trend ───────────────────────────────────────────────────────────
interface LeetifyHistory { history: { date: string }[] }

export function LeetifyTrendWidget() {
  const latest = useQuery({
    queryKey: ['runner-report', 'leetify-latest'],
    queryFn: () => get<{ dimensions?: Record<string, number>; summary?: string; maps?: unknown[] }>(
      '/api/runners/leetify-latest', 15_000),
    retry: 0,
  });
  const history = useQuery({
    queryKey: ['history', 'leetify-latest'],
    queryFn: () => get<LeetifyHistory>('/api/runners/leetify-latest/history', 15_000),
    retry: 0,
  });

  // Rating over time needs the dated snapshots; fetch the last 14 and read their
  // aim dimension (the one that moves and the one the coach keys on).
  const dates = (history.data?.history ?? []).slice(0, 14).map((h) => h.date).reverse();
  const snaps = useQueries({
    queries: dates.map((d) => ({
      queryKey: ['leetify-snap', d],
      queryFn: () => get<{ dimensions?: Record<string, number> }>(`/api/runners/leetify-latest/report/${d}`, 15_000),
      staleTime: 6 * 3600_000,
      retry: 0,
    })),
  });

  if (latest.isError) return <WidgetFrame title="CS2"><WidgetError message="no Leetify report yet" /></WidgetFrame>;

  const series = snaps.map((s) => {
    const dims = s.data?.dimensions ?? {};
    const key = Object.keys(dims).find((k) => /aim/i.test(k)) ?? Object.keys(dims)[0];
    return key ? dims[key] ?? null : null;
  });
  const dims = latest.data?.dimensions ?? {};

  return (
    <WidgetFrame title="CS2 / Leetify" meta={<Link to="/leetify">details →</Link>}>
      {latest.isLoading && <WidgetLoading />}
      <div className="dim-strip">
        {Object.entries(dims).slice(0, 3).map(([k, v]) => (
          <div key={k} className="dim" data-s={v >= 60 ? 'strong' : v < 52 ? 'focus' : 'ok'}>
            <span className="dim-name">{k}</span>
            <span className="dim-val">{Math.round(v)}</span>
          </div>
        ))}
      </div>
      {series.filter((v) => v != null).length > 1 && (
        <div className="spark-wrap" style={{ color: 'var(--brand)' }} title="trend over the last runs">
          <Sparkline values={series} label="Leetify trend" />
        </div>
      )}
      {latest.data?.summary && <div className="t-dim">{latest.data.summary}</div>}
    </WidgetFrame>
  );
}

// ── downloads (qBittorrent / SABnzbd summary via the *arr proxy on nn) ───────
// Read-only: the widget links out for anything actionable.
export function DownloadsWidget() {
  const q = useQuery({
    queryKey: ['linkcheck'],
    queryFn: () => get<{ origins: Record<string, { up: boolean }> }>('/api/linkcheck', 15_000),
    refetchInterval: 60_000,
  });
  const qbt = q.data?.origins['http://noblenumbat.lan:8081'];

  return (
    <WidgetFrame title="Downloads" meta={<a href="http://noblenumbat.lan:8081/" target="_blank" rel="noreferrer">qBittorrent →</a>}>
      <div className="kv-rows">
        <div className="kv-row">
          <span>qBittorrent</span>
          <span className={qbt?.up ? '' : 't-crit'}>{qbt == null ? '…' : qbt.up ? 'reachable' : 'down'}</span>
        </div>
      </div>
      <div className="t-dim">
        Behind gluetun&apos;s network namespace — if this is down, check the VPN widget first.
      </div>
    </WidgetFrame>
  );
}
