// Layout for the topology diagram. Hand-tuned to this homelab rather than a generic
// graph layout: hosts are lanes, services stack inside them, the outside world sits
// above. Edges are routed so they never cut through a service card:
//   - neighbouring hosts: an S-curve across the gap between them
//   - same host: a bracket curve along the lane's left edge
//   - hosts further apart: up into a dedicated lane above the hosts, across, down
//   - to the outside world: up the gap beside the host, across a lane, into the side
//     of the external node
export interface Rect { x: number; y: number; w: number; h: number }
export interface LNode extends Rect { id: string; label: string; sub: string; kind: string; status: string; type: 'service' | 'external' | 'router'; host?: string; count?: number; detail?: string | null; resource?: string | null; href: string }
export interface LHost extends Rect { id: string; label: string; role: string | null; status: string; online: boolean | null; metrics: any; counts: any; state_text: string }
export interface LEdge { id: string; from: string; to: string; label: string; kind: string; status: string; d: string; mid: { x: number; y: number } }
export interface Layout { width: number; height: number; hosts: LHost[]; nodes: LNode[]; edges: LEdge[] }

const ORDER: Record<string, number> = { rpi: 0, opti: 1, noblenumbat: 2, android: 3 };
const WIDTH: Record<string, number> = { rpi: 230, opti: 300, noblenumbat: 300, android: 160 };
const GAP = 40;
const MARGIN = 30;
const HOST_TOP = 214;
export const HEADER = 80;
const PITCH = 56;
const NODE_H = 44;
const PAD = 14;
const EXT_Y = 22;
const EXT_H = 46;
const ROUTER_Y = 98;
const LANE = { up: 162, router: 178, dns: 196 };
// Same-host bracket curves run along this side of the lane — away from the busy gap
// that carries the storage/media curves between opti and noblenumbat.
const BRACKET: Record<string, 'left' | 'right'> = { noblenumbat: 'right' };
// Per-edge preference for which side of the host an upward edge leaves from.
const EXIT: Record<string, 'left' | 'right'> = { 'bots>discord': 'left', 'gluetun>proton': 'right', 'ntfy>internet': 'right' };

const cx = (r: Rect) => r.x + r.w / 2;
const cy = (r: Rect) => r.y + r.h / 2;

