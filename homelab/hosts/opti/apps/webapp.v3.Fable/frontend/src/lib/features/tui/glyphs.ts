// btop's vocabulary, as strings. Everything the monitor draws is text: no SVG, no
// canvas. That is the whole point — a terminal renders graphs out of block glyphs,
// so the page does too, and it stays crisp at any zoom without a single path.

/** Eighth-blocks, low → high. index 0 is a space so a null sample leaves a gap. */
const BLOCKS = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

/** Braille dot patterns for a denser two-row-per-cell graph (btop's default). */
// Unicode braille dot bits:  1:0x01 4:0x08
//                             2:0x02 5:0x10
//                             3:0x04 6:0x20
//                             7:0x40 8:0x80
// Each character cell is two sample columns of four levels, bottom → top.
const BRAILLE_BASE = 0x2800;
const BRAILLE_L = [0x40, 0x04, 0x02, 0x01];   // dots 7,3,2,1
const BRAILLE_R = [0x80, 0x20, 0x10, 0x08];   // dots 8,6,5,4

/**
 * A block-glyph sparkline. `values` may contain nulls (a gap in the ring buffer);
 * those render as spaces, never as an interpolated line — an absent sample is not
 * a zero. Scale is min..max across the present values unless a domain is given.
 */
export function spark(values: (number | null | undefined)[], width = 24, domain?: [number, number]): string {
  if (!values.length) return ' '.repeat(width);
  // Take the last `width` samples; bucket-average if there are more than fit.
  const step = values.length / width;
  const cells: (number | null)[] = [];
  for (let i = 0; i < width; i++) {
    const from = Math.floor(i * step);
    const to = Math.max(from + 1, Math.floor((i + 1) * step));
    const slice = values.slice(from, to).filter((v): v is number => v != null && Number.isFinite(v));
    cells.push(slice.length ? slice.reduce((a, b) => a + b, 0) / slice.length : null);
  }
  const present = cells.filter((v): v is number => v != null);
  if (!present.length) return ' '.repeat(width);
  const lo = domain ? domain[0] : Math.min(...present);
  const hi = domain ? domain[1] : Math.max(...present);
  const span = hi - lo || 1;
  return cells.map((v) => {
    if (v == null) return ' ';
    const t = Math.max(0, Math.min(1, (v - lo) / span));
    return BLOCKS[Math.max(1, Math.round(t * 8))];
  }).join('');
}

/** Denser sparkline: 2 samples per character cell via braille. */
export function brailleSpark(values: (number | null | undefined)[], width = 24, domain?: [number, number]): string {
  const need = width * 2;
  const step = Math.max(1, values.length / need);
  const cells: (number | null)[] = [];
  for (let i = 0; i < need; i++) {
    const from = Math.floor(i * step);
    const to = Math.max(from + 1, Math.floor((i + 1) * step));
    const slice = values.slice(from, to).filter((v): v is number => v != null && Number.isFinite(v));
    cells.push(slice.length ? slice.reduce((a, b) => a + b, 0) / slice.length : null);
  }
  const present = cells.filter((v): v is number => v != null);
  if (!present.length) return ' '.repeat(width);
  const lo = domain ? domain[0] : Math.min(...present);
  const hi = domain ? domain[1] : Math.max(...present);
  const span = hi - lo || 1;
  const level = (v: number | null) => (v == null ? -1 : Math.max(0, Math.min(3, Math.round(((v - lo) / span) * 3))));
  let out = '';
  for (let i = 0; i < need; i += 2) {
    const a = level(cells[i]);
    const b = level(cells[i + 1]);
    if (a < 0 && b < 0) { out += ' '; continue; }
    let code = BRAILLE_BASE;
    if (a >= 0) for (let d = 0; d <= a; d++) code |= BRAILLE_L[d];
    if (b >= 0) for (let d = 0; d <= b; d++) code |= BRAILLE_R[d];
    out += String.fromCharCode(code);
  }
  return out;
}

/** A filled meter: `████████░░░░░░░░`. pct is 0-100; null renders as dashes. */
export function meter(pct: number | null | undefined, width = 20): string {
  if (pct == null || !Number.isFinite(pct)) return '─'.repeat(width);
  const filled = Math.max(0, Math.min(width, Math.round((pct / 100) * width)));
  return '█'.repeat(filled) + '░'.repeat(width - filled);
}

/** Right-align a number in a fixed column so rows stay in a grid. */
export const pad = (s: string | number, n: number) => String(s).padStart(n, ' ');
export const padEnd = (s: string | number, n: number) => String(s).padEnd(n, ' ');

/** The tone a percentage earns. Shared with the rest of the app's thresholds. */
/** btop's load ramp, by thirds (Peter's call 2026-09-10).
 *
 * Deliberately NOT the ok/warn/crit ramp above. That one answers "is something
 * wrong?" and stays grey until it is. This one answers "how hard is this box
 * working?", which is a magnitude, not a verdict — a CPU at 50% is not a problem,
 * it is just busier than one at 5%, and the colour should say so without crying
 * wolf. So it walks cool → warm: blue (low) → purple (moderate) → red (>2/3),
 * mapped onto --accent / --brand / --crit in the Monitor's stylesheet.
 *
 * The split is exact thirds of the scale. `mod` and `high` are overridable for
 * gauges that are not percentages: temperature passes (60, 72) because thirds of
 * a degree axis would paint an idle Pi purple, which tells you nothing.
 */
export type Load = 'low' | 'mod' | 'high' | 'dim';
export function loadTone(
  value: number | null | undefined,
  mod = 100 / 3,
  high = 200 / 3,
): Load {
  if (value == null || !Number.isFinite(value)) return 'dim';
  return value >= high ? 'high' : value >= mod ? 'mod' : 'low';
}

export function toneFor(pct: number | null | undefined): 'ok' | 'warn' | 'crit' | 'dim' {
  if (pct == null || !Number.isFinite(pct)) return 'dim';
  return pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : 'ok';
}

/** Bytes/sec → a fixed-width human string, so the column never jitters. */
export function rate(bps: number | null | undefined): string {
  if (bps == null || !Number.isFinite(bps)) return '   —  ';
  if (bps < 1024) return pad(Math.round(bps), 4) + ' B';
  if (bps < 1024 * 1024) return pad((bps / 1024).toFixed(0), 4) + ' K';
  if (bps < 1024 * 1024 * 1024) return pad((bps / 1048576).toFixed(1), 4) + ' M';
  return pad((bps / 1073741824).toFixed(1), 4) + ' G';
}

/** Seconds → btop-ish compact uptime: 29d 4h / 3h 12m / 12m. */
export function uptime(s: number | null | undefined): string {
  if (s == null) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/**
 * A domain that keeps an idle series readable without misrepresenting it.
 * btop pins CPU to 0-100 and an idle box draws a flat line at the floor; here the
 * scale follows the data instead, and the caller prints the peak next to the graph
 * so the axis is always stated rather than implied.
 */
export function autoDomain(values: (number | null | undefined)[], floor = 0, minSpan = 5): [number, number] {
  const present = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (!present.length) return [floor, floor + minSpan];
  const hi = Math.max(...present);
  const lo = Math.min(floor, Math.min(...present));
  return [lo, Math.max(hi, lo + minSpan)];
}

/** The peak of a series, for the "pk NN" label beside an auto-scaled graph. */
export function peak(values: (number | null | undefined)[]): number | null {
  const present = values.filter((v): v is number => v != null && Number.isFinite(v));
  return present.length ? Math.max(...present) : null;
}
