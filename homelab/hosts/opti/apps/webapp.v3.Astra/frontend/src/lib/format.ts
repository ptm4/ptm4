// Formatting helpers shared across pages/widgets (ports of the v1 helpers).

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

export function localeDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '—' : new Date(t).toLocaleString();
}

export function fmtBytesPerSec(bps: number | null | undefined): string {
  if (bps == null) return '—';
  if (bps < 1024) return `${bps} B/s`;
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
  return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`;
}

// Shared thresholds so a percentage means the same thing everywhere.
export function toneFor(p: number | null | undefined): 'ok' | 'warn' | 'crit' | '' {
  if (p == null) return '';
  return p >= 90 ? 'crit' : p >= 75 ? 'warn' : 'ok';
}