// Polyline → path with rounded corners.
function rounded(pts: [number, number][], r = 12): string {
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [x, y] = pts[i], [nx, ny] = pts[i + 1];
    const l1 = Math.hypot(x - px, y - py), l2 = Math.hypot(nx - x, ny - y);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const ax = x - ((x - px) / l1) * rr, ay = y - ((y - py) / l1) * rr;
    const bx = x + ((nx - x) / l2) * rr, by = y + ((ny - y) / l2) * rr;
    d += ` L${ax},${ay} Q${x},${y} ${bx},${by}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return `${d} L${lx},${ly}`;
}
function polyMid(pts: [number, number][]) {
  let best = 0, bi = 0;
  for (let i = 1; i < pts.length; i++) {
    const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (l > best) { best = l; bi = i; }
  }
  return { x: (pts[bi][0] + pts[bi - 1][0]) / 2, y: (pts[bi][1] + pts[bi - 1][1]) / 2 };
}
function curve(a: [number, number], b: [number, number], c1: [number, number], c2: [number, number]) {
  return {
    d: `M${a[0]},${a[1]} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${b[0]},${b[1]}`,
    mid: { x: (a[0] + 3 * c1[0] + 3 * c2[0] + b[0]) / 8, y: (a[1] + 3 * c1[1] + 3 * c2[1] + b[1]) / 8 },
  };
}

export function layoutTopology(t: any): Layout {
  const hostsIn = [...t.hosts].sort((a: any, b: any) => (ORDER[a.id] ?? 9) - (ORDER[b.id] ?? 9));
  const cols = new Map<string, { x: number; w: number; idx: number }>();
  let x = MARGIN;
  hostsIn.forEach((h: any, idx: number) => {
    const w = WIDTH[h.id] ?? 220;
    cols.set(h.id, { x, w, idx });
    x += w + GAP;
  });
  const width = x - GAP + MARGIN;

  const nodes: LNode[] = [];
  const hosts: LHost[] = hostsIn.map((h: any) => {
    const c = cols.get(h.id)!;
    const svcs = t.services.filter((s: any) => s.host === h.id);
    svcs.forEach((s: any, i: number) => {
      nodes.push({
        ...s, type: 'service', x: c.x + PAD, y: HOST_TOP + HEADER + 10 + i * PITCH, w: c.w - 2 * PAD, h: NODE_H,
        href: s.resource ? `/r/${s.resource}` : s.id === 'bots' ? '/resources?kind=bot' : `/r/${s.host}`,
      });
    });
    return {
      id: h.id, label: h.label, role: h.role, status: h.status, online: h.online, metrics: h.metrics,
      counts: h.counts, state_text: h.state_text,
      x: c.x, y: HOST_TOP, w: c.w, h: Math.max(118, HEADER + 10 + svcs.length * PITCH + 6),
    };
  });
  const height = Math.max(...hosts.map((h) => h.y + h.h)) + MARGIN;

  // Outside world + router, placed relative to the host lanes.
  const col = (id: string) => cols.get(id);
  const opti = col('opti'), nn = col('noblenumbat'), android = col('android');
  const gapCenter = opti && nn ? opti.x + opti.w + GAP / 2 : width / 2;
  const place: Record<string, { cx: number; w: number }> = {
    internet: { cx: gapCenter, w: 160 },
    discord: { cx: opti ? opti.x + opti.w * 0.25 : 200, w: 150 },
    proton: { cx: android ? android.x + android.w / 2 : width - 120, w: 170 },
  };
  for (const e of t.external) {
    const p = place[e.id] ?? { cx: width / 2, w: 150 };
    nodes.push({ ...e, type: 'external', status: 'ok', x: p.cx - p.w / 2, y: EXT_Y, w: p.w, h: EXT_H, href: '' });
  }
  nodes.push({ ...t.router, type: 'router', status: 'ok', x: gapCenter - 105, y: ROUTER_Y, w: 210, h: EXT_H, href: '' });

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const hostById = new Map(hosts.map((h) => [h.id, h]));
  const gutterUse = new Map<number, number>();
  const gutterX = (base: number) => {
    const n = gutterUse.get(base) ?? 0;
    gutterUse.set(base, n + 1);
    return base + [0, 12, -12, 24, -24][n % 5];
  };

  const edges: LEdge[] = [];
  for (const e of t.edges) {
    const key = `${e.from}>${e.to}`;
    const fromHost = e.from.startsWith('host:') ? hostById.get(e.from.slice(5)) : null;
    const toHost = e.to.startsWith('host:') ? hostById.get(e.to.slice(5)) : null;
    const a = fromHost ?? nodeById.get(e.from);
    const b = toHost ?? nodeById.get(e.to);
    if (!a || !b) continue;
    const aCol = fromHost ? cols.get(fromHost.id) : (a as LNode).host ? cols.get((a as LNode).host!) : undefined;
    const bCol = toHost ? cols.get(toHost.id) : (b as LNode).host ? cols.get((b as LNode).host!) : undefined;
    const headerMid = (h: Rect) => h.y + 36;
    let d = '', mid = { x: 0, y: 0 };

    if (!aCol && !bCol) {
      // external → router: straight down
      const pts: [number, number][] = [[cx(a), a.y + a.h], [cx(b), b.y]];
      d = rounded(pts); mid = polyMid(pts);
    } else if (!aCol && bCol) {
      // router → host: down to the router lane, across, down into the host's top
      const tx = toHost ? cx(b) - (toHost.w / 2 - 40) : cx(b);
      const pts: [number, number][] = [[cx(a), a.y + a.h], [cx(a), LANE.router], [tx, LANE.router], [tx, b.y]];
      d = rounded(pts); mid = polyMid(pts);
    } else if (aCol && !bCol) {
      // up to the outside world: leave via a gap beside the host, climb, enter from the side
      const riser = cx(a) < cx(b) ? b.x - 34 : b.x + b.w + 34;
      const side = EXIT[key] ?? (Math.abs(aCol.x - GAP / 2 - riser) < Math.abs(aCol.x + aCol.w + GAP / 2 - riser) ? 'left' : 'right');
      const sx = side === 'left' ? a.x : a.x + a.w;
      const gx = gutterX(side === 'left' ? aCol.x - GAP / 2 : aCol.x + aCol.w + GAP / 2);
      const enterX = riser < cx(b) ? b.x : b.x + b.w;
      const pts: [number, number][] = Math.abs(gx - riser) < 30
        ? [[sx, cy(a)], [gx, cy(a)], [gx, cy(b)], [enterX, cy(b)]]
        : [[sx, cy(a)], [gx, cy(a)], [gx, LANE.up], [riser, LANE.up], [riser, cy(b)], [enterX, cy(b)]];
      d = rounded(pts); mid = polyMid(pts);
    } else if (aCol === bCol) {
      // same host: bracket along one edge of the lane
      const hostId = (a as LNode).host ?? '';
      const r = BRACKET[hostId] === 'right'
        ? curve([a.x + a.w, cy(a)], [b.x + b.w, cy(b)], [a.x + a.w + 28, cy(a)], [b.x + b.w + 28, cy(b)])
        : curve([a.x, cy(a)], [b.x, cy(b)], [a.x - 28, cy(a)], [b.x - 28, cy(b)]);
      d = r.d; mid = r.mid;
    } else if (Math.abs(aCol!.idx - bCol!.idx) === 1) {
      // neighbouring hosts: S-curve across the gap between them
      const right = bCol!.idx > aCol!.idx;
      const ay = fromHost ? headerMid(a) : cy(a);
      const by = toHost ? headerMid(b) : cy(b);
      const ax = right ? a.x + a.w : a.x;
      const bx = right ? b.x : b.x + b.w;
      const k = (bx - ax) * 0.55;
      const r = curve([ax, ay], [bx, by], [ax + k, ay], [bx - k, by]);
      d = r.d; mid = r.mid;
    } else {
      // hosts further apart: up into the DNS lane, across, down
      const right = bCol!.idx > aCol!.idx;
      const sx = right ? a.x + a.w - 36 : a.x + 36;
      const tx = right ? b.x + 36 : b.x + b.w - 36;
      const pts: [number, number][] = [[sx, a.y], [sx, LANE.dns], [tx, LANE.dns], [tx, b.y]];
      d = rounded(pts); mid = polyMid(pts);
    }
    edges.push({ id: key, from: e.from, to: e.to, label: e.label, kind: e.kind, status: e.status, d, mid });
  }

  return { width, height, hosts, nodes, edges };
}
