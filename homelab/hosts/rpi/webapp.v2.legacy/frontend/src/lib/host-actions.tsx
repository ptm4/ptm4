// Host actions as a hook, so any surface (host-vitals widget, future widgets)
// can offer Reboot / Apt / Terminal without owning Cockpit's card state. Carries
// the same safety semantics as the Cockpit page: typed confirm with blast-radius
// copy, the ZFS-guard 409, and "a dropped connection to rpi IS success".
import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { get, post, ApiError } from './api';
import { toast } from './toast';
import { useConfirm } from '../components/ConfirmDialog';
import { HOST_REBOOT_IMPACT, agentTooOld } from './impact';
import type { AgentRow } from './api-types';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function useHostActions(host: string) {
  const { confirm, dialog } = useConfirm();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const termUrl = host === 'rpi'
    ? 'https://rpi.lan:9090/system/terminal'
    : `https://rpi.lan:9090/@${host}/system/terminal`;

  // Poll until the host answers again, then refresh everything host-shaped.
  const watchReturn = useCallback(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 10 * 60_000) {
      await sleep(5000);
      let back = false;
      try {
        if (host === 'rpi') {
          // Parsed as JSON, not just res.ok — nginx serves a 200 holding page
          // during the boot window, which would read as a false recovery.
          const h = await get<{ status?: string }>('/api/health', 4000);
          back = h?.status === 'ok';
        }
        if (!back) {
          const a = await get<{ hosts: AgentRow[] }>('/api/agents', 8000);
          back = !!a.hosts.find((x) => x.id === host)?.reachable;
        }
      } catch { /* still down */ }
      if (back) {
        setBusy(false);
        toast(`${host} is back online after ${Math.round((Date.now() - t0) / 1000)}s.`, 'ok');
        qc.invalidateQueries({ queryKey: ['agents'] });
        qc.invalidateQueries({ queryKey: ['vitals'] });
        qc.invalidateQueries({ queryKey: ['containers'] });
        return;
      }
    }
    setBusy(false);
    toast(`${host} has not come back after 10 minutes — check it directly.`, 'crit', { sticky: true });
  }, [host, qc]);

  const reboot = useCallback(async () => {
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
    setBusy(true);
    try {
      const d = await post<{ ok?: boolean }>(`/api/agents/${host}/reboot`, undefined, 20_000);
      if (d?.ok) {
        toast(`Reboot accepted — ${host} goes down in ~2s. Watching for it to return…`, 'warn');
        watchReturn();
        return;
      }
      setBusy(false);
      toast(`Reboot of ${host} did not take.`, 'crit', { sticky: true });
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        setBusy(false);
        toast(`Reboot of ${host} REFUSED by the ZFS guard: ${err.message}`, 'crit', { sticky: true });
      } else if (err.status === 404) {
        setBusy(false);
        toast(agentTooOld(host, 'reboots'), 'crit', { sticky: true });
      } else if (host === 'rpi') {
        toast('Connection dropped — expected when rebooting rpi, it serves this page. Watching for it to return…', 'warn');
        watchReturn();
      } else {
        setBusy(false);
        toast(`Reboot request to ${host} failed: ${err.message}`, 'crit', { sticky: true });
      }
    }
  }, [host, confirm, watchReturn]);

  const aptUpgrade = useCallback(async () => {
    const ok = await confirm({
      title: `Apt upgrade on ${host}?`,
      tone: 'warn',
      confirmLabel: 'Upgrade now',
      body: (
        <>
          <p>Runs the nightly <code>homelab-autoupdate</code> unit on <b>{host}</b> now —
            the same code path that runs unattended at 02:00.</p>
          <p className="t-dim">The live log tail is on this host&apos;s Cockpit card.</p>
        </>
      ),
    });
    if (!ok) return;
    setBusy(true);
    try {
      const d = await post<{ ok?: boolean; already_running?: boolean }>(`/api/agents/${host}/apt-upgrade`, undefined, 15_000);
      setBusy(false);
      if (!d?.ok) {
        toast(`Apt upgrade on ${host} failed to start.`, 'crit', { sticky: true });
        return;
      }
      toast(d.already_running
        ? `An apt run is already in progress on ${host} — follow it on Cockpit.`
        : `Apt upgrade started on ${host} — follow the log on Cockpit.`, 'ok');
    } catch (e) {
      setBusy(false);
      const err = e as ApiError;
      toast(err.status === 404 ? agentTooOld(host, 'apt upgrades') : `Apt upgrade on ${host} failed: ${err.message}`,
        'crit', { sticky: true });
    }
  }, [host, confirm]);

  return { reboot, aptUpgrade, termUrl, busy, dialog };
}
