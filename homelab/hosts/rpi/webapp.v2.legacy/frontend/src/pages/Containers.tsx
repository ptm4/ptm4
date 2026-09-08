// The container control room: every container across the fleet as one live table —
// current docker ps (report data joined with Dozzle's live SSE feed), per-container
// log viewer (Dozzle deep-linked in a modal), restart and update actions with the
// same blast-radius gates the Cockpit uses, and text/host filtering.
//
// opti intentionally never appears here: it runs no docker (control plane only).
import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ScrollText, RotateCw, ArrowUpCircle } from 'lucide-react';
import { useContainers } from '../lib/queries';
import { useDozzle } from '../lib/dozzle';
import { post, ApiError } from '../lib/api';
import { toast } from '../lib/toast';
import { durSince } from '../lib/format';
import { Modal } from '../components/Modal';
import { useConfirm } from '../components/ConfirmDialog';
import { CRITICAL_CONTAINERS, SELF_CONTAINERS } from '../lib/impact';

interface Row {
  key: string;
  host: string;
  name: string;
  image: string | null;
  project: string | null;
  ports: string[];   // formatted "host→container/proto", ipv4/ipv6 duplicates collapsed
  status: string | null;
  since: string | null;
  up: boolean;
  update: boolean;
  id?: string;
  health?: string;
  liveState?: string;
}

