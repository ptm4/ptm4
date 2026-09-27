<script lang="ts">
  // The homelab as a live diagram. Layout: lib/topology-layout.ts. Data: /api/topology.
  // Links flow from source to target; a link turns red and stops when one end is down.
  // Hover (or focus) anything to light up what it connects to; click a card to open it.
  import {
    ShieldCheck, Send, HardDrive, LayoutDashboard, KeyRound, Inbox, Bot, Crosshair,
    NotebookPen, ScrollText, Clapperboard, Library, Download, Shield, BookOpen, Radio, Activity,
    BellRing, Container, Cpu, Globe, MessageSquare, Lock, Router, Server, Smartphone, Tags,
  } from '@lucide/svelte';
  import { layoutTopology, HEADER, type LEdge, type Layout } from '$lib/topology-layout';
  import { pct } from '$lib/format';

  let { topology }: { topology: any } = $props();

  const L: Layout = $derived(layoutTopology(topology));
  let hover = $state<string | null>(null);
  let showLabels = $state(false);

  const ICON: Record<string, any> = {
    pihole: ShieldCheck, 'dozzle-agent-rpi': Send, samba: HardDrive, webapp: LayoutDashboard,
    vault: KeyRound, seerr: Inbox, bots: Bot, hltv: Crosshair, notes: NotebookPen, dozzle: ScrollText,
    jellyfin: Clapperboard, arr: Library, downloaders: Download, gluetun: Shield, kavita: BookOpen,
    streams: Radio, kuma: Activity, ntfy: BellRing, portainer: Container, llama: Cpu,
    internet: Globe, discord: MessageSquare, proton: Lock, router: Router,
  };
  const KIND: Record<string, { color: string; label: string; dur: string }> = {
    network: { color: 'var(--chart-1)', label: 'Network', dur: '1.1s' },
    dns: { color: 'var(--chart-1)', label: 'DNS', dur: '0.8s' },
    storage: { color: 'var(--purple)', label: 'Storage', dur: '1.6s' },
    media: { color: 'var(--info)', label: 'Media', dur: '1.3s' },
    vpn: { color: 'var(--brand)', label: 'VPN', dur: '1s' },
    apps: { color: 'var(--ink-2)', label: 'Apps', dur: '1.4s' },
    monitor: { color: 'var(--ink-3)', label: 'Monitoring', dur: '2s' },
  };
  const ACCENT: Record<string, string> = {
    network: 'var(--chart-1)', storage: 'var(--purple)', media: 'var(--info)', apps: 'var(--brand)', infra: 'var(--ink-3)',
  };
  const dotColor = (s: string) => (s === 'crit' ? 'var(--crit)' : s === 'warn' ? 'var(--warn)' : s === 'unknown' || s === 'offline' ? 'transparent' : 'var(--ok)');

  // What lights up for the hovered thing: its edges and the nodes at their other ends.
  const related = $derived.by(() => {
    if (!hover) return null;
    const hostPrefix = hover.startsWith('host:') ? hover : null;
    const edges = L.edges.filter((e) =>
      e.id === hover || e.from === hover || e.to === hover
      || (hostPrefix && (e.from === hostPrefix || e.to === hostPrefix)),
    );
    const ids = new Set<string>([hover]);
    for (const e of edges) { ids.add(e.from); ids.add(e.to); }
    return { edges: new Set(edges.map((e) => e.id)), ids };
  });
  const dimNode = (id: string) => !!related && !related.ids.has(id);
  const dimEdge = (e: LEdge) => !!related && !related.edges.has(e.id);
  const labelShown = (e: LEdge) => showLabels || (!!related && related.edges.has(e.id));
  const labelW = (s: string) => s.length * 6.1 + 16;
  // SVG text never clips: cut to the pixels available (~5.9px per char at 11px).
  const fit = (s: string, px: number) => {
    const max = Math.max(4, Math.floor(px / 5.9));
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
  };
</script>

