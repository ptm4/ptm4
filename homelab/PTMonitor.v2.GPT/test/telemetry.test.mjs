import test from 'node:test';
import assert from 'node:assert/strict';
import { bytes, rate, temp, percent, severity, strongest, RollingHistory, chartSegments, sampleState, orderedDisks, sensorMatches } from '../src/telemetry.mjs';

test('missing and nonfinite telemetry stays unavailable while genuine zero is preserved', () => {
  for (const value of [null, undefined, NaN, Infinity]) { assert.equal(bytes(value), '—'); assert.equal(rate(value), '—'); assert.equal(temp(value), '—'); assert.equal(percent(value), '—'); }
  assert.equal(rate(0), '0 B/s'); assert.equal(percent(0), '0%'); assert.equal(bytes(32 * 1024 ** 3), '32.0 GiB'); assert.equal(bytes(.5), '1 B');
});
test('threshold severity handles missing sensors and warning/critical boundaries', () => {
  assert.equal(severity(null, 85, 95), 'unavailable'); assert.equal(severity(84.9, 85, 95), 'normal'); assert.equal(severity(85, 85, 95), 'warning'); assert.equal(severity(95, 85, 95), 'critical'); assert.equal(strongest('normal', 'critical'), 'critical');
});
test('history is bounded by elapsed time, rejects reordered snapshots and preserves null gaps', () => {
  const history = new RollingHistory();
  for (let second = 1; second <= 130; second++) history.push({ capturedAtMs: second * 1000, cpu: { usagePct: second % 100 }, gpu: { usagePct: second === 129 ? null : 0 } });
  assert.equal(history.samples.length, 60); assert.equal(history.samples[0].capturedAtMs, 71000);
  assert.equal(history.push({ capturedAtMs: 129000 }), false); assert.equal(history.push({ capturedAtMs: 130000 }), false);
  assert.equal(history.series('gpu').at(-2).value, null); assert.equal(history.series('gpu').at(-1).value, 0);
  history.push({ capturedAtMs: 220000 }); assert.equal(history.samples.length, 1);
});
test('missing network adapters are gaps, not zero-throughput traces', () => {
  const history = new RollingHistory(); history.push({ capturedAtMs: 1000, network: { available: false, rxBytesPerSec: 0 } }); assert.equal(history.series('down')[0].value, null);
});
test('tray resume restores native history without replacing newer live samples',()=>{
  const history=new RollingHistory();history.push({capturedAtMs:100000,cpu:{usagePct:42}});
  history.restore([{capturedAtMs:30000,cpuPct:1},{capturedAtMs:99000,cpuPct:3},{capturedAtMs:100000,cpuPct:4},{capturedAtMs:101000,cpuPct:5}],100000);
  assert.deepEqual(history.series('cpu').map((p)=>p.value),[3,42]);
});
test('charts preserve sixty-second time geometry and break across missing or delayed samples', () => {
  const segments = chartSegments([{ timestamp: 10000, value: 20 }, { timestamp: 11000, value: 30 }, { timestamp: 12000, value: null }, { timestamp: 13000, value: 40 }, { timestamp: 19000, value: 50 }], 20000);
  assert.deepEqual(segments.map((s) => s.length), [2, 1, 1]); assert.equal(segments[0][0].x, 1 - 10000 / 60000); assert.ok(segments.at(-1)[0].x < 1);
});
test('freshness turns stale even when no replacement snapshot arrives', () => {
  assert.equal(sampleState(null, 10000).state, 'waiting'); assert.equal(sampleState(10000, 13000).state, 'live'); assert.equal(sampleState(10000, 14000).label, '4s OLD');
});
test('priority volumes preserve native system/fullest ordering and sensor filter includes provenance', () => {
  const disks = [{ label: 'E:',usagePct:40 }, { label: 'V:',usagePct:93 }, { label: 'C:',usagePct:50 }];
  assert.deepEqual(orderedDisks(disks).map((d) => d.label), ['E:', 'V:', 'C:']); assert.notEqual(orderedDisks(disks),disks);
  assert.ok(sensorMatches({ name: 'Core', hardware: 'NVIDIA', sensorType: 'Temperature', id: '/gpu/0' }, 'nvidia'));
});
