// Hand-tuned coordinates for the LAN map (viewBox 0 0 820 340). Five hosts do not
// need a force layout, and a fixed layout means the map reads the same every visit.
// Hosts the backend reports that are not listed here fall into the bottom row.
//
// Re-laid out 2026-09-10 to match what the homelab actually became. The old map put
// opti and rpi side by side as equals, which was true when rpi ran the app tier and
// opti was a NAS. It is not true now: opti carries storage, the control plane and all
// 14 application containers, while rpi is down to two and does one job.
//
// The hosts stay on ONE row and the meaning is carried by ORDER, not by tiering. A
// vertical arrangement was tried first — rpi under the gateway, opti below as the base
// — and it read well in the abstract but not on screen: this component hangs a host's
// text label below its node and its SPOF badge above, so stacking two hosts vertically
// collides one's badge with the other's label, and opti's own labels ran off the bottom.
//
// So: opti takes the CENTRE, directly beneath the gateway, because it is the hub almost
// everything depends on. rpi sits immediately beside it rather than at the far edge,
// close to the gateway it serves DNS for. The consumers (tux, noblenumbat) hold the
// outer positions and android floats off to the side, as an intermittent phone should.
// Reading left to right you get consumer, appliance, hub, consumer.
export const VIEW = { w: 820, h: 340 };

export interface Pt { x: number; y: number }

export const INTERNET: Pt = { x: 410, y: 30 };
export const GATEWAY: Pt = { x: 410, y: 104 };

const ROW_Y = 250;

export const HOST_POS: Record<string, Pt> = {
  tux: { x: 96, y: ROW_Y },
  // The DNS appliance, next to the gateway it answers for.
  rpi: { x: 268, y: ROW_Y },
  // The hub: centre of the row, directly under the gateway.
  opti: { x: 452, y: ROW_Y },
  noblenumbat: { x: 700, y: ROW_Y },
  android: { x: 690, y: 66 },
};

export function positionFor(name: string, index: number): Pt {
  return HOST_POS[name] ?? { x: 130 + (index % 4) * 190, y: ROW_Y };
}

// Container dots sit on an arc above the host node; `n` dots spread over ~120°.
export function arcDots(center: Pt, n: number, radius = 34): Pt[] {
  if (n <= 0) return [];
  const out: Pt[] = [];
  const span = Math.min(Math.PI * 0.9, 0.16 * n);
  const start = -Math.PI / 2 - span / 2;
  for (let i = 0; i < n; i++) {
    const a = n === 1 ? -Math.PI / 2 : start + (span * i) / (n - 1);
    out.push({ x: center.x + Math.cos(a) * radius, y: center.y + Math.sin(a) * radius });
  }
  return out;
}

// A dashed dependency arc from A to B, bowing below the host row so it never crosses
// a node or its label. Depth scales with the run: adjacent hosts get a shallow hop,
// tux-to-noblenumbat a deep one, so overlapping arcs stay individually traceable.
export function depPath(a: Pt, b: Pt): string {
  const mx = (a.x + b.x) / 2;
  const span = Math.abs(b.x - a.x);
  const my = Math.max(a.y, b.y) + 34 + Math.min(52, 16 + span * 0.08);
  return `M ${a.x} ${a.y + 34} Q ${mx} ${my} ${b.x} ${b.y + 34}`;
}
