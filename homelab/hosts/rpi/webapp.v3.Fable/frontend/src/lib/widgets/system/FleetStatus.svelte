<script lang="ts">
  // Ported from webapp.v2.legacy/frontend/src/widgets/system.tsx: FleetStatusWidget
  // (the v1 ribbon, as a widget). One-line rollup: worst reporting runner status,
  // uptime monitors, reachable agents, and per-runner freshness.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, Pill } from '$lib/widgets/kit';
  import { useRunners, useAgents, useUptime } from '$lib/api/queries';
  import { relTime } from '$lib/format';

  let { options: _options = {} }: WidgetProps = $props();

  const runners = useRunners();
  const agents = useAgents();
  const uptime = useUptime();

  const RANK: Record<string, number> = { critical: 0, warn: 1, ok: 2 };

  // Only runners that have actually reported drive the fleet pill: a manual or
  // never-run runner sits at "unknown" forever, and treating that as critical
  // painted a red warning over a healthy fleet in v1.
  let reporting = $derived(
    (runners.data?.runners ?? []).filter((r) => r.run_at && r.status && r.status !== 'unknown'),
  );
  let worst = $derived(
    reporting.reduce((w, r) => ((RANK[r.status] ?? 1) < (RANK[w] ?? 2) ? r.status : w), 'ok'),
  );
  let reach = $derived((agents.data?.hosts ?? []).filter((h) => h.reachable).length);
  let ku = $derived(uptime.data);
</script>

<WidgetFrame title="Fleet">
  <div class="fleet-row">
    <Pill tone={worst === 'ok' ? 'ok' : worst === 'warn' ? 'warn' : 'crit'}>
      {worst === 'ok' ? '✓ fleet ok' : `! ${worst}`}
    </Pill>
    {#if ku?.ok}
      <Pill tone={ku.down ? 'crit' : ku.pending ? 'warn' : 'ok'}>{ku.up}/{ku.total} monitors</Pill>
    {/if}
    <Pill>{reach}/{agents.data?.hosts.length ?? 3} agents</Pill>
  </div>
  <div class="fleet-fresh">
    {reporting.map((r) => `${r.label.split(' ')[0].toLowerCase()} ${relTime(r.run_at)}`).join(' · ')}
  </div>
</WidgetFrame>
