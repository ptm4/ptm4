<script lang="ts">
  // The LAN as a live map: internet → gateway → hosts, container dots on an arc
  // above each host, dashed dependency arcs, health halos, SPOF badges. Pure SVG —
  // data comes in as props so the same map serves the Topology page and the Home hero.
  import type { FleetHost, Dependency, HostTone } from '$lib/api/fleet';
  import { VIEW, INTERNET, GATEWAY, positionFor, arcDots, depPath, type Pt } from './layout';

  export interface HostView {
    host: FleetHost;
    tone: HostTone;
    stat: string;              // the small mono line under the name
    containers: { name: string; up: boolean; update: boolean }[];
  }

  let {
    hosts,
    depends = [],
    gateway,
    selected = null,
    onSelect,
    compact = false,
  }: {
    hosts: HostView[];
    depends?: Dependency[];
    gateway?: { label: string; ip: string } | null;
    selected?: string | null;
    onSelect?: (name: string | null) => void;
    /** hero mode: no legend, tighter labels */
    compact?: boolean;
  } = $props();

  let pos = $derived.by(() => {
    const m = new Map<string, Pt>();
    hosts.forEach((h, i) => m.set(h.host.name, positionFor(h.host.name, i)));
    return m;
  });
  let arcs = $derived(depends
    .filter((d) => pos.has(d.from) && pos.has(d.to))
    .map((d) => ({ ...d, d: depPath(pos.get(d.from)!, pos.get(d.to)!) })));

  const pick = (name: string) => onSelect?.(selected === name ? null : name);
</script>

