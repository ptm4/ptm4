// Fleet control hub: per-host reboot (typed confirm), apt upgrade with a live log
// tail, allowlisted systemd unit restarts, Wake-on-LAN, and the Kuma monitor panel.
//
// The load-bearing behaviours ported verbatim from v1:
//   - rebooting rpi kills the connection serving this page; a dropped fetch there
//     IS success, and the watcher then polls /api/health (parsed as JSON, since
//     nginx serves a 200 holding page during the boot window).
//   - the timeout ladder: this page's fetches sit above the backend's caps and
//     below nginx's 240s on /api/agents.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Stethoscope, Pause, Terminal, Zap } from 'lucide-react';
import { get, post, ApiError } from '../lib/api';
import { toast } from '../lib/toast';
import { useAgents, useContainers, useRunnerReport, useUptime, useVitals } from '../lib/queries';
import { useConfirm } from '../components/ConfirmDialog';
import {
  CRITICAL_UNITS, HOST_REBOOT_IMPACT, HOST_ROLES, UNIT_IMPACT, UNIT_LABELS, agentTooOld,
} from '../lib/impact';
import type { AgentRow } from '../lib/api-types';

const HOSTS = ['opti', 'rpi', 'noblenumbat'];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function ckUptime(s: number | null | undefined): string | null {
  if (s == null) return null;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

interface AptStatus {
  running?: boolean;
  result?: string;
  exit_status?: string;
  reboot_required?: boolean;
  finished_at?: string;
  log_tail?: string[];
  already_running?: boolean;
  ok?: boolean;
}

export default function CockpitPage() {
  const agents = useAgents();
  const vitals = useVitals();
  const software = useRunnerReport('software-latest');
  const containers = useContainers();
  const uptime = useUptime();
  const qc = useQueryClient();
  const { confirm, dialog } = useConfirm();

  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [watch, setWatch] = useState<Record<string, { label: string; t0: number; secs: number }>>({});
  const [apt, setApt] = useState<Record<string, AptStatus>>({});
  const watchToken = useRef<Record<string, number>>({});

  const setBusyFor = (host: string, on: boolean) =>
    setBusy((s) => { const n = new Set(s); if (on) n.add(host); else n.delete(host); return n; });

  // Poll until the host answers again; drives the "down Xs" line on its card.
  const watchHostReturn = useCallback(async (host: string, label = 'rebooting') => {
    const t0 = Date.now();
    watchToken.current[host] = t0;
    setBusyFor(host, true);
    setWatch((w) => ({ ...w, [host]: { label, t0, secs: 0 } }));

    const giveUpMs = 10 * 60 * 1000;
    while (Date.now() - t0 < giveUpMs) {
      await sleep(5000);
      if (watchToken.current[host] !== t0) return;   // superseded by a newer watch
      setWatch((w) => (w[host] ? { ...w, [host]: { ...w[host], secs: Math.round((Date.now() - t0) / 1000) } } : w));

      let back = false;
      try {
        if (host === 'rpi') {
          // Must parse as JSON, not just res.ok: during the boot window nginx serves
          // the 200 "_restarting" holding page, which would read as a false recovery.
          const health = await get<{ status?: string }>('/api/health', 4000);
          back = health?.status === 'ok';
        }
        if (!back) {
          const a = await get<{ hosts: AgentRow[] }>('/api/agents', 8000);
          back = !!a.hosts.find((h) => h.id === host)?.reachable;
          qc.setQueryData(['agents'], a);
        }
      } catch { /* still down — the gap is the honest answer */ }

      if (back) {
        setWatch((w) => { const n = { ...w }; delete n[host]; return n; });
        setBusyFor(host, false);
        toast(`${host} is back online after ${Math.round((Date.now() - t0) / 1000)}s.`, 'ok');
        qc.invalidateQueries({ queryKey: ['agents'] });
        qc.invalidateQueries({ queryKey: ['containers'] });
        return;
      }
    }
    setWatch((w) => { const n = { ...w }; delete n[host]; return n; });
    setBusyFor(host, false);
    toast(`${host} has not come back after 10 minutes — check it directly.`, 'crit', { sticky: true });
  }, [qc]);

  const rebootHost = async (host: string) => {
    const ok = await confirm({
      title: `Reboot ${host}?`,
      tone: 'crit',
      confirmLabel: 'Reboot',
      requireTyped: host,
      body: (
        <>
          <p>Reboots <b>{host}</b> now. Expect ~2 minutes of downtime.</p>
          <p className="confirm-danger">⚠ {HOST_REBOOT_IMPACT[host]}</p>
        </>
      ),
    });
    if (!ok) return;
    setBusyFor(host, true);
    try {
      const d = await post<{ ok?: boolean }>(`/api/agents/${host}/reboot`, undefined, 20_000);
      if (d?.ok) {
        toast(`Reboot accepted — ${host} goes down in ~2s. Watching for it to return…`, 'warn');
        watchHostReturn(host);
        return;
      }
      setBusyFor(host, false);
      toast(`Reboot of ${host} did not take: ${JSON.stringify(d)}`, 'crit', { sticky: true });
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        setBusyFor(host, false);
        toast(`Reboot of ${host} REFUSED by the ZFS guard: ${err.message}`, 'crit', { sticky: true });
      } else if (err.status === 404) {
        setBusyFor(host, false);
        toast(agentTooOld(host, 'reboots'), 'crit', { sticky: true });
      } else if (host === 'rpi') {
        // The host serving this page: a dropped connection here IS the reboot working.
        toast('Connection dropped — expected when rebooting rpi, it serves this page. Watching for it to return…', 'warn');
        watchHostReturn(host);
      } else {
        setBusyFor(host, false);
        toast(`Reboot request to ${host} failed: ${err.message}`, 'crit', { sticky: true });
      }
    }
  };

  const pollAptStatus = async (host: string) => {
    const t0 = Date.now();
    const giveUpMs = 30 * 60 * 1000;   // a big upgrade on the Pi genuinely runs long
    while (Date.now() - t0 < giveUpMs) {
      await sleep(5000);
      let st: AptStatus | null = null;
      try { st = await get<AptStatus>(`/api/agents/${host}/apt-status`, 10_000); } catch { /* transient */ }
      if (!st) continue;
      setApt((a) => ({ ...a, [host]: st! }));
      if (!st.running) {
        setBusyFor(host, false);
        const good = st.result === 'success' || st.exit_status === '0';
        toast(
          good
            ? `Apt upgrade finished on ${host}${st.reboot_required ? ' — reboot required to finish.' : '.'}`
            : `Apt upgrade on ${host} ended with result "${st.result ?? '?'}" — see the log on its card.`,
          good ? 'ok' : 'crit', { sticky: !good },
        );
        qc.invalidateQueries({ queryKey: ['agents'] });
        return;
      }
    }
    setBusyFor(host, false);
    toast(`Apt upgrade on ${host} still running after 30 min — check /var/log/homelab-autoupdate.log on the host.`, 'warn', { sticky: true });
  };

  const aptUpgrade = async (host: string) => {
    const ok = await confirm({
      title: `Apt upgrade on ${host}?`,
      tone: 'warn',
      confirmLabel: 'Upgrade now',
      body: (
        <>
          <p>Runs the nightly <code>homelab-autoupdate</code> unit on <b>{host}</b> now
            (apt update + full upgrade + autoremove) — the same code path that already
            runs unattended at 02:00.</p>
          <p className="t-dim">Progress and the log tail show on the card. If the upgrade
            wants a reboot, the Reboot button lights up afterwards.</p>
        </>
      ),
    });
    if (!ok) return;
    setBusyFor(host, true);
    try {
      const d = await post<AptStatus>(`/api/agents/${host}/apt-upgrade`, undefined, 15_000);
      if (!d?.ok) {
        setBusyFor(host, false);
        toast(`Apt upgrade on ${host} failed to start.`, 'crit', { sticky: true });
        return;
      }
      if (d.already_running) toast(`An apt run is already in progress on ${host} — attaching to it.`, 'warn');
      pollAptStatus(host);
    } catch (e) {
      setBusyFor(host, false);
      const err = e as ApiError;
      toast(err.status === 404 ? agentTooOld(host, 'apt upgrades') : `Apt upgrade on ${host} failed: ${err.message}`,
        'crit', { sticky: true });
    }
  };

  const restartUnit = async (host: string, unit: string) => {
    const critical = CRITICAL_UNITS.has(unit);
    const ok = await confirm({
      title: `Restart ${unit}?`,
      tone: critical ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: critical ? unit : null,
      body: (
        <>
          <p>Runs <code>systemctl restart {unit}</code> on <b>{host}</b>.</p>
          {UNIT_IMPACT[unit] && <p className="confirm-danger">⚠ {UNIT_IMPACT[unit]}</p>}
          {unit === 'hl-arch-agent.service' && (
            <p className="t-dim">This is the agent itself — it responds first and restarts ~2s later.</p>
          )}
          {unit === 'vpn-stack-heal.service' && (
            <p className="t-dim">vpn-stack-heal is a oneshot: this simply runs the heal check now.</p>
          )}
        </>
      ),
    });
    if (!ok) return;
    setBusyFor(host, true);
    try {
      // 170s sits above the backend's 160s cap and below nginx's 240s.
      const d = await post<{ ok?: boolean; self_restart?: boolean }>(
        `/api/agents/${host}/restart-service`, { unit }, 170_000);
      setBusyFor(host, false);
      if (d?.self_restart) {
        toast(`Agent on ${host} is restarting itself — its card refreshes shortly.`, 'warn');
        setTimeout(() => qc.invalidateQueries({ queryKey: ['agents'] }), 6000);
      } else {
        toast(`${unit} restarted on ${host}.`, 'ok');
        qc.invalidateQueries({ queryKey: ['containers'] });
      }
    } catch (e) {
      setBusyFor(host, false);
      toast(`Restart of ${unit} on ${host} failed: ${(e as Error).message}`, 'crit', { sticky: true });
    }
  };

  const wakeHost = async (host: string) => {
    setBusyFor(host, true);
    try {
      const d = await post<{ sent_by?: string }>(`/api/agents/${host}/wake`, undefined, 15_000);
      toast(`Wake packet sent to ${host}${d?.sent_by ? ` by ${d.sent_by}` : ''} — watching for it to return…`, 'warn');
      watchHostReturn(host, 'waking');
    } catch (e) {
      setBusyFor(host, false);
      toast(`Wake failed: ${(e as Error).message}`, 'crit', { sticky: true });
    }
  };

  const runDoctor = async () => {
    try {
      await post('/api/runners/homelab-doctor/run');
      toast('Homelab Doctor queued', 'ok');
    } catch (e) { toast(`Doctor run failed: ${(e as Error).message}`, 'crit'); }
  };

  const syncAgents = async () => {
    try {
      await post('/api/agents/sync-all', undefined, 30_000);
      toast('Agents synced', 'ok');
      qc.invalidateQueries({ queryKey: ['agents'] });
    } catch (e) { toast(`Sync failed: ${(e as Error).message}`, 'crit'); }
  };

  const pausePihole = async () => {
    try {
      await post('/api/pihole/blocking', { enabled: false, seconds: 300 }, 15_000);
      toast('Pi-hole paused for 5 minutes', 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    } catch (e) { toast(`Pi-hole: ${(e as Error).message}`, 'crit'); }
  };

  // 30s refresh while this page is mounted, matching v1's self-clearing timer.
  useEffect(() => {
    const id = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      qc.invalidateQueries({ queryKey: ['vitals'] });
    }, 30_000);
    return () => clearInterval(id);
  }, [qc]);

  const agentById = Object.fromEntries((agents.data?.hosts ?? []).map((h) => [h.id, h]));
  const swByHost = Object.fromEntries((software.data?.hosts ?? []).map((h) => [h.host, h]));
  const updateCount = (containers.data?.hosts ?? []).reduce(
    (n, h) => n + h.containers.filter((c) => c.update_available).length, 0);

  return (
    <div className="cockpit-page">
      <div className="board-bar">
        <span className="spacer" />
        <button className="tb-btn" onClick={runDoctor}><Stethoscope /> Doctor</button>
        <button className="tb-btn" onClick={syncAgents}><RefreshCw /> Sync agents</button>
        <button className="tb-btn" onClick={pausePihole}><Pause /> Pi-hole 5 min</button>
        {updateCount > 0 && (
          <a className="tb-btn" href="/updates">⬆ {updateCount} update{updateCount > 1 ? 's' : ''}</a>
        )}
      </div>

      <div className="cockpit-grid">
        {HOSTS.map((host) => {
          const a = agentById[host];
          const v = vitals.data?.hosts[host]?.latest;
          const m = (swByHost[host]?.metrics ?? {}) as Record<string, any>;
          const reachable = !!a?.reachable;
          const hasControls = Array.isArray(a?.allowed_units);   // null = pre-0.4.0 agent
          const isBusy = busy.has(host);
          const w = watch[host];
          const aptState = apt[host];
          const termUrl = host === 'rpi'
            ? 'https://rpi.lan:9090/system/terminal'
            : `https://rpi.lan:9090/@${host}/system/terminal`;
          const wakeable = (agents.data?.hosts ?? [])
            .some((h) => h.reachable && (h.wake_targets ?? []).includes(host));

          const stats = v ? [
            v.uptime_s != null ? `up ${ckUptime(v.uptime_s)}` : null,
            v.load1 != null ? `load ${v.load1.toFixed(2)}` : null,
            v.cpu_pct != null ? `cpu ${v.cpu_pct}%` : null,
            v.mem_pct != null ? `mem ${v.mem_pct}%` : null,
            v.temp_c != null ? `${Math.round(v.temp_c)}°C` : null,
          ].filter(Boolean).join(' · ') : 'no vitals';

          return (
            <section key={host} className="ck-card glass card">
              <header className="ck-head">
                <span className="mono ck-host">{host}</span>
                <span className="t-dim">{HOST_ROLES[host]}</span>
                <span className="spacer" />
                <span className="pill" data-s={reachable ? 'ok' : 'crit'}>{reachable ? 'up' : 'unreachable'}</span>
                {a?.agent_version && <span className="chip" title="hl-arch-agent version">v{a.agent_version}</span>}
              </header>

              <div className="t-dim ck-stats">{stats}</div>

              <div className="ck-chips">
                {m.reboot_required && <span className="chip" data-s="warn" title={m.reboot_pkgs ?? ''}>reboot req</span>}
                {m.pending_count ? (
                  <span className="chip">{m.pending_count} pkg{m.security_count ? <> · <b className="t-crit">{m.security_count} sec</b></> : null}</span>
                ) : null}
                {m.image_update_count ? <span className="chip">{m.image_update_count} image{m.image_update_count > 1 ? 's' : ''}</span> : null}
                {!m.reboot_required && !m.pending_count && !m.image_update_count && (
                  <span className="t-dim">{software.data ? 'patched · no reboot needed' : 'package info unavailable'}</span>
                )}
              </div>

              {w && <div className="t-dim ck-status">⏳ {w.label} — down {w.secs}s…</div>}

              {aptState && (aptState.running ? (
                <div className="t-dim ck-status">
                  ⏳ apt running… <span className="mono">{(aptState.log_tail ?? []).slice(-1)[0] ?? ''}</span>
                </div>
              ) : (
                <details className="ck-aptlog">
                  <summary className="t-dim">apt log · {aptState.finished_at ?? 'last run'}</summary>
                  <pre className="mono">{(aptState.log_tail ?? []).join('\n')}</pre>
                </details>
              ))}

              <div className="ck-actions">
                {reachable && hasControls ? (
                  <>
                    <button className={`tb-btn danger${m.reboot_required ? ' hot' : ''}`}
                      disabled={isBusy} onClick={() => rebootHost(host)}>Reboot</button>
                    <button className="tb-btn" disabled={isBusy} onClick={() => aptUpgrade(host)}>Apt upgrade</button>
                    {(a!.allowed_units ?? []).map((u) => (
                      <button key={u} className="tb-btn" disabled={isBusy}
                        title={`systemctl restart ${u}`} onClick={() => restartUnit(host, u)}>
                        ↻ {UNIT_LABELS[u] ?? u}
                      </button>
                    ))}
                    <a className="tb-btn" href={termUrl} target="_blank" rel="noreferrer"
                      title={`Terminal on ${host} via Cockpit (rpi:9090, system login)`}>
                      <Terminal /> Terminal
                    </a>
                  </>
                ) : reachable ? (
                  <span className="t-dim">controls need agent v0.4.0 — reinstall hl-arch-agent.py on {host}</span>
                ) : wakeable ? (
                  <button className="tb-btn" disabled={isBusy} onClick={() => wakeHost(host)}><Zap /> Wake</button>
                ) : (
                  <span className="t-dim">unreachable — no WoL for this host, physical access needed if it is off</span>
                )}
              </div>
            </section>
          );
        })}

        <section className="ck-card glass card">
          <header className="ck-head">
            <span className="mono ck-host">android</span>
            <span className="t-dim">{HOST_ROLES.android}</span>
            <span className="spacer" />
            <AndroidPill />
          </header>
          <div className="t-dim">
            Status display only — no agent on this host, and it is often offline by
            design (it is a phone).
          </div>
        </section>
      </div>

      <section className="glass card ck-monitors">
        <div className="w-head">
          <span className="w-title">Monitors</span>
          <span className="w-meta">
            <a href="http://rpi.lan:3001/" target="_blank" rel="noreferrer">Uptime Kuma</a>
          </span>
        </div>
        {uptime.data?.ok ? (
          <>
            <span className="pill" data-s={uptime.data.down ? 'crit' : uptime.data.pending ? 'warn' : 'ok'}>
              {uptime.data.up}/{uptime.data.total} up
              {uptime.data.down ? ` · ${uptime.data.down} down` : ''}
              {uptime.data.pending ? ` · ${uptime.data.pending} pending` : ''}
            </span>
            <div className="mon-grid">
              {[...uptime.data.monitors]
                .sort((a, b) => {
                  // Down/pending first, so a problem is the first thing on the panel.
                  const rank: Record<string, number> = { down: 0, pending: 1, maintenance: 2, up: 3 };
                  return (rank[a.status] ?? 4) - (rank[b.status] ?? 4) || a.name.localeCompare(b.name);
                })
                .map((m) => (
                  <span className="mon" key={m.name} title={`${m.name} — ${m.status}${m.ms != null ? `, ${m.ms}ms` : ''}`}>
                    <span className="cdot" data-s={m.status === 'up' ? 'ok' : m.status === 'down' ? 'crit' : 'warn'} />
                    {m.name}
                    {m.ms != null && <span className="t-dim"> {m.ms}ms</span>}
                  </span>
                ))}
            </div>
          </>
        ) : (
          <div className="t-dim">Unavailable.</div>
        )}
      </section>

      {dialog}
    </div>
  );
}

function AndroidPill() {
  const [up, setUp] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    get('/api/llama/status', 5000).then(() => alive && setUp(true)).catch(() => alive && setUp(false));
    return () => { alive = false; };
  }, []);
  return <span className="pill" data-s={up ? 'ok' : 'warn'}>{up == null ? '…' : up ? 'up' : 'offline'}</span>;
}
