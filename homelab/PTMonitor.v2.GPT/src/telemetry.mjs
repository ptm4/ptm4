// Shared presentation rules; null is unavailable, never an invented zero.
export const finite = (value) => typeof value === 'number' && Number.isFinite(value);
export const clamp = (value, min = 0, max = 100) => finite(value) ? Math.max(min, Math.min(max, value)) : null;
export const fixed = (value, digits = 0) => finite(value) ? value.toFixed(digits) : '—';
export const percent = (value, digits = 0) => finite(value) ? `${fixed(value, digits)}%` : '—';
export const temp = (value) => finite(value) ? `${fixed(value)}°C` : '—';
export const unit = (value, suffix, digits = 0) => finite(value) ? `${fixed(value, digits)} ${suffix}` : '—';
export function bytes(value, digits = 1) {
  if (!finite(value) || value < 0) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const power = value >= 1 ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0;
  return `${(value / 1024 ** power).toFixed(power === 0 ? 0 : digits)} ${units[power]}`;
}
export const rate = (value) => finite(value) ? `${bytes(value)}/s` : '—';
export function uptime(seconds) {
  if (!finite(seconds)) return '—';
  const total = Math.max(0, seconds);
  return `${Math.floor(total / 86400) ? `${Math.floor(total / 86400)}d ` : ''}${Math.floor(total % 86400 / 3600)}h ${Math.floor(total % 3600 / 60)}m`;
}
export function severity(value, warn, critical) {
  if (!finite(value)) return 'unavailable';
  if (finite(critical) && value >= critical) return 'critical';
  if (finite(warn) && value >= warn) return 'warning';
  return 'normal';
}
export const strongest = (...levels) => ['critical', 'warning', 'normal', 'unavailable'].find((level) => levels.includes(level)) || 'normal';
export const THRESHOLDS = [
  ['CPU load %', 'cpuWarnPct', 'cpuCriticalPct', 100],
  ['Memory used %', 'ramWarnPct', 'ramCriticalPct', 100],
  ['GPU load %', 'gpuWarnPct', 'gpuCriticalPct', 100],
  ['Disk used %', 'diskWarnPct', 'diskCriticalPct', 100],
  ['CPU temp °C', 'cpuTempWarnC', 'cpuTempCriticalC', 150],
  ['GPU temp °C', 'gpuTempWarnC', 'gpuTempCriticalC', 150],
  ['Storage temp °C', 'diskTempWarnC', 'diskTempCriticalC', 150],
];
export class RollingHistory {
  constructor(windowMs = 60_000) { this.windowMs = windowMs; this.samples = []; }
  push(snapshot) {
    const timestamp = snapshot?.capturedAtMs;
    if (!finite(timestamp) || timestamp <= (this.samples.at(-1)?.capturedAtMs ?? 0)) return false;
    this.samples.push({ capturedAtMs: timestamp, cpu: snapshot.cpu?.usagePct, memory: snapshot.memory?.usagePct, gpu: snapshot.gpu?.usagePct, down: snapshot.network?.available === false ? null : snapshot.network?.rxBytesPerSec, up: snapshot.network?.available === false ? null : snapshot.network?.txBytesPerSec, cpuTemp: snapshot.cpu?.tempC, gpuTemp: snapshot.gpu?.tempC });
    this.samples = this.samples.filter((sample) => sample.capturedAtMs > timestamp - this.windowMs).slice(-120);
    return true;
  }
  series(key, now = this.samples.at(-1)?.capturedAtMs || Date.now()) {
    return this.samples.filter((sample) => sample.capturedAtMs >= now - this.windowMs).map((sample) => ({ timestamp: sample.capturedAtMs, value: finite(sample[key]) ? sample[key] : null }));
  }
  restore(points, now = Date.now()) {
    const restored=points.map((point)=>({capturedAtMs:point.capturedAtMs,cpu:point.cpuPct,memory:point.memoryPct,gpu:point.gpuPct,down:point.rxBytesPerSec,up:point.txBytesPerSec,cpuTemp:point.cpuTempC,gpuTemp:point.gpuTempC}));
    this.samples=[...new Map([...restored,...this.samples].map((point)=>[point.capturedAtMs,point])).values()].filter((point)=>finite(point.capturedAtMs)&&point.capturedAtMs>now-this.windowMs&&point.capturedAtMs<=now).sort((a,b)=>a.capturedAtMs-b.capturedAtMs).slice(-120);
  }
}
export function chartSegments(points, now, windowMs = 60_000, maxGapMs = 2500) {
  const segments = []; let current = []; let previous = null;
  for (const point of points) {
    if (point.timestamp < now - windowMs) continue;
    if (point.value == null || (previous !== null && point.timestamp - previous > maxGapMs)) { if (current.length) segments.push(current); current = []; }
    if (finite(point.value)) current.push({ x: Math.max(0, Math.min(1, 1 - (now - point.timestamp) / windowMs)), value: point.value });
    previous = point.timestamp;
  }
  if (current.length) segments.push(current);
  return segments;
}
export function sensorMatches(sensor, query) { return `${sensor.name} ${sensor.hardware} ${sensor.sensorType} ${sensor.hardwareType} ${sensor.id}`.toLowerCase().includes(query.toLowerCase().trim()); }
// The native collector owns system-volume identity and priority. Do not hide a
// critical disk by re-sorting its list alphabetically in the presentation layer.
export function orderedDisks(disks) { return [...disks]; }
export function sampleState(capturedAtMs, now = Date.now()) {
  if (!finite(capturedAtMs) || capturedAtMs <= 0) return { state: 'waiting', label: 'WAIT', ageMs: null };
  const ageMs = Math.max(0, now - capturedAtMs);
  return ageMs > 3500 ? { state: 'stale', label: `${Math.floor(ageMs / 1000)}s OLD`, ageMs } : { state: 'live', label: 'LIVE', ageMs };
}
