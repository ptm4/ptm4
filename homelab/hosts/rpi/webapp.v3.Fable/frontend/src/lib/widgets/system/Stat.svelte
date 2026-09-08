<script lang="ts">
  // Stat counter — a single big number that links out to the page it summarises.
  // Direct port of v2's StatWidget (widgets/system.tsx): monitors up, reports
  // healthy, agent drift, or pending image updates. Each metric reads its own
  // query and degrades to a dash when that query hasn't loaded (or errored) yet —
  // the tile never throws, it just shows less.
  import { opt, type WidgetProps } from '$lib/widgets/sdk';
  import { useAgents, useContainers, useRunners, useUptime } from '$lib/api/queries';

  let { options = {} }: WidgetProps = $props();

  const STAT_DEFS: Record<string, { label: string; sub: string; to: string }> = {
    monitors: { label: 'Monitors', sub: 'Uptime Kuma', to: '/cockpit' },
    reports: { label: 'Reports', sub: 'runner status', to: '/reports' },
    drift: { label: 'Agent drift', sub: 'undescribed vs missing', to: '/agents/' },
    updates: { label: 'Updates', sub: 'container images', to: '/updates' },
  };

  let metric = $derived(opt(options, 'metric', 'monitors'));
  let def = $derived(STAT_DEFS[metric] ?? STAT_DEFS.monitors);

  const uptime = useUptime();
  const runners = useRunners();
  const agents = useAgents();
  const containers = useContainers();

  let stat = $derived.by(() => {
    let value = '—';
    let tone: 'ok' | 'warn' | 'crit' | undefined;
    let sub = def.sub;

    if (metric === 'monitors' && uptime.data?.ok) {
      value = `${uptime.data.up}/${uptime.data.total}`;
      tone = uptime.data.down ? 'crit' : 'ok';
      const bad = uptime.data.monitors.filter((m) => m.status !== 'up').map((m) => m.name);
      sub = bad.length ? `down: ${bad.join(', ')}` : 'all up';
    } else if (metric === 'reports' && runners.data) {
      const bad = runners.data.runners.filter((r) => r.status === 'critical' || r.status === 'warn').length;
      value = `${runners.data.runners.length - bad}/${runners.data.runners.length}`;
      tone = bad ? 'warn' : 'ok';
      sub = bad ? `${bad} need attention` : 'all healthy';
    } else if (metric === 'drift' && agents.data) {
      const n = agents.data.hosts.reduce((acc, h) => acc + (h.drift_count || 0), 0);
      value = String(n);
      tone = n ? 'warn' : 'ok';
    } else if (metric === 'updates' && containers.data) {
      const n = containers.data.hosts.reduce(
        (acc, h) => acc + h.containers.filter((c) => c.update_available).length, 0);
      value = String(n);
      tone = n ? 'warn' : 'ok';
      sub = n ? 'images out of date' : 'all current';
    }
    return { value, tone, sub };
  });
</script>

<a class="w-card glass w-link" href={def.to}>
  <div class="w-body stat">
    <div class="w-title">{def.label}</div>
    <div class="big-metric" data-s={stat.tone}>{stat.value}</div>
    <div class="t-dim stat-sub">{stat.sub}</div>
  </div>
</a>
