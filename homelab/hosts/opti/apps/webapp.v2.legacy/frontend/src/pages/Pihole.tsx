// Pi-hole as a full page: live stats, pause/resume with a duration picker, the
// top-blocked table with one-click whitelisting, and a jump to the real admin.
// Everything runs through the backend's session-disciplined proxy — the browser
// never touches FTL directly, and /allow is allow-only by construction.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pause, Play, ExternalLink, ShieldCheck } from 'lucide-react';
import { get, post } from '../lib/api';
import { usePihole } from '../lib/queries';
import { toast } from '../lib/toast';

const PAUSES = [
  { label: '1 min', s: 60 },
  { label: '5 min', s: 300 },
  { label: '30 min', s: 1800 },
  { label: '1 hour', s: 3600 },
];

export default function PiholePage() {
  const summary = usePihole();
  const qc = useQueryClient();
  const [count, setCount] = useState(15);

  const top = useQuery({
    queryKey: ['pihole-top', count],
    queryFn: () => get<{ domains: { domain: string; count: number }[] }>(`/api/pihole/top?count=${count}`, 15_000),
    refetchInterval: 60_000,
  });

  const blocking = useMutation({
    mutationFn: ({ enabled, seconds }: { enabled: boolean; seconds?: number }) =>
      post('/api/pihole/blocking', { enabled, seconds }, 15_000),
    onSuccess: (_d, v) => {
      toast(v.enabled ? 'Blocking resumed' : `Blocking paused for ${Math.round((v.seconds ?? 300) / 60)} min`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    },
    onError: (e) => toast(`Pi-hole: ${(e as Error).message}`, 'crit', { sticky: true }),
  });

  const allow = useMutation({
    mutationFn: (domain: string) => post('/api/pihole/allow', { domain }, 15_000),
    onSuccess: (_d, domain) => {
      toast(`${domain} whitelisted`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole-top'] });
    },
    onError: (e) => toast(`Whitelist failed: ${(e as Error).message}`, 'crit'),
  });

  const d = summary.data;
  const enabled = d?.blocking?.enabled ?? true;

  return (
    <div className="pihole-page">
      <div className="board-bar board-head">
        <div className="board-head-text">
          <h2 className="board-title">Pi-hole</h2>
          <div className="board-sub t-dim">
            the LAN&apos;s only DNS + DHCP — pausing only lifts blocklist filtering, resolution never stops
          </div>
        </div>
        <span className="spacer" />
        <a className="tb-btn" href="http://rpi.lan/admin" target="_blank" rel="noreferrer">
          <ExternalLink /> Admin UI
        </a>
      </div>

      <div className="pihole-grid">
        <section className="glass card">
          <div className="w-head">
            <span className="w-title">Blocking</span>
            <span className="w-meta">
              <span className="pill" data-s={enabled ? 'ok' : 'warn'}>
                {enabled ? 'active' : `paused${d?.blocking?.timer ? ` · ${Math.round(d.blocking.timer / 60)}m left` : ''}`}
              </span>
            </span>
          </div>
          <div className="big-metric">{d?.ads_percentage_today != null ? `${d.ads_percentage_today.toFixed(1)}%` : '—'}<small> of today&apos;s queries blocked</small></div>
          <div className="kv-rows">
            <div className="kv-row"><span>queries today</span><span>{d?.dns_queries_today?.toLocaleString() ?? '—'}</span></div>
            <div className="kv-row"><span>blocked</span><span>{d?.ads_blocked_today?.toLocaleString() ?? '—'}</span></div>
            <div className="kv-row"><span>active clients</span><span>{d?.unique_clients ?? '—'}</span></div>
            <div className="kv-row"><span>gravity domains</span><span>{d?.gravity_domains?.toLocaleString() ?? '—'}</span></div>
          </div>
          <div className="w-actions">
            {enabled ? (
              PAUSES.map((p) => (
                <button key={p.s} className="tb-btn" disabled={blocking.isPending}
                  onClick={() => blocking.mutate({ enabled: false, seconds: p.s })}>
                  <Pause /> {p.label}
                </button>
              ))
            ) : (
              <button className="tb-btn primary" disabled={blocking.isPending}
                onClick={() => blocking.mutate({ enabled: true })}>
                <Play /> Resume now
              </button>
            )}
          </div>
          <p className="t-dim">A pause always carries a server-side timer — blocking resumes on its own even if this tab closes.</p>
        </section>

        <section className="glass card">
          <div className="w-head">
            <span className="w-title">Top blocked today</span>
            <span className="w-meta">
              <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
                {[10, 15, 25].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </span>
          </div>
          {top.isError && <p className="t-dim">Unavailable — {(top.error as Error).message}</p>}
          <table className="detail-table">
            <tbody>
              {(top.data?.domains ?? []).map((row) => (
                <tr key={row.domain}>
                  <td className="mono ct-image" title={row.domain}>{row.domain}</td>
                  <td>{row.count.toLocaleString()}</td>
                  <td>
                    <button className="tb-btn sm" disabled={allow.isPending}
                      title={`Whitelist ${row.domain} (allow-only — this can never add a block)`}
                      onClick={() => allow.mutate(row.domain)}>
                      <ShieldCheck /> Allow
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="t-dim">Replaces ssh-ing in for <span className="mono">pihole allow</span> — Teams telemetry topping the list is normal.</p>
        </section>
      </div>
    </div>
  );
}
