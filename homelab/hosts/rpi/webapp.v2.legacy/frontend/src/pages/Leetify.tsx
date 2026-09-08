// CS2 / Leetify — the leetify-stats runner's report, rendered as dimension chips,
// a per-map table, AI coaching notes, the HLTV VRS watchlist, and a collapsible
// round-by-round deep dive per parsed demo.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get, ApiError } from '../lib/api';
import { Markdown } from '../components/Markdown';
import { localeDateTime } from '../lib/format';

interface MapRow {
  map: string; matches: number; win_rate: number;
  avg_rating?: number; ct_rating?: number; t_rating?: number;
}
interface RoundRow {
  round?: number; won?: boolean | null; damage?: number; died?: boolean;
  killer?: string; planted?: boolean; defused?: boolean;
  kills?: unknown[];
}
interface DemoSummary {
  map: string; date: string; result: string; score?: string;
  kills?: number; deaths?: number; rating?: number; hs_pct?: number;
  hotspots?: { area: string; side: string; count: number; pct: number }[];
  rounds?: RoundRow[];
}
interface LeetifyReport {
  run_at?: string;
  summary?: string;
  dimensions?: Record<string, number>;
  maps?: MapRow[];
  demo_summaries?: DemoSummary[];
  coaching?: string;
  log?: string;
}

export default function LeetifyPage() {
  const q = useQuery({
    queryKey: ['leetify'],
    queryFn: () => get<LeetifyReport>('/api/runners/leetify-latest', 15_000),
    retry: 0,
  });

  if (q.isError) {
    const err = q.error as ApiError;
    // A 500 means the report exists but won't parse (corrupt/truncated) — distinct
    // from a 404 "no report yet". Show the real reason so it's fixable.
    return (
      <div className="glass card">
        {err.status === 500 ? (
          <>
            <p>Leetify report is corrupt and could not be read.</p>
            <p className="t-dim">{err.message}</p>
            <p className="t-dim">Re-run the agent on opti to regenerate it.</p>
          </>
        ) : (
          <>
            <p>No Leetify report yet.</p>
            <p className="t-dim">Set LEETIFY_API_KEY + STEAM64_ID on opti and run the agent.</p>
          </>
        )}
      </div>
    );
  }
  if (q.isLoading || !q.data) return <div className="spin" />;

  const d = q.data;
  const dims = Object.entries(d.dimensions ?? {});
  const demos = d.demo_summaries ?? [];
  const deepDives = demos.filter((ds) => (ds.rounds ?? []).length > 0);

  return (
    <div className="leetify-page">
      <section className="glass card">
        <div className="w-head">
          <span className="w-title">Overview</span>
          <span className="w-meta">{d.run_at ? localeDateTime(d.run_at) : ''}</span>
        </div>
        {d.summary && <p className="report-summary">{d.summary}</p>}
        {dims.length > 0 && (
          <div className="dim-strip">
            {dims.map(([k, v]) => (
              <div key={k} className="dim" data-s={v >= 60 ? 'strong' : v < 52 ? 'focus' : 'ok'}>
                <span className="dim-name">{k}</span>
                <span className="dim-val">{Math.round(v)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {(d.maps?.length ?? 0) > 0 && (
        <section className="glass card">
          <div className="w-head"><span className="w-title">Maps</span></div>
          <table className="detail-table">
            <thead>
              <tr><th>Map</th><th>Matches</th><th>Win rate</th><th>CT</th><th>T</th><th>Verdict</th></tr>
            </thead>
            <tbody>
              {d.maps!.map((m) => {
                const verdict = m.matches < 2 ? 'low sample'
                  : (m.win_rate >= 55 && (m.avg_rating ?? 0) >= 0) ? 'strong'
                  : (m.win_rate <= 40 || (m.avg_rating ?? 0) < -0.03) ? 'avoid / practice'
                  : 'even';
                return (
                  <tr key={m.map}>
                    <td>{m.map}</td>
                    <td>{m.matches}</td>
                    <td>{m.win_rate}%</td>
                    <td>{(m.ct_rating ?? 0).toFixed(3)}</td>
                    <td>{(m.t_rating ?? 0).toFixed(3)}</td>
                    <td>{verdict}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {d.coaching && (
        <section className="glass card">
          <div className="w-head"><span className="w-title">Coaching</span></div>
          <Markdown source={d.coaching} />
        </section>
      )}

      {demos.length > 0 && (
        <section className="glass card">
          <div className="w-head"><span className="w-title">Recent demos</span></div>
          <div className="demo-grid">
            {demos.map((ds, i) => (
              <div className="demo-card glass" key={i}>
                <div className="demo-head">
                  <span className="demo-map">{ds.map}</span>
                  <span className="t-dim">{ds.date}</span>
                  <span className="demo-result" data-s={ds.result}>{ds.result}{ds.score ? ` ${ds.score}` : ''}</span>
                </div>
                <div className="t-dim">
                  {ds.kills != null && ds.deaths != null ? `${ds.kills}/${ds.deaths} K/D` : ''}
                  {ds.rating != null ? ` · ${ds.rating > 0 ? '+' : ''}${ds.rating.toFixed(3)} rating` : ''}
                  {ds.hs_pct != null ? ` · ${ds.hs_pct}% HS` : ''}
                </div>
                {(ds.hotspots?.length ?? 0) > 0 && (
                  <table className="detail-table">
                    <thead><tr><th>Died at</th><th>Side</th><th>×</th><th>%</th></tr></thead>
                    <tbody>
                      {ds.hotspots!.map((h, j) => (
                        <tr key={j}><td>{h.area}</td><td>{h.side}</td><td>{h.count}</td><td>{h.pct}%</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {deepDives.length > 0 && (
        <section className="glass card">
          <div className="w-head"><span className="w-title">Match deep-dive — round by round</span></div>
          {deepDives.map((ds, i) => <DeepDive key={i} demo={ds} />)}
        </section>
      )}

      {d.log && (
        <section className="glass card">
          <div className="w-head"><span className="w-title">Full report</span></div>
          <Markdown source={d.log} />
        </section>
      )}
    </div>
  );
}

function DeepDive({ demo }: { demo: DemoSummary }) {
  const [open, setOpen] = useState(false);
  const rounds = demo.rounds ?? [];
  const won = rounds.filter((r) => r.won === true).length;
  const lost = rounds.filter((r) => r.won === false).length;

  return (
    <details className="deep-dive" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span className="demo-map">{demo.map}</span>
        <span className="t-dim"> {demo.date} · {won}–{lost}</span>
        <span className="demo-result" data-s={demo.result}>{demo.result}</span>
      </summary>
      <table className="detail-table">
        <thead><tr><th>#</th><th>Result</th><th>Kills</th><th>Damage</th><th>Objective</th><th>Fate</th></tr></thead>
        <tbody>
          {rounds.map((r, i) => (
            <tr key={i} data-s={r.won === true ? 'won' : r.won === false ? 'lost' : undefined}>
              <td>{r.round ?? i + 1}</td>
              <td>{r.won === true ? 'won' : r.won === false ? 'lost' : '—'}</td>
              <td>{(r.kills ?? []).length || '—'}</td>
              <td>{r.damage ?? '—'}</td>
              <td>{r.planted ? '💣 plant' : r.defused ? '🛡 defuse' : ''}</td>
              <td>{r.died ? (r.killer ? `died → ${r.killer}` : 'died') : 'survived'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