<div class="map" class:compact>
  <svg viewBox="0 0 {VIEW.w} {VIEW.h}" role="img" aria-label="LAN topology map">
    <!-- links -->
    <line class="edge faded" x1={INTERNET.x} y1={INTERNET.y + 14} x2={GATEWAY.x} y2={GATEWAY.y - 16} />
    {#each hosts as h (h.host.name)}
      {@const p = pos.get(h.host.name)!}
      <line class="edge" class:faded={h.tone === 'off'} x1={GATEWAY.x} y1={GATEWAY.y + 14} x2={p.x} y2={p.y - 14} />
    {/each}
    <!-- dependency arcs -->
    {#each arcs as a (a.from + a.to)}
      <path class="dep" d={a.d}><title>{a.from} → {a.to}: {a.why}</title></path>
    {/each}

    <!-- internet + gateway -->
    <g class="node gw"><circle class="core" cx={INTERNET.x} cy={INTERNET.y} r="12" /><text class="cloudt" x={INTERNET.x} y={INTERNET.y - 16}>internet</text></g>
    <g class="node gw">
      <circle class="halo" cx={GATEWAY.x} cy={GATEWAY.y} r="19" /><circle class="core" cx={GATEWAY.x} cy={GATEWAY.y} r="14" />
      <text class="nlabel" x={GATEWAY.x} y={GATEWAY.y + 34}>{gateway?.label ?? 'gateway'}</text>
      <text class="nsub" x={GATEWAY.x} y={GATEWAY.y + 47}>gateway · {gateway?.ip ?? '.1'} · dhcp off</text>
    </g>

    <!-- hosts -->
    {#each hosts as h (h.host.name)}
      {@const p = pos.get(h.host.name)!}
      {@const dots = arcDots(p, Math.min(h.containers.length, 24))}
      {@const small = h.host.kind === 'phone' || h.host.kind === 'workstation'}
      <g class="node {h.tone}" class:sel={selected === h.host.name} class:small role="button" tabindex="0"
         onclick={() => pick(h.host.name)} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(h.host.name); } }}>
        <title>{h.host.label} · {h.host.role} · {h.host.ip}</title>
        {#each dots as d, i (i)}
          {@const c = h.containers[i]}
          <circle class="cdot" class:down={!c.up} class:update={c.update} cx={d.x} cy={d.y} r="2.2"><title>{c.name}{c.up ? '' : ' (down)'}{c.update ? ' · update' : ''}</title></circle>
        {/each}
        {#if selected === h.host.name}<circle class="selring" cx={p.x} cy={p.y} r={small ? 18 : 23} />{/if}
        <circle class="halo" cx={p.x} cy={p.y} r={small ? 14 : 18} />
        <circle class="core" cx={p.x} cy={p.y} r={small ? 10 : 13} />
        <text class="nlabel" class:dim={h.tone === 'off'} x={p.x} y={p.y + (small ? 27 : 35)}>{h.host.label}</text>
        <text class="nsub" x={p.x} y={p.y + (small ? 39 : 48)}>{h.host.role} · .{h.host.ip.split('.').pop()}</text>
        {#if h.stat && !compact}<text class="nstat" x={p.x} y={p.y + 62}>{h.stat}</text>{/if}
        {#if h.host.spof}<text class="spof" x={p.x} y={p.y - 30}>{h.host.spof.toUpperCase()} SPOF</text>{/if}
      </g>
    {/each}
  </svg>
  {#if !compact}
    <div class="legend">
      <span class="lg"><i></i> LAN link</span>
      <span class="lg"><i class="dep"></i> depends on</span>
      <span class="lg"><span class="t-ok">●</span> healthy</span>
      <span class="lg"><span class="t-warn">●</span> update pending</span>
      <span class="lg"><span class="t-crit">●</span> unreachable</span>
      <span class="lg faint">click a host · dots are containers</span>
    </div>
  {/if}
</div>

<style>
  .map { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); position: relative; overflow: hidden; }
  .map::before { content: ""; position: absolute; inset: 0; background: linear-gradient(var(--accent-dim) 1px, transparent 1px), linear-gradient(90deg, var(--accent-dim) 1px, transparent 1px); background-size: 32px 32px; opacity: .35; pointer-events: none; }
  .map svg { display: block; width: 100%; height: auto; position: relative; }
  .legend { position: absolute; left: 12px; bottom: 9px; display: flex; gap: 14px; font-size: 10.5px; color: var(--ink-3); flex-wrap: wrap; }
  .lg { display: flex; gap: 5px; align-items: center; }
  .lg i { width: 14px; height: 2px; background: var(--c-network); opacity: .6; }
  .lg i.dep { background: none; height: 0; border-top: 2px dashed var(--warn); opacity: .8; }

  .edge { stroke: var(--c-network); stroke-opacity: .35; stroke-width: 1.5; }
  .edge.faded { stroke-opacity: .15; }
  .dep { stroke: var(--warn); stroke-width: 1.2; stroke-dasharray: 4 4; opacity: .55; fill: none; }
  .node { cursor: pointer; outline: none; }
  .node circle.halo { fill: none; stroke-width: 6; opacity: .22; }
  .node circle.core { stroke-width: 1.5; fill: var(--bg-inset); transition: stroke .15s; }
  .node.ok circle.core, .node.ok circle.halo { stroke: var(--ok); }
  .node.warn circle.core, .node.warn circle.halo { stroke: var(--warn); }
  .node.crit circle.core, .node.crit circle.halo { stroke: var(--crit); }
  .node.off circle.core { stroke: var(--ink-3); stroke-dasharray: 2 2; }
  .node.off circle.halo { stroke: var(--ink-3); opacity: .12; }
  .node.gw circle.core, .node.gw circle.halo { stroke: var(--c-network); }
  .node:hover circle.halo, .node:focus-visible circle.halo { opacity: .45; }
  .selring { fill: none; stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 3 3; }
  .nlabel { fill: var(--ink); font: 600 13px var(--sans); text-anchor: middle; }
  .nlabel.dim { fill: var(--ink-2); }
  .small .nlabel { font-size: 11px; }
  .nsub { fill: var(--ink-3); font: 400 10px var(--sans); text-anchor: middle; }
  .nstat { fill: var(--ink-2); font: 400 10.5px var(--mono); text-anchor: middle; }
  .spof { fill: var(--warn); font: 700 9px var(--sans); text-anchor: middle; letter-spacing: .08em; }
  .cloudt { fill: var(--ink-2); font: 600 11px var(--sans); text-anchor: middle; }
  .cdot { fill: var(--ok); opacity: .55; }
  .cdot.update { fill: var(--warn); opacity: .9; }
  .cdot.down { fill: var(--crit); opacity: .95; }
</style>