<div class="diagram panel">
  <div class="panel-head">
    <h2>Homelab map</h2>
    <div class="legend">
      {#each Object.entries(KIND).filter(([k]) => k !== 'network') as [k, v] (k)}
        <span><i style="background:{v.color}"></i>{v.label}</span>
      {/each}
      <span><i class="broken"></i>Broken</span>
    </div>
    <button class="btn ghost" aria-pressed={showLabels} onclick={() => (showLabels = !showLabels)}><Tags size={14} /> {showLabels ? 'Hide' : 'Show'} labels</button>
  </div>

  <div class="scroll">
    <svg viewBox="0 0 {L.width} {L.height}" role="img" aria-label="Homelab topology diagram" style="min-width: {Math.min(L.width, 940)}px">
      <defs>
        <pattern id="grid" width="22" height="22" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="var(--border-2)" opacity=".55" />
        </pattern>
      </defs>
      <rect width={L.width} height={L.height} fill="url(#grid)" />

      <!-- Host lanes -->
      {#each L.hosts as h (h.id)}
        {@const HostIcon = h.id === 'android' ? Smartphone : Server}
        <a href="/r/{h.id}" class="host" class:dim={dimNode(`host:${h.id}`)} class:crit={h.status === 'crit'} class:offline={h.status === 'offline'}
          onmouseenter={() => (hover = `host:${h.id}`)} onmouseleave={() => (hover = null)} onfocus={() => (hover = `host:${h.id}`)} onblur={() => (hover = null)}>
          <rect x={h.x} y={h.y} width={h.w} height={h.h} rx="14" class="lane" />
          <line x1={h.x + 12} x2={h.x + h.w - 12} y1={h.y + HEADER} y2={h.y + HEADER} class="sep" />
          <!-- row 1: name + status -->
          <HostIcon x={h.x + 14} y={h.y + 13} size={17} class="hico" />
          <text x={h.x + 38} y={h.y + 27} class="hname">{h.label}</text>
          <circle cx={h.x + h.w - 18} cy={h.y + 22} r="4.5" fill={dotColor(h.status)} stroke={h.status === 'offline' || h.status === 'unknown' ? 'var(--ink-3)' : 'none'} stroke-dasharray={h.status === 'unknown' ? '2 2' : undefined} />
          <!-- row 2: role + containers -->
          <text x={h.x + 16} y={h.y + 46} class="hrole">{h.role ?? ''}</text>
          {#if h.counts}
            <text x={h.x + h.w - 16} y={h.y + 46} text-anchor="end" class="hcount">{h.counts.running}/{h.counts.containers} running</text>
          {/if}
          <!-- row 3: live meters (or the state, for hosts without an agent) -->
          {#if h.metrics}
            {@const gw = Math.min(96, (h.w - 32 - 40) / 2)}
            {#each [['cpu', h.metrics.cpu_pct], ['mem', h.metrics.mem_pct]] as [lbl, v], i}
              {@const gx = h.x + 16 + i * (gw + 8)}
              <text x={gx} y={h.y + 67} class="mlabel">{lbl}</text>
              <rect x={gx + 24} y={h.y + 61} width={gw - 58} height="5" rx="2.5" class="mtrack" />
              <rect x={gx + 24} y={h.y + 61} width={Math.max(0, Math.min(1, ((v as number | null) ?? 0) / 100)) * (gw - 58)} height="5" rx="2.5" class="mfill" class:hi={((v as number | null) ?? 0) >= 85} />
              <text x={gx + gw - 4} y={h.y + 67} text-anchor="end" class="mval">{pct(v as number | null)}</text>
            {/each}
            {#if h.metrics.temp_c != null}
              <text x={h.x + h.w - 16} y={h.y + 67} text-anchor="end" class="mval" class:hot={h.metrics.temp_c >= 75}>{Math.round(h.metrics.temp_c)}°</text>
            {/if}
          {:else}
            <text x={h.x + 16} y={h.y + 67} class="hcount">{h.state_text}</text>
          {/if}
          <title>{h.label} — {h.state_text}</title>
        </a>
      {/each}

      <!-- Links -->
      {#each L.edges as e (e.id)}
        {@const k = KIND[e.kind] ?? KIND.apps}
        <g class="edge" class:dim={dimEdge(e)} class:hot={!!related && related.edges.has(e.id)} class:broken={e.status !== 'ok'}
          role="presentation" onmouseenter={() => (hover = e.id)} onmouseleave={() => (hover = null)}>
          <path d={e.d} class="hit" />
          <path d={e.d} class="base" style="stroke:{e.status !== 'ok' ? 'var(--crit)' : k.color}" />
          {#if e.status === 'ok'}
            <path d={e.d} class="flow" style="stroke:{k.color}; --dur:{k.dur}" />
          {/if}
          <title>{e.label}{e.status !== 'ok' ? ' — broken: one end is down' : ''}</title>
        </g>
      {/each}

      <!-- Outside world + router -->
      {#each L.nodes.filter((n) => n.type !== 'service') as n (n.id)}
        {@const Ic = ICON[n.id] ?? Globe}
        <g class="ext" class:router={n.type === 'router'} class:dim={dimNode(n.id)} role="presentation"
          onmouseenter={() => (hover = n.id)} onmouseleave={() => (hover = null)}>
          <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={n.type === 'router' ? 10 : 23} />
          <Ic x={n.x + 14} y={n.y + 14} size={17} class="eico" />
          <text x={n.x + 40} y={n.y + 20} class="nlabel">{n.label}</text>
          <text x={n.x + 40} y={n.y + 35} class="nsub">{n.sub}</text>
          <title>{n.label} — {n.sub}</title>
        </g>
      {/each}

      <!-- Services -->
      {#each L.nodes.filter((n) => n.type === 'service') as n (n.id)}
        {@const Ic = ICON[n.id] ?? Container}
        <a href={n.href} class="svc s-{n.status}" class:dim={dimNode(n.id)}
          onmouseenter={() => (hover = n.id)} onmouseleave={() => (hover = null)} onfocus={() => (hover = n.id)} onblur={() => (hover = null)}>
          <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="9" class="card" />
          <rect x={n.x} y={n.y + 9} width="3" height={n.h - 18} rx="1.5" fill={ACCENT[n.kind] ?? 'var(--ink-3)'} />
          {#if n.id === 'pertal'}
            <image href="/favicon.svg" x={n.x + 11} y={n.y + 11} width="21" height="21" />
          {:else}
            <Ic x={n.x + 12} y={n.y + 13} size={18} class="sico" />
          {/if}
          <text x={n.x + 40} y={n.y + 19} class="nlabel">{n.label}</text>
          <text x={n.x + 40} y={n.y + 34} class="nsub">{fit(n.detail ?? n.sub, n.w - 40 - ((n.count ?? 0) > 1 ? 44 : 26))}</text>
          {#if (n.count ?? 0) > 1}
            <text x={n.x + n.w - 26} y={n.y + 26} text-anchor="end" class="count">{n.count}</text>
          {/if}
          <circle cx={n.x + n.w - 13} cy={n.y + n.h / 2} r="4" fill={dotColor(n.status)} stroke={n.status === 'offline' || n.status === 'unknown' ? 'var(--ink-3)' : 'none'} />
          <title>{n.label}{n.detail ? ` — ${n.detail}` : n.sub ? ` — ${n.sub}` : ''}</title>
        </a>
      {/each}

      <!-- Labels on top of everything -->
      {#each L.edges.filter(labelShown) as e (e.id)}
        <g class="elabel" transform="translate({e.mid.x},{e.mid.y})">
          <rect x={-labelW(e.label) / 2} y="-10" width={labelW(e.label)} height="20" rx="10" class:bad={e.status !== 'ok'} />
          <text text-anchor="middle" y="4">{e.label}</text>
        </g>
      {/each}
    </svg>
  </div>
</div>

<style>
  .diagram { margin-top: var(--s3); overflow: hidden; }
  .panel-head { flex-wrap: wrap; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: var(--fs-xs); color: var(--ink-3); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 16px; height: 3px; border-radius: 2px; display: inline-block; }
  .legend i.broken { background: repeating-linear-gradient(90deg, var(--crit) 0 4px, transparent 4px 7px); }
  .scroll { overflow-x: auto; background: var(--bg-inset); }
  svg { display: block; width: 100%; height: auto; font-family: var(--sans); }

  .lane { fill: var(--surface); stroke: var(--border-2); stroke-width: 1; }
  .host.crit .lane { stroke: color-mix(in srgb, var(--crit) 55%, var(--border-2)); }
  .host.offline { opacity: .6; }
  .host.offline .lane { stroke-dasharray: 6 5; }
  .sep { stroke: var(--border); }
  .hname { fill: var(--ink); font-size: 15px; font-weight: 700; }
  .hrole { fill: var(--ink-3); font-size: 11px; }
  .hcount { fill: var(--ink-3); font-size: 11px; }
  .mlabel { fill: var(--ink-3); font: 10px var(--mono); text-transform: uppercase; }
  .mval { fill: var(--ink-2); font: 11px var(--mono); }
  .mval.hot { fill: var(--warn); }
  .mtrack { fill: var(--surface-3); }
  .mfill { fill: var(--chart-1); }
  .mfill.hi { fill: var(--warn); }
  :global(.hico) { color: var(--ink-2); }

  .ext rect { fill: var(--surface); stroke: var(--ink-3); stroke-dasharray: 4 4; stroke-width: 1; }
  .ext.router rect { stroke: var(--brand); stroke-dasharray: none; stroke-width: 1.4; }
  :global(.eico) { color: var(--ink-2); }
  .ext.router :global(.eico) { color: var(--brand); }

  .card { fill: var(--surface-2); stroke: var(--border-2); stroke-width: 1; transition: stroke .15s, fill .15s; }
  .svc:hover .card, .svc:focus .card { stroke: var(--accent); fill: var(--surface-3); }
  .svc.s-warn .card { stroke: var(--warn); }
  .svc.s-crit .card { stroke: var(--crit); stroke-width: 1.5; }
  .svc.s-crit .nsub, .svc.s-warn .nsub { fill: var(--ink-2); }
  .svc.s-offline, .svc.s-unknown { opacity: .65; }
  .svc.s-offline .card, .svc.s-unknown .card { stroke-dasharray: 4 3; }
  :global(.sico) { color: var(--ink-2); }
  .nlabel { fill: var(--ink); font-size: 13px; font-weight: 600; }
  .nsub { fill: var(--ink-3); font-size: 11px; }
  .count { fill: var(--ink-3); font: 11px var(--mono); }
  .svc, .host { cursor: pointer; outline: none; }

  .edge .hit { fill: none; stroke: transparent; stroke-width: 14; }
  .edge .base { fill: none; stroke-width: 1.6; opacity: .45; transition: opacity .15s; }
  .edge .flow { fill: none; stroke-width: 3.2; stroke-linecap: round; stroke-dasharray: 0.1 13; opacity: .9; }
  .edge.hot .base { opacity: .95; stroke-width: 2.2; }
  .edge.broken .base { stroke-dasharray: 6 5; opacity: .9; stroke-width: 2; }
  @media (prefers-reduced-motion: no-preference) {
    .edge .flow { animation: flow var(--dur, 1.2s) linear infinite; }
  }
  @keyframes flow { to { stroke-dashoffset: -13.1; } }

  /* Beats the offline/unknown opacity on purpose: dimmed means "not part of this". */
  svg .dim { opacity: .18 !important; transition: opacity .15s; }
  .edge.dim .flow { opacity: .15; }

  .elabel rect { fill: var(--surface); stroke: var(--border-2); }
  .elabel rect.bad { stroke: var(--crit); }
  .elabel text { fill: var(--ink-2); font-size: 11px; }
</style>