export default function ContainersPage() {
  const containers = useContainers();
  const dozzle = useDozzle();
  const qc = useQueryClient();
  const { confirm, dialog } = useConfirm();
  const [filter, setFilter] = useState('');
  const [hostFilter, setHostFilter] = useState<string>('all');
  const [logs, setLogs] = useState<Row | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());

  const setBusyFor = (key: string, on: boolean) =>
    setBusy((s) => { const n = new Set(s); if (on) n.add(key); else n.delete(key); return n; });

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    for (const h of containers.data?.hosts ?? []) {
      for (const c of h.containers) {
        const dz = dozzle.byName[c.name];
        out.push({
          key: `${h.host}/${c.name}`,
          host: h.host,
          name: c.name,
          image: c.image ?? null,
          project: c.compose_project ?? null,
          ports: [...new Set((c.ports ?? []).map((p) =>
            p.host_port === p.container_port
              ? `${p.host_port}/${p.proto ?? 'tcp'}`
              : `${p.host_port ?? '?'}→${p.container_port ?? '?'}/${p.proto ?? 'tcp'}`))],
          status: c.status ?? null,
          since: c.status_since ?? null,
          up: dz ? dz.state === 'running' : c.up,
          update: c.update_available,
          id: dz?.id,
          health: dz?.health,
          liveState: dz?.state,
        });
      }
    }
    const f = filter.trim().toLowerCase();
    return out
      .filter((r) => hostFilter === 'all' || r.host === hostFilter)
      .filter((r) => !f || r.name.includes(f) || (r.image ?? '').toLowerCase().includes(f) || (r.project ?? '').includes(f))
      .sort((a, b) => Number(a.up) - Number(b.up) || a.host.localeCompare(b.host) || a.name.localeCompare(b.name));
  }, [containers.data, dozzle.byName, filter, hostFilter]);

  const hosts = [...new Set((containers.data?.hosts ?? []).map((h) => h.host))];
  const total = rows.length;
  const up = rows.filter((r) => r.up).length;
  const updates = rows.filter((r) => r.update).length;

  const restart = async (row: Row) => {
    const danger = CRITICAL_CONTAINERS[row.name];
    const ok = await confirm({
      title: `Restart ${row.name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Restart',
      requireTyped: danger ? row.name : null,
      body: (
        <>
          <p>Runs <code>docker restart {row.name}</code> on <b>{row.host}</b> via its agent (~10–15s for a heavy container).</p>
          {danger && <p className="confirm-danger">⚠ {danger}</p>}
        </>
      ),
    });
    if (!ok) return;
    setBusyFor(row.key, true);
    try {
      await post(`/api/agents/${row.host}/restart-container`, { container: row.name }, 60_000);
      toast(`${row.name} restarted on ${row.host}`, 'ok');
      qc.invalidateQueries({ queryKey: ['containers'] });
    } catch (e) {
      // Restarting the container serving this page kills the very response we're
      // waiting on — a dropped fetch or bare 502/504 IS the restart working.
      const err = e as ApiError;
      if (SELF_CONTAINERS.has(row.name) && (err.status === 502 || err.status === 504 || err.status === undefined)) {
        toast(`Connection dropped — expected when restarting ${row.name}: it serves this page. It is almost certainly back; reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Restart of ${row.name} failed: ${err.message}`, 'crit', { sticky: true });
      }
    } finally {
      setBusyFor(row.key, false);
    }
  };

  const update = async (row: Row) => {
    const danger = CRITICAL_CONTAINERS[row.name];
    const ok = await confirm({
      title: `Update ${row.name}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate',
      requireTyped: danger ? row.name : null,
      body: (
        <>
          <p>Pulls the newest image for <b>{row.name}</b> on <b>{row.host}</b> and recreates
            just that compose service. A registry pull on the Pi can run for minutes.</p>
          {danger && <p className="confirm-danger">⚠ {danger}</p>}
        </>
      ),
    });
    if (!ok) return;
    setBusyFor(row.key, true);
    try {
      // 230s sits above the backend's 220s agent cap, below nginx's 240s.
      await post(`/api/agents/${row.host}/update-container`, { container: row.name }, 230_000);
      toast(`${row.name} updated on ${row.host}`, 'ok');
      qc.invalidateQueries({ queryKey: ['containers'] });
      qc.invalidateQueries({ queryKey: ['updates'] });
    } catch (e) {
      const err = e as ApiError;
      if (SELF_CONTAINERS.has(row.name) && (err.status === 502 || err.status === 504 || err.status === undefined)) {
        toast(`Connection dropped — expected when updating ${row.name}: it serves this page. Reload to confirm.`, 'warn', { sticky: true });
      } else {
        toast(`Update of ${row.name} failed: ${err.message}`, 'crit', { sticky: true });
      }
    } finally {
      setBusyFor(row.key, false);
    }
  };

  return (
    <div className="containers-page">
      <div className="board-bar board-head">
        <div className="board-head-text">
          <h2 className="board-title">Containers</h2>
          <div className="board-sub t-dim">
            {up}/{total} up{updates ? ` · ${updates} update${updates > 1 ? 's' : ''} available` : ''}
            {' · '}
            <span className={dozzle.live ? 't-ok' : ''}>{dozzle.live ? 'live via dozzle' : 'report data (dozzle stream offline)'}</span>
          </div>
        </div>
        <span className="spacer" />
        <div className="seg">
          <button className={`seg-btn${hostFilter === 'all' ? ' active' : ''}`} onClick={() => setHostFilter('all')}>all</button>
          {hosts.map((h) => (
            <button key={h} className={`seg-btn${hostFilter === h ? ' active' : ''}`} onClick={() => setHostFilter(h)}>{h}</button>
          ))}
        </div>
        <input className="links-filter glass ct-filter" placeholder="Filter name / image / project…"
          value={filter} onChange={(e) => setFilter(e.target.value)} />
        <button className="tb-btn" onClick={() => qc.invalidateQueries({ queryKey: ['containers'] })}>
          <RefreshCw /> Refresh
        </button>
      </div>

      <section className="glass card ct-table-card">
        {containers.isLoading && <div className="spin" />}
        <table className="detail-table ct-table">
          <thead>
            <tr><th /><th>Name</th><th>Host</th><th>Image</th><th>Project</th><th>Ports</th><th>Up</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} data-down={!r.up || undefined}>
                <td>
                  <span className="cdot" data-s={r.up ? (r.health === 'unhealthy' ? 'warn' : 'ok') : 'crit'}
                    title={r.liveState ?? r.status ?? 'unknown'} />
                </td>
                <td className="mono ct-name">
                  {r.name}
                  {r.health === 'unhealthy' && <span className="badge badge-alert">UNHEALTHY</span>}
                  {r.update && <span className="badge badge-stale">update</span>}
                </td>
                <td>{r.host}</td>
                <td className="mono t-dim ct-image" title={r.image ?? ''}>{r.image ?? '—'}</td>
                <td className="t-dim">{r.project ?? '—'}</td>
                <td className="mono t-dim ct-ports" title={r.ports.join(', ')}>
                  {r.ports.length ? r.ports.slice(0, 2).join(', ') + (r.ports.length > 2 ? '…' : '') : '—'}
                </td>
                <td className="t-dim">{r.since ? durSince(r.since) : (r.status ?? '—')}</td>
                <td className="ct-actions">
                  <button className="tb-btn sm" title={r.id ? 'Live logs (Dozzle)' : 'Open the Logs page — no live id for this container yet'}
                    onClick={() => r.id ? setLogs(r) : window.location.assign('/logs')}>
                    <ScrollText /> Logs
                  </button>
                  <button className="tb-btn sm" disabled={busy.has(r.key)} title={`Restart on ${r.host}`}
                    onClick={() => restart(r)}>
                    <RotateCw /> Restart
                  </button>
                  {r.update && (
                    <button className="tb-btn sm" disabled={busy.has(r.key)} title="Pull newest image & recreate"
                      onClick={() => update(r)}>
                      <ArrowUpCircle /> Update
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && !containers.isLoading && (
              <tr><td colSpan={8} className="t-dim">Nothing matches.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {logs && (
        <Modal open onClose={() => setLogs(null)} title={`${logs.name} — live logs (${logs.host})`} wide>
          <iframe className="ct-logs-frame" src={`/dozzle/container/${logs.id}`} title={`${logs.name} logs`} />
        </Modal>
      )}
      {dialog}
    </div>
  );
}
