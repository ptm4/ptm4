// Formatting helpers shared across pages/widgets (ports of the v1/v2 helpers).

export function relTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Age phrasing ("12h", "7d") for uptimes, where "12h ago" reads wrong.
export function durSince(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

// Seconds of uptime → "29d", "1d 8h", "3h", "12m".
export function fmtUptime(s: number | null | undefined): string {
  if (s == null) return '—';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d >= 2) return `${d}d`;
  if (d === 1) return `1d ${h}h`;
  if (h >= 1) return `${h}h`;
  return `${m}m`;
}

export function localeDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '—' : new Date(t).toLocaleString();
}

export function fmtBytesPerSec(bps: number | null | undefined): string {
  if (bps == null) return '—';
  if (bps < 1024) return `${Math.round(bps)} B/s`;
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
  return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`;
}

export function fmtKBps(bps: number | null | undefined): string {
  if (bps == null) return '—';
  const k = bps / 1024;
  return k < 1000 ? `${Math.round(k)}` : `${(k / 1024).toFixed(1)}M`;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function fmtPct(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${n.toFixed(digits)}%`;
}

export type Tone = 'ok' | 'warn' | 'crit' | '';

// Shared thresholds so a percentage means the same thing everywhere.
export function toneFor(p: number | null | undefined): Tone {
  if (p == null) return '';
  return p >= 90 ? 'crit' : p >= 75 ? 'warn' : 'ok';
}

// Severity strings from the various collectors → the three tones.
export function toneForSeverity(sev: string | null | undefined): Tone {
  const s = (sev || '').toLowerCase();
  if (s === 'critical' || s === 'crit' || s === 'high' || s === 'error') return 'crit';
  if (s === 'warn' || s === 'warning' || s === 'medium') return 'warn';
  if (s === 'ok' || s === 'info' || s === 'low') return 'ok';
  return '';
}

export function clockHM(d = new Date()): string {
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}
