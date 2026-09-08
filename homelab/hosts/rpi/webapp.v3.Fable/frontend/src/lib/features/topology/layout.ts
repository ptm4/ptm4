// Hand-tuned coordinates for the LAN map (viewBox 0 0 820 320). Five hosts do not
// need a force layout, and a fixed layout means the map reads the same every visit.
// Hosts the backend reports that are not listed here fall into the bottom row.
export const VIEW = { w: 820, h: 320 };

export interface Pt { x: number; y: number }

export const INTERNET: Pt = { x: 410, y: 32 };
export const GATEWAY: Pt = { x: 410, y: 116 };

export const HOST_POS: Record<string, Pt> = {
  tux: { x: 110, y: 242 },
  opti: { x: 300, y: 242 },
  rpi: { x: 520, y: 242 },
  noblenumbat: { x: 720, y: 242 },
  android: { x: 650, y: 76 },
};

export function positionFor(name: string, index: number): Pt {
  return HOST_POS[name] ?? { x: 110 + (index % 4) * 200, y: 242 };
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

// A dashed dependency arc from A to B, bowing below the host row.
export function depPath(a: Pt, b: Pt): string {
  const mx = (a.x + b.x) / 2;
  const my = Math.max(a.y, b.y) + 58;
  return `M ${a.x} ${a.y + 34} Q ${mx} ${my} ${b.x} ${b.y + 34}`;
}
