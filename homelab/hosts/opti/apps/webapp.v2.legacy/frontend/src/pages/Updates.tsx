// Updates center — every pending container image and apt package across the fleet
// as one work queue, with the existing per-item apply actions. Cockpit stays the
// host-centric view; this is the "what needs doing" view.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowUpCircle, Terminal } from 'lucide-react';
import { get, post } from '../lib/api';
import { toast } from '../lib/toast';
import { relTime } from '../lib/format';
import { useConfirm } from '../components/ConfirmDialog';
import { CRITICAL_CONTAINERS, SELF_CONTAINERS } from '../lib/impact';

interface ImageUpdate {
  host: string; container: string; image: string | null;
  compose_project: string | null; running: boolean; self: boolean;
}
interface PackageUpdate {
  host: string; pending: number; security: number;
  reboot_required: boolean; reboot_pkgs: string | null;
}
interface UpdatesResp {
  images: ImageUpdate[];
  packages: PackageUpdate[];
  counts: { images: number; packages: number; security: number; reboots: number };
  collected_at: string | null;
}

export default function UpdatesPage() {
  const qc = useQueryClient();
  const { confirm, dialog } = useConfirm();

  const q = useQuery({
    queryKey: ['updates'],
    queryFn: () => get<UpdatesResp>('/api/updates', 15_000),
    refetchInterval: 5 * 60_000,
  });

  // 230s: above the backend's 220s agent cap, below nginx's 240s on /api/agents.
  const update = useMutation({
    mutationFn: ({ host, container }: { host: string; container: string }) =>
      post(`/api/agents/${host}/update-container`, { container }, 230_000),
    onSuccess: (_d, v) => {
      toast(`${v.container} updated on ${v.host}`, 'ok');
      qc.invalidateQueries({ queryKey: ['updates'] });
      qc.invalidateQueries({ queryKey: ['containers'] });
    },
    onError: (e, v) => {
      // Updating a container that serves this page kills the response to the very
      // request that asked for it — both a dropped fetch and a 502/504 mean success.
      if (SELF_CONTAINERS.has(v.container)) {
        toast(`Connection dropped — expected when updating ${v.container}: it serves this page. It is almost certainly back; reload to confirm.`,
          'warn', { sticky: true });
      } else {
        toast(`Update of ${v.container} failed: ${(e as Error).message}`, 'crit', { sticky: true });
      }
    },
  });

  const applyUpdate = async (row: ImageUpdate) => {
    const danger = CRITICAL_CONTAINERS[row.container];
    const ok = await confirm({
      title: `Update ${row.container}?`,
      tone: danger ? 'crit' : 'warn',
      confirmLabel: 'Pull & recreate',
      requireTyped: danger ? row.container : null,
      body: (
        <>
          <p>Pulls the newest image for <b>{row.container}</b> on <b>{row.host}</b> and
            recreates just that compose service.</p>
          {danger && <p className="confirm-danger">⚠ {danger}</p>}
          <p className="t-dim">A registry pull on the Pi can run for minutes; the request
            waits up to ~4 minutes.</p>
        </>
      ),
    });
    if (!ok) return;
    update.mutate({ host: row.host, container: row.container });
  };

  const counts = q.data?.counts;

  return (
    <div className="updates-page">
      <div className="board-bar">
        <span className="board-name">
          {counts
            ? `${counts.images} image${counts.images === 1 ? '' : 's'} · ${counts.packages} package${counts.packages === 1 ? '' : 's'}`
            : 'loading…'}
          {counts?.security ? <span className="t-crit"> · {counts.security} security</span> : null}
          {counts?.reboots ? <span className="t-warn"> · {counts.reboots} reboot pending</span> : null}
        </span>
        <span className="spacer" />
        <span className="t-dim">from software inventory {relTime(q.data?.collected_at)}</span>
      </div>

      <section className="glass card">
        <div className="w-head"><span className="w-title">Container images</span></div>
        {q.data?.images.length === 0 && <p className="t-dim">Every container is on its newest image.</p>}
        {(q.data?.images.length ?? 0) > 0 && (
          <table className="detail-table updates-table">
            <thead><tr><th>Container</th><th>Host</th><th>Image</th><th>State</th><th /></tr></thead>
            <tbody>
              {q.data!.images.map((row) => (
                <tr key={`${row.host}/${row.container}`}>
                  <td className="mono">{row.container}{row.self && <span className="badge badge-stale"> serves this page</span>}</td>
                  <td>{row.host}</td>
                  <td className="mono t-dim">{row.image ?? '—'}</td>
                  <td>{row.running ? 'running' : <span className="t-warn">stopped</span>}</td>
                  <td>
                    <button className="tb-btn" disabled={update.isPending} onClick={() => applyUpdate(row)}>
                      <ArrowUpCircle /> Update
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="glass card">
        <div className="w-head"><span className="w-title">Packages</span></div>
        {q.data?.packages.length === 0 && <p className="t-dim">All hosts fully patched.</p>}
        <div className="kv-rows">
          {(q.data?.packages ?? []).map((p) => (
            <div className="kv-row" key={p.host}>
              <span className="mono">{p.host}</span>
              <span>
                {p.pending} pending
                {p.security > 0 && <span className="t-crit"> · {p.security} security</span>}
                {p.reboot_required && <span className="t-warn" title={p.reboot_pkgs ?? ''}> · reboot required</span>}
                {' · '}
                <a href="/cockpit">apt upgrade →</a>
              </span>
            </div>
          ))}
        </div>
        <p className="t-dim">
          <Terminal size={12} /> Package upgrades run from the Cockpit host cards, where the
          live apt log and the reboot button live.
        </p>
      </section>

      {dialog}
    </div>
  );
}
