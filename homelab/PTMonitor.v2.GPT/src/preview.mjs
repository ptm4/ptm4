// Explicit opt-in design fixture. Never selected inside the native application.
export const previewSettings = {
  version: 2, expanded: false, opacity: 1, backgroundOpacity: .95,
  startup: false, startHidden: false, clickThrough: false, toastAlerts: false, advancedSensors: false, selectedAdapter: null,
  thresholds: { cpuWarnPct: 85, cpuCriticalPct: 95, ramWarnPct: 85, ramCriticalPct: 95, gpuWarnPct: 90, gpuCriticalPct: 98, diskWarnPct: 80, diskCriticalPct: 90, cpuTempWarnC: 85, cpuTempCriticalC: 95, gpuTempWarnC: 82, gpuTempCriticalC: 90, diskTempWarnC: 60, diskTempCriticalC: 70 },
};
const gib = 1024 ** 3;
function sensor(id, hardware, hardwareType, name, sensorType, unit, value) { return { id, hardware, hardwareType, name, sensorType, unit, value, min: value * .85, max: value * 1.08 }; }
export function previewSnapshot(timestamp = Date.now(), tick = 60, scenario = '') {
  const wave = (speed, spread, base) => Math.max(0, base + Math.sin(tick / speed) * spread + Math.sin(tick * .8) * spread * .18);
  const cpuUsage = wave(5, 8, 22), gpuUsage = wave(7, 13, 41), cpuTemp = wave(9, 3, 58), gpuTemp = wave(11, 2, 54);
  const sensors = [
    sensor('/cpu/0/temperature/0', 'AMD Ryzen 7 5800X', 'Cpu', 'CPU Package', 'Temperature', '°C', cpuTemp),
    sensor('/cpu/0/clock/0', 'AMD Ryzen 7 5800X', 'Cpu', 'Core #1', 'Clock', 'MHz', 4550),
    sensor('/cpu/0/power/0', 'AMD Ryzen 7 5800X', 'Cpu', 'Package', 'Power', 'W', 68),
    sensor('/gpu-nvidia/0/temperature/0', 'NVIDIA GeForce RTX 4070 Ti', 'GpuNvidia', 'GPU Core', 'Temperature', '°C', gpuTemp),
    sensor('/gpu-nvidia/0/temperature/1', 'NVIDIA GeForce RTX 4070 Ti', 'GpuNvidia', 'GPU Hot Spot', 'Temperature', '°C', gpuTemp + 12),
    sensor('/gpu-nvidia/0/fan/0', 'NVIDIA GeForce RTX 4070 Ti', 'GpuNvidia', 'GPU Fan 1', 'Fan', 'RPM', 1150),
    sensor('/gpu-nvidia/0/power/0', 'NVIDIA GeForce RTX 4070 Ti', 'GpuNvidia', 'GPU Package', 'Power', 'W', 132),
    sensor('/storage/0/temperature/0', 'Samsung SSD 990 PRO 2TB', 'Storage', 'Composite', 'Temperature', '°C', 42),
    sensor('/lpc/nct6798/temperature/0', 'ASUS ROG STRIX B550-F', 'Motherboard', 'Motherboard', 'Temperature', '°C', 38),
    sensor('/lpc/nct6798/fan/0', 'ASUS ROG STRIX B550-F', 'Motherboard', 'CPU Fan', 'Fan', 'RPM', 980),
  ];
  const snapshot = {
    sequence: tick + 1, capturedAtMs: timestamp, sampleDurationMs: 14,
    cpu: { name: 'AMD Ryzen 7 5800X', logicalCores: 16, usagePct: cpuUsage, tempC: cpuTemp, clockMhz: 4550, powerW: 68 },
    memory: { usagePct: 47, usedBytes: 15.04 * gib, totalBytes: 32 * gib },
    gpu: { name: 'NVIDIA GeForce RTX 4070 Ti', usagePct: gpuUsage, tempC: gpuTemp, hotspotC: gpuTemp + 12, clockMhz: 2610, powerW: 132, vramUsedMb: 4870, vramTotalMb: 12282, source: 'sensor-host' },
    disks: [{ id: 'C:\\', label: 'C:', usagePct: 62, usedBytes: 1154 * gib, totalBytes: 1862 * gib, tempC: null }, { id: 'E:\\', label: 'E:', usagePct: 38, usedBytes: 708 * gib, totalBytes: 1862 * gib, tempC: null }, { id: 'P:\\', label: 'P:', usagePct: 24, usedBytes: 447 * gib, totalBytes: 1862 * gib, tempC: null }],
    network: { adapter: 'Ethernet', available: true, rxBytesPerSec: wave(7, 800000, 2400000), txBytesPerSec: wave(5, 25000, 152000), availableAdapters: ['Ethernet', 'Wi-Fi', 'WireGuard Tunnel'] },
    diskIo: { readBytesPerSec: 4700000, writeBytesPerSec: 1600000 }, uptimeSecs: 2 * 86400 + 7 * 3600 + 18 * 60,
    topCpuProcesses: [{ name: 'msedge.exe', pid: '17432', cpuPct: 7.2, memoryBytes: 890000000 }, { name: 'Code.exe', pid: '5304', cpuPct: 4.6, memoryBytes: 530000000 }, { name: 'dwm.exe', pid: '2908', cpuPct: 1.7, memoryBytes: 181000000 }, { name: 'PTMonitor v2.exe', pid: '2044', cpuPct: .3, memoryBytes: 63000000 }],
    topMemoryProcesses: [{ name: 'msedge.exe', pid: '17432', cpuPct: 7.2, memoryBytes: 890000000 }, { name: 'Code.exe', pid: '5304', cpuPct: 4.6, memoryBytes: 530000000 }, { name: 'Photoshop.exe', pid: '9432', cpuPct: .2, memoryBytes: 320000000 }],
    sensors, fans: sensors.filter((s) => s.sensorType === 'Fan'), storageTemps: sensors.filter((s) => s.hardwareType === 'Storage'),
    sensorStatus: { state: 'online', detail: null, lastSeenMs: timestamp }, alerts: [],
    alertHistory: [{ key: 'cpu_temp', level: 'resolved', message: 'CPU temperature recovered to 76°C', capturedAtMs: timestamp - 100000 }, { key: 'cpu_temp', level: 'warning', message: 'CPU temperature reached 87°C', capturedAtMs: timestamp - 130000 }],
  };
  if (scenario === 'unavailable') { snapshot.cpu.tempC = null; snapshot.gpu = { usagePct: null, tempC: null, source: 'unavailable' }; snapshot.diskIo = { readBytesPerSec: null, writeBytesPerSec: null }; snapshot.sensors = []; snapshot.fans = []; snapshot.storageTemps = []; snapshot.sensorStatus = { state: 'unavailable', detail: 'Additional hardware sensors require supported hardware and access.', lastSeenMs: null }; snapshot.network.available = false; }
  if (scenario === 'long') { snapshot.network.adapter = 'Ethernet — Intel(R) Ethernet Controller (3) I225-V'; snapshot.disks.push({ id: 'V:\\', label: 'V:', usagePct: 93, usedBytes: 1800 * gib, totalBytes: 1862 * gib }); snapshot.alerts = [{ key: 'disk_V', level: 'critical', message: 'V: capacity 93% — critically low free space', capturedAtMs: timestamp }]; snapshot.sensors.push(sensor('/malicious', '<img src=x onerror=alert(1)>', 'Motherboard', '<script>doNotExecute()</script>', 'Temperature', '°C', 44)); }
  snapshot.disks.sort((a,b)=>Number(b.label==='C:')-Number(a.label==='C:')||b.usagePct-a.usagePct);
  return snapshot;
}
export function createPreview() {
  const params = new URLSearchParams(location.search), scenario = params.get('scenario') || '';
  let config = { ...previewSettings, thresholds: { ...previewSettings.thresholds }, expanded: params.has('expanded') }, tick = 60;
  const listeners = new Map();
  const emit = (name, payload) => { for (const callback of listeners.get(name) || []) callback({ payload }); };
  const started = Date.now();
  let snapshot = previewSnapshot(started, tick, scenario);
  const timer = setInterval(() => { if (params.has('paused')) return; snapshot = previewSnapshot(Date.now(), ++tick, scenario); emit('ptmonitor://snapshot', snapshot); }, 1000);
  const inventory = { hostname: 'STUDIO · DESIGN PREVIEW', osName: 'Windows 11 Pro', cpuName: snapshot.cpu.name, logicalCores: 16, totalMemoryBytes: 32 * gib, gpuNames: [snapshot.gpu.name], volumes: snapshot.disks, adapters: snapshot.network.availableAdapters, sensorCount: snapshot.sensors.length };
  return {
    listen: async (name, callback) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(callback); return () => listeners.get(name).delete(callback); },
    invoke: async (command, args = {}) => {
      if (command === 'get_snapshot') return snapshot;
      if (command === 'get_inventory') return inventory;
      if (command === 'get_settings') return config;
      if (command === 'get_history') return Array.from({ length: 59 }, (_, index) => { const sample = previewSnapshot(started - (59 - index) * 1000, index + 1, scenario); return { capturedAtMs: sample.capturedAtMs, cpuPct: sample.cpu.usagePct, memoryPct: sample.memory.usagePct, gpuPct: sample.gpu.usagePct, rxBytesPerSec: sample.network.available ? sample.network.rxBytesPerSec : null, txBytesPerSec: sample.network.available ? sample.network.txBytesPerSec : null, cpuTempC: sample.cpu.tempC, gpuTempC: sample.gpu.tempC }; });
      if (command === 'get_diagnostics') return { collectorState: 'DESIGN PREVIEW — simulated data', ticks: tick, sampleDurationMs: 14, lastError: null, sensorDetail: 'No workstation data is collected by this preview.' };
      if (command === 'update_settings') { config = { ...config, ...args.patch }; emit('ptmonitor://settings', config); return config; }
      if (command === 'snap_to_current_monitor') return;
      throw new Error('This is a design preview. Use the Windows application for this action.');
    },
    window: { hide: async () => { throw new Error('Design preview stays visible. Hide to tray works in the Windows app.'); }, startDragging: async () => {} },
    dispose: () => clearInterval(timer),
  };
}
