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

// ── CS2 matches ─────────────────────────────────────────────────────────────
// Today's HLTV slate, same notable-match filter the Discord digest uses: live
// scores, what's coming with a stream link, and results with per-map scores.
interface Cs2Match {
  id?: string; url?: string; event?: string; stars?: number; bo?: string;
  team1?: string; team2?: string; start_unix?: number;
  status?: 'upcoming' | 'live' | 'finished';
  score1?: number | null; score2?: number | null;
  maps?: { name?: string; s1?: number; s2?: number }[];
  stream?: { name?: string; url?: string } | null;
}
interface Cs2Day {
  date?: string; fetched_at?: number; stale?: boolean;
  vrs_as_of?: string; matches?: Cs2Match[];
}

function clockOf(unix?: number) {
  if (!unix) return '—';
  return new Date(unix * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function Cs2Row({ m }: { m: Cs2Match }) {
  const name = <>{m.team1 ?? 'TBD'} <span className="t-dim">vs</span> {m.team2 ?? 'TBD'}</>;
  if (m.status === 'finished') {
    // Winner first, so the result reads without decoding which side is which.
    const flip = (m.score2 ?? 0) > (m.score1 ?? 0);
    const [w, l] = flip ? [m.team2, m.team1] : [m.team1, m.team2];
    const [ws, ls] = flip ? [m.score2, m.score1] : [m.score1, m.score2];
    const maps = (m.maps ?? [])
      .map((mp) => `${mp.name} ${flip ? mp.s2 : mp.s1}–${flip ? mp.s1 : mp.s2}`)
      .join(' · ');
    return (
      <div className="kv-row">
        <span className="mono">✅</span>
        <span>
          <a href={m.url} target="_blank" rel="noreferrer"><strong>{w}</strong> {ws}–{ls} {l}</a>
          {maps && <span className="t-dim"> · {maps}</span>}
        </span>
      </div>
    );
  }
  const live = m.status === 'live';
  return (
    <div className="kv-row">
      <span className="mono">{live ? '🔴' : clockOf(m.start_unix)}</span>
      <span>
        <a href={m.url} target="_blank" rel="noreferrer">
          {live && m.score1 != null ? <>{m.team1} {m.score1}–{m.score2} {m.team2}</> : name}
        </a>
        {m.stream?.url && (
          <> · <a href={m.stream.url} target="_blank" rel="noreferrer">📺 {m.stream.name}</a></>
        )}
      </span>
    </div>
  );
}

export function Cs2MatchesWidget({ options }: { options?: Record<string, unknown> }) {
  const limit = Number(options?.limit ?? 10) || 10;
  const sections = String(options?.sections ?? 'all');
  const q = useQuery({
    queryKey: ['hltv-day'],
    queryFn: () => get<Cs2Day>('/api/hltv/day', 25_000),
    refetchInterval: 60_000,
    retry: 0,
  });

  if (q.isError) {
    return <WidgetFrame title="CS2 today"><WidgetError message="hltv bot unreachable" /></WidgetFrame>;
  }

  const all = q.data?.matches ?? [];
  const pick = (s: Cs2Match['status']) => all.filter((m) => m.status === s);
  const groups: [string, Cs2Match[]][] = [
    ['Live', sections === 'results' ? [] : pick('live')],
    ['Upcoming', sections === 'results' ? [] : pick('upcoming')],
    ['Results', sections === 'upcoming' ? [] : pick('finished')],
  ];
  const shown = groups.reduce((n, [, ms]) => n + ms.length, 0);

  return (
    <WidgetFrame
      title="CS2 today"
      meta={q.data?.fetched_at
        ? <span title={q.data.stale ? 'HLTV unreachable — showing the last good scrape' : undefined}>
            {q.data.stale ? '⚠ ' : ''}{relTime(new Date(q.data.fetched_at * 1000).toISOString())}
          </span>
        : undefined}
      scroll
    >
      {q.isLoading && <WidgetLoading />}
      {!q.isLoading && shown === 0 && <div className="t-dim">No notable matches today.</div>}
      {groups.map(([label, ms]) => ms.length > 0 && (
        <div key={label}>
          <div className="t-dim">{label}</div>
          <div className="kv-rows">
            {ms.slice(0, limit).map((m, i) => <Cs2Row key={m.id ?? i} m={m} />)}
          </div>
        </div>
      ))}
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

// ── price watch ─────────────────────────────────────────────────────────────
// The opti-rebuild part tracker: pricewatch on opti scrapes Newegg/eBay/Amazon four
// times a day; this shows current price vs target with a per-item trend sparkline.
// Buy windows (price at/below target) get the green pill — that is the whole point.
interface PriceItem {
  id: string;
  label?: string;
  category?: string;
  retailer: string;
  url?: string;
  price: number | null;
  in_stock?: number | null;
  target_price?: number | null;
  error?: string | null;
}
interface PriceReport {
  run_at?: string;
  summary?: string;
  items?: PriceItem[];
  history?: Record<string, { d: string; p: number }[]>;
  below_target?: string[];
}

const money = (v: number) => (v >= 1000 ? `$${Math.round(v).toLocaleString()}` : `$${v.toFixed(2)}`);

export function PriceWatchWidget({ options }: { options?: Record<string, unknown> }) {
  const category = typeof options?.category === 'string' ? options.category : '';
  const q = useQuery({
    queryKey: ['pricewatch'],
    queryFn: () => get<PriceReport>('/api/pricewatch', 12_000),
    refetchInterval: 15 * 60_000,
    retry: 0,
  });
  if (q.isLoading) return <WidgetFrame title="Price watch"><WidgetLoading /></WidgetFrame>;
  if (q.isError || !q.data) {
    return <WidgetFrame title="Price watch"><WidgetError message="pricewatch report unavailable" /></WidgetFrame>;
  }
  const report = q.data;
  const items = (report.items ?? []).filter((it) => !category || it.category === category);
  const history = report.history ?? {};

  return (
    <WidgetFrame title="Price watch" scroll meta={report.run_at ? relTime(report.run_at) : undefined}>
      <div className="kv-rows">
        {items.map((it) => {
          const series = (history[it.id] ?? []).map((pt) => pt.p);
          const below = it.price != null && it.target_price != null && it.price <= it.target_price;
          return (
            <div className="kv-row" key={it.id}>
              <span>
                {it.url
                  ? <a href={it.url} target="_blank" rel="noreferrer">{it.label ?? it.id}</a>
                  : (it.label ?? it.id)}
                <span className="t-dim"> · {it.retailer}</span>
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {series.length > 1 && <Sparkline values={series} width={64} height={18} />}
                {it.price == null
                  ? <Pill tone="warn">{it.error ? 'fetch failed' : 'no price'}</Pill>
                  : below
                    ? <Pill tone="ok">{money(it.price)} · buy</Pill>
                    : <span>
                        {money(it.price)}
                        {it.target_price != null
                          && <span className="t-dim"> / {money(it.target_price)}</span>}
                      </span>}
              </span>
            </div>
          );
        })}
        {items.length === 0 && <div className="t-dim">no tracked items{category ? ` in ${category}` : ''}</div>}
      </div>
    </WidgetFrame>
  );
}
