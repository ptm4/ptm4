// Host actions as a factory, so any surface (host-vitals widget, host page,
// Cockpit) can offer Reboot / Apt / Terminal without owning Cockpit's card state.
// Carries the same safety semantics as the Cockpit page: typed confirm with
// blast-radius copy, the ZFS-guard 409, and "a dropped connection to rpi IS success".
// Call during component initialisation (it reads the query client from context).
import { useQueryClient } from '@tanstack/svelte-query';
import { get, post, ApiError } from './api/client';
import { toast } from './stores/toast.svelte';
import { confirm } from './stores/confirm.svelte';
import { HOST_REBOOT_IMPACT, agentTooOld } from './impact';
import type { AgentRow } from './api/types';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function termUrlFor(host: string): string {
  return host === 'rpi'
    ? 'https://rpi.lan:9090/system/terminal'
    : `https://rpi.lan:9090/@${host}/system/terminal`;
}

export function createHostActions(host: () => string) {
  const qc = useQueryClient();
  let busy = $state(false);

  // Poll until the host answers again, then refresh everything host-shaped.
  async function watchReturn() {
    const h = host();
    const t0 = Date.now();
    while (Date.now() - t0 < 10 * 60_000) {
      await sleep(5000);
      let back = false;
      try {
        if (h === 'rpi') {
          // Parsed as JSON, not just res.ok — nginx serves a 200 holding page
          // during the boot window, which would read as a false recovery.
          const r = await get<{ status?: string }>('/api/health', 4000);
          back = r?.status === 'ok';
        }
        if (!back) {
          const a = await get<{ hosts: AgentRow[] }>('/api/agents', 8000);
          back = !!a.hosts.find((x) => x.id === h)?.reachable;
        }
      } catch { /* still down */ }
      if (back) {
        busy = false;
        toast(`${h} is back online after ${Math.round((Date.now() - t0) / 1000)}s.`, 'ok');
        qc.invalidateQueries({ queryKey: ['agents'] });
        qc.invalidateQueries({ queryKey: ['vitals'] });
        qc.invalidateQueries({ queryKey: ['containers'] });
        return;
      }
    }
    busy = false;
    toast(`${h} has not come back after 10 minutes — check it directly.`, 'crit', { sticky: true });
  }

  async function reboot() {
    const h = host();
    const ok = await confirm({
      title: `Reboot ${h}?`,
      tone: 'crit',
      confirmLabel: 'Reboot',
      requireTyped: h,
      body: `Reboots ${h} now. Expect ~2 minutes of downtime.`,
      danger: HOST_REBOOT_IMPACT[h],
    });
    if (!ok) return;
    busy = true;
    try {
      const d = await post<{ ok?: boolean }>(`/api/agents/${h}/reboot`, undefined, 20_000);
      if (d?.ok) {
        toast(`Reboot accepted — ${h} goes down in ~2s. Watching for it to return…`, 'warn');
        watchReturn();
        return;
      }
      busy = false;
      toast(`Reboot of ${h} did not take.`, 'crit', { sticky: true });
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        busy = false;
        toast(`Reboot of ${h} REFUSED by the ZFS guard: ${err.message}`, 'crit', { sticky: true });
      } else if (err.status === 404) {
        busy = false;
        toast(agentTooOld(h, 'reboots'), 'crit', { sticky: true });
      } else if (h === 'rpi') {
        toast('Connection dropped — expected when rebooting rpi, it serves this page. Watching for it to return…', 'warn');
        watchReturn();
      } else {
        busy = false;
        toast(`Reboot request to ${h} failed: ${err.message}`, 'crit', { sticky: true });
      }
    }
  }

  async function aptUpgrade() {
    const h = host();
    const ok = await confirm({
      title: `Apt upgrade on ${h}?`,
      tone: 'warn',
      confirmLabel: 'Upgrade now',
      body: `Runs the nightly homelab-autoupdate unit on ${h} now — the same code path that runs unattended at 02:00.`,
      note: "The live log tail is on this host's Cockpit card.",
    });
    if (!ok) return;
    busy = true;
    try {
      const d = await post<{ ok?: boolean; already_running?: boolean }>(`/api/agents/${h}/apt-upgrade`, undefined, 15_000);
      busy = false;
      if (!d?.ok) {
        toast(`Apt upgrade on ${h} failed to start.`, 'crit', { sticky: true });
        return;
      }
      toast(d.already_running
        ? `An apt run is already in progress on ${h} — follow it on Cockpit.`
        : `Apt upgrade started on ${h} — follow the log on Cockpit.`, 'ok');
    } catch (e) {
      busy = false;
      const err = e as ApiError;
      toast(err.status === 404 ? agentTooOld(h, 'apt upgrades') : `Apt upgrade on ${h} failed: ${err.message}`,
        'crit', { sticky: true });
    }
  }

  return {
    reboot,
    aptUpgrade,
    get termUrl() { return termUrlFor(host()); },
    get busy() { return busy; },
  };
}
