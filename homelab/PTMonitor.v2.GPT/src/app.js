import { finite, clamp, fixed, percent, temp, unit, bytes, rate, uptime, severity, strongest, THRESHOLDS, RollingHistory, chartSegments, sensorMatches, orderedDisks, sampleState } from './telemetry.mjs';

const $ = (id) => document.getElementById(id);
const history = new RollingHistory();
const native = window.__TAURI__;
const demo = !native && new URLSearchParams(location.search).has('demo');
let bridge = native ? { invoke: native.core.invoke, listen: native.event.listen, window: native.window.getCurrentWindow() } : null;
if (demo) bridge = (await import('./preview.mjs')).createPreview();
const invoke = (...args) => bridge ? bridge.invoke(...args) : Promise.reject(new Error('Open PTMonitor from the Windows application. For a labeled browser preview, add ?demo to the URL.'));
const listen = (...args) => bridge.listen(...args);
let settings = null, latest = null, inventory = null, activeTab = 'overview', diagnostics = null;
let inventoryPending = false;
let saveQueue = Promise.resolve(), settingsRevision = 0;
const unlisten = [];
const charts = new Map();
const metricNodes = new Map();
const listNodes = new Map();

function el(tag, className = '', text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function put(node, text) { const value = String(text ?? '—'); if (node.textContent !== value) node.textContent = value; }
function text(id, value) { put($(id), value); }
function showFailure(error) { text('notice-text', String(error?.message || error)); $('notice').hidden = false; }
function action(callback) { return async (event) => { try { await callback(event); } catch (error) { showFailure(error); } }; }
function nodeList(target, rows, keyOf, create, update, empty = 'No readings available') {
  const container = $(target);
  if (!listNodes.has(target)) listNodes.set(target, new Map());
  const cache = listNodes.get(target), keys = new Set();
  for (const [index, row] of rows.entries()) {
    const key = String(keyOf(row)); keys.add(key);
    if (!cache.has(key)) cache.set(key, create(row));
    const node = cache.get(key); update(node, row);
    if (container.children[index] !== node) container.insertBefore(node, container.children[index] || null);
  }
  for (const [key, node] of cache) if (!keys.has(key)) { node.remove(); cache.delete(key); }
  let blank = container.querySelector(':scope > .empty');
  if (!rows.length) { if (!blank) { blank = el('p', 'empty'); container.append(blank); } put(blank, empty); } else blank?.remove();
}

function createMetrics() {
  for (const [key, name] of [['cpu', 'CPU'], ['memory', 'RAM'], ['gpu', 'GPU']]) {
    const row = el('article', `metric-row ${key}`), visual = el('div', 'metric-visual');
    const canvas = el('canvas'); canvas.setAttribute('aria-label', `${name} utilization over the last 60 seconds`);
    const meter = el('div', 'meter'), fill = el('div', 'meter-fill'); meter.append(fill); visual.append(canvas, meter);
    const readout = el('div', 'metric-readout'), value = el('strong', '', '—'), sub = el('small', '', 'Waiting…'); readout.append(value, sub);
    row.append(el('span', 'metric-label', name), visual, readout); $('core-metrics').append(row);
    metricNodes.set(key, { row, canvas, fill, value, sub });
  }
  for (const [key, label] of [['cpu', 'CPU'], ['memory', 'MEMORY'], ['gpu', 'GPU'], ['network', 'NETWORK']]) {
    const node = el('article', `chart-card ${key}`), heading = el('header'), group = el('div'), value = el('strong', '', '—'), sub = el('small', '', 'Waiting…');
    group.append(el('h2', '', label), sub); heading.append(group, value);
    const canvas = el('canvas'); canvas.setAttribute('aria-label', `${label} history for the last sixty seconds`);
    const axis = el('div', 'chart-axis'), scale = el('span', '', key === 'network' ? 'AUTO SCALE' : '0–100%'); axis.append(el('span', '', '−60s'), scale, el('span', '', 'now'));
    node.append(heading, canvas, axis); $('chart-grid').append(node); charts.set(key, { node, canvas, value, sub, scale });
  }
}
createMetrics();

function drawChart(canvas, key, color, { secondary = null, grid = false, scale = 100 } = {}) {
  if (!canvas.offsetWidth) return;
  const now = Math.max(latest?.capturedAtMs || 0, Date.now()), width = canvas.clientWidth, height = canvas.clientHeight, dpr = Math.min(3, window.devicePixelRatio || 1);
  const pixelWidth = Math.round(width * dpr), pixelHeight = Math.round(height * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) { canvas.width = pixelWidth; canvas.height = pixelHeight; }
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
  if (grid) { ctx.lineWidth = .5; ctx.strokeStyle = 'rgba(177,199,227,.14)'; for (const fraction of [.25, .5, .75]) { ctx.beginPath(); ctx.moveTo(0, height * fraction); ctx.lineTo(width, height * fraction); ctx.stroke(); } }
  const trace = (seriesKey, stroke, fill) => {
    const segments = chartSegments(history.series(seriesKey, now), now);
    for (const segment of segments) {
      const points = segment.map((point) => [1 + point.x * (width - 2), height - 3 - Math.max(0, Math.min(1, point.value / scale)) * (height - 6)]);
      if (!points.length) continue;
      if (fill && points.length > 1) {
        const gradient = ctx.createLinearGradient(0, 0, 0, height); gradient.addColorStop(0, `${stroke}24`); gradient.addColorStop(1, `${stroke}00`);
        ctx.beginPath(); ctx.moveTo(points[0][0], height); points.forEach(([x, y]) => ctx.lineTo(x, y)); ctx.lineTo(points.at(-1)[0], height); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
      }
      ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.lineWidth = grid ? 1.6 : 1.3; ctx.lineJoin = 'round'; ctx.strokeStyle = stroke; ctx.stroke();
      const [x, y] = points.at(-1); ctx.beginPath(); ctx.arc(x, y, grid ? 2 : 1.4, 0, Math.PI * 2); ctx.fillStyle = stroke; ctx.fill();
    }
  };
  trace(key, color, true); if (secondary) trace(secondary, '#59d3b1', false);
}
function threshold(kind, value) {
  const t = settings?.thresholds || {};
  const prefix = { cpu: 'cpu', memory: 'ram', gpu: 'gpu', disk: 'disk', cpuTemp: 'cpuTemp', gpuTemp: 'gpuTemp', diskTemp: 'diskTemp' }[kind];
  const suffix = kind.endsWith('Temp') ? 'C' : 'Pct';
  return severity(value, t[`${prefix}Warn${suffix}`], t[`${prefix}Critical${suffix}`]);
}
function renderCompact(snapshot) {
  const { cpu, memory, gpu, network } = snapshot;
  for (const [key, metric, color] of [['cpu', cpu, '#73b7fa'], ['memory', memory, '#59d3b1'], ['gpu', gpu, '#b1a0ff']]) {
    const nodes = metricNodes.get(key), thermal = key !== 'memory' ? threshold(`${key}Temp`, metric.tempC) : 'normal';
    put(nodes.value, percent(metric.usagePct)); nodes.fill.style.width = `${clamp(metric.usagePct) ?? 0}%`;
    nodes.row.className = `metric-row ${key} ${strongest(threshold(key, metric.usagePct), thermal)}`;
    if (key === 'memory') { put(nodes.sub, `${bytes(memory.usedBytes).replace(' GiB', '')} / ${bytes(memory.totalBytes).replace('GiB', 'G')}`); nodes.sub.className = ''; }
    else { put(nodes.sub, finite(metric.tempC) ? temp(metric.tempC) : 'temp unavailable'); nodes.sub.className = finite(metric.tempC) ? `temperature ${thermal}` : 'missing'; }
    nodes.row.title = key === 'memory' ? `${bytes(memory.usedBytes)} used of ${bytes(memory.totalBytes)}` : `${key === 'cpu' ? cpu.name || 'CPU' : gpu.name || 'GPU'} · ${temp(metric.tempC)} · ${unit(metric.clockMhz, 'MHz')} · ${unit(metric.powerW, 'W')}`;
    drawChart(nodes.canvas, key, color);
  }
  const disks = orderedDisks(snapshot.disks || []);
  text('storage-count', disks.length > 3 ? `3 OF ${disks.length} VOLUMES` : 'USED CAPACITY');
  nodeList('disk-list', disks.slice(0, 3), (disk) => disk.id, () => {
    const row = el('div', 'disk-row'), meter = el('div', 'disk-meter'), detail = el('div','disk-subline');
    meter.append(el('i')); detail.append(el('span'),el('span')); row.append(el('strong'), meter, el('span', 'disk-readout'),detail); return row;
  }, (row, disk) => {
    row.className = `disk-row ${strongest(threshold('disk', disk.usagePct),threshold('diskTemp',disk.tempC))}`; put(row.children[0], disk.label); row.children[1].firstChild.style.width = `${clamp(disk.usagePct) ?? 0}%`; put(row.children[2], percent(disk.usagePct));
    put(row.children[3].children[0],`${bytes(disk.totalBytes-disk.usedBytes)} free`);
    put(row.children[3].children[1],finite(disk.tempC)?temp(disk.tempC):'— °C');
    row.children[3].children[1].className=threshold('diskTemp',disk.tempC);
    row.children[3].children[1].title=finite(disk.tempC)?'Temperature of the underlying physical disk(s)':'Disk temperature unavailable at this access level or on this hardware';
    row.title = `${disk.label}: ${bytes(disk.totalBytes - disk.usedBytes)} free of ${bytes(disk.totalBytes)}${finite(disk.tempC) ? ` · ${temp(disk.tempC)}` : ''}`;
  }, 'No eligible volumes');
  text('adapter-name', network.adapter || 'No adapter'); $('adapter-name').title = `${network.adapter || 'No adapter'}${network.available === false ? ' · disconnected' : ''}`;
  text('net-down', rate(network.available === false ? null : network.rxBytesPerSec)); text('net-up', rate(network.available === false ? null : network.txBytesPerSec));
  $('net-down').title = unit(network.available === false ? null : network.rxBytesPerSec * 8 / 1e6, 'Mbps', 2); $('net-up').title = unit(network.available === false ? null : network.txBytesPerSec * 8 / 1e6, 'Mbps', 2);
}
function vitals(target, entries) {
  nodeList(target, entries, (entry) => entry[0], () => { const node = el('article', 'vital'); node.append(el('span'), el('strong'), el('small')); return node; }, (node, [label, value, sub]) => { put(node.children[0], label); put(node.children[1], value); put(node.children[2], sub || ''); node.children[2].hidden = !sub; });
}
function sensorDetail(snapshot) {
  const status = snapshot.sensorStatus || {};
  return `${status.state === 'online' ? `${snapshot.sensors?.length || 0} live hardware sensors` : `Hardware sensors: ${status.state || 'starting'}`}${status.detail ? ` · ${status.detail}` : ''}`;
}
function renderOverview(snapshot) {
  const { cpu, memory, gpu, network, diskIo } = snapshot;
  text('hardware-summary', [cpu.name || inventory?.cpuName, cpu.logicalCores ? `${cpu.logicalCores} threads` : '', gpu.name || inventory?.gpuNames?.[0]].filter(Boolean).join(' · ') || 'Hardware identity unavailable');
  for (const [key, metric, color] of [['cpu', cpu, '#73b7fa'], ['memory', memory, '#59d3b1'], ['gpu', gpu, '#b1a0ff']]) {
    const chart = charts.get(key); put(chart.value, percent(metric.usagePct));
    put(chart.sub, key === 'memory' ? `${bytes(memory.usedBytes)} / ${bytes(memory.totalBytes)}` : `${temp(metric.tempC)} · ${unit(metric.powerW, 'W')}`);
    drawChart(chart.canvas, key, color, { grid: true });
  }
  const netChart = charts.get('network');
  const scale = Math.max(1024, ...history.series('down').map((point) => point.value || 0), ...history.series('up').map((point) => point.value || 0)) * 1.1;
  put(netChart.value, rate(network.available === false ? null : network.rxBytesPerSec));
  netChart.value.style.fontSize = '16px'; put(netChart.sub, `↓ receive · ↑ ${rate(network.available === false ? null : network.txBytesPerSec)}`); put(netChart.scale, `MAX ${rate(scale)}`);
  drawChart(netChart.canvas, 'down', '#73b7fa', { secondary: 'up', grid: true, scale });
  vitals('hardware-vitals', [
    ['CPU PACKAGE', temp(cpu.tempC), unit(cpu.powerW, 'W')], ['CPU CLOCK', unit(cpu.clockMhz, 'MHz'), cpu.clockSource === 'sensor-host' ? 'Mean of core sensors' : 'OS-reported clock'],
    ['GPU CORE', temp(gpu.tempC), `Hotspot ${temp(gpu.hotspotC)}`], ['GPU CLOCK', unit(gpu.clockMhz, 'MHz'), unit(gpu.powerW, 'W')],
    ['GPU MEMORY', finite(gpu.vramUsedMb) ? bytes(gpu.vramUsedMb * 1024 ** 2) : '—', finite(gpu.vramTotalMb) ? `of ${bytes(gpu.vramTotalMb * 1024 ** 2)}` : 'Capacity unavailable'],
    ['FANS', snapshot.fans?.length ? unit(snapshot.fans[0].value, 'RPM') : '—', snapshot.fans?.length ? `${snapshot.fans.length} sensor${snapshot.fans.length === 1 ? '' : 's'} · see Sensors` : 'Sensor unavailable'],
  ]);
  text('sensor-capability', sensorDetail(snapshot));
  nodeList('all-disks', orderedDisks(snapshot.disks || []), (disk) => disk.id, () => { const node = el('article', 'volume'), heading = el('div', 'volume-heading'), meter = el('div', 'disk-meter'); heading.append(el('strong'), el('span')); meter.append(el('i')); node.append(heading, meter, el('small')); return node; }, (node, disk) => {
    node.className = `volume ${strongest(threshold('disk', disk.usagePct),threshold('diskTemp',disk.tempC))}`; put(node.children[0].children[0], disk.label); put(node.children[0].children[1], `${bytes(disk.totalBytes - disk.usedBytes)} free · ${percent(disk.usagePct)}`); node.children[1].firstChild.style.width = `${clamp(disk.usagePct) ?? 0}%`;
    put(node.children[2], `${bytes(disk.usedBytes)} / ${bytes(disk.totalBytes)}${finite(disk.tempC) ? ` · ${temp(disk.tempC)}` : ''}`);
  }, 'No eligible volumes');
  text('details-adapter', `${network.adapter || 'No adapter'}${network.available === false ? ' · disconnected' : ''}`);
  const adapter=network.details;
  text('adapter-details',adapter?`${adapter.description || network.adapter} · ${adapter.receiveLinkSpeedBps ? unit(adapter.receiveLinkSpeedBps/1e6,'Mbps')+' receive link' : 'Link speed unavailable'} · ${adapter.transmitLinkSpeedBps ? unit(adapter.transmitLinkSpeedBps/1e6,'Mbps')+' transmit link' : ''} · MAC ${adapter.macAddress || 'unavailable'} · Adapter totals ↓ ${bytes(adapter.receivedBytes)} / ↑ ${bytes(adapter.transmittedBytes)}`:'Adapter details unavailable');
  vitals('io-vitals', [['RECEIVE', rate(network.available === false ? null : network.rxBytesPerSec)], ['TRANSMIT', rate(network.available === false ? null : network.txBytesPerSec)], ['DISK READ', rate(diskIo?.readBytesPerSec)], ['DISK WRITE', rate(diskIo?.writeBytesPerSec)], ...((snapshot.storageTemps || []).slice(0, 2).map((sensor) => [sensor.hardware, temp(sensor.value), 'Physical drive temperature']))]);
}
function renderSensors(snapshot) {
  text('sensor-status', `${sensorDetail(snapshot)}. Unavailable values are shown as —. Temperatures are Celsius. Min/max are supplied by the hardware collector for this session.`);
  const query = $('sensor-search').value;
  const sensors = (snapshot.sensors || []).filter((sensor) => sensorMatches(sensor, query)).sort((a, b) => a.hardware.localeCompare(b.hardware) || a.sensorType.localeCompare(b.sensorType) || a.name.localeCompare(b.name));
  nodeList('sensor-list', sensors, (sensor) => sensor.id, () => {
    const node = el('article', 'sensor'), label = el('div', 'sensor-label'), reading = el('div', 'sensor-reading'); label.append(el('strong'), el('small'), el('small')); reading.append(el('strong'), el('small'), el('small', 'provenance')); node.append(label, reading); return node;
  }, (node, sensor) => {
    const label = node.children[0], reading = node.children[1]; put(label.children[0], sensor.name); put(label.children[1], `${sensor.hardware} · ${sensor.sensorType}`); put(label.children[2], sensor.id);
    const digits = ['Voltage', 'Power', 'Data', 'SmallData'].includes(sensor.sensorType) ? 1 : 0;
    put(reading.children[0], unit(sensor.value, sensor.unit, digits)); put(reading.children[1], `${fixed(sensor.min, digits)} / ${fixed(sensor.max, digits)}`); put(reading.children[2], sensor.source || 'Libre Hardware Monitor');
  }, query ? 'No sensors match this filter.' : snapshot.sensorStatus?.detail || 'No hardware sensors available. Core CPU, RAM and network monitoring continue.');
}
function renderActivity(snapshot) {
  for (const [target, entries, cpu] of [['top-cpu', snapshot.topCpuProcesses || [], true], ['top-memory', snapshot.topMemoryProcesses || [], false]]) {
    nodeList(target, entries, (entry) => entry.pid, () => { const node = el('div', 'process'), label = el('div'); label.append(el('span'), el('small')); node.append(label, el('strong')); return node; }, (node, process) => { put(node.children[0].children[0], process.name); node.children[0].title = process.name; put(node.children[0].children[1], `PID ${process.pid}`); put(node.children[1], cpu ? percent(process.cpuPct, 1) : bytes(process.memoryBytes)); });
  }
  nodeList('alert-list', snapshot.alertHistory || snapshot.alerts || [], (entry) => `${entry.key}:${entry.level}:${entry.capturedAtMs || 0}`, () => { const node = el('article', 'alert-row'), body = el('div'); body.append(el('p'), el('small')); node.append(el('time'), body); return node; }, (node, alert) => {
    node.className = `alert-row ${['critical', 'resolved'].includes(alert.level) ? alert.level : 'warning'}`; put(node.children[0], alert.capturedAtMs ? new Date(alert.capturedAtMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'NOW'); put(node.children[1].children[0], alert.message); put(node.children[1].children[1], alert.level === 'unavailable' ? 'Reading lost · recovery not confirmed' : alert.level === 'resolved' ? 'Recovered' : alert.level === 'critical' ? 'Critical threshold' : 'Warning threshold');
  }, 'No alerts this session. Thresholds are configurable in Settings.');
}
function renderActive() {
  if (document.hidden || !latest || !settings?.expanded || $('settings-panel').hidden === false) return;
  if (activeTab === 'overview') renderOverview(latest); else if (activeTab === 'sensors') renderSensors(latest); else renderActivity(latest);
}
function renderFreshness() {
  if (document.hidden) return;
  const state = sampleState(latest?.capturedAtMs);
  $('widget').dataset.stale = String(state.state === 'stale'); text('sample-age', demo && state.state === 'live' ? 'DEMO' : state.label);
  const alert = latest?.alerts?.find((entry) => entry.level === 'critical') || latest?.alerts?.[0];
  const status = latest?.sensorStatus?.state;
  const message = state.state === 'stale' ? 'Updates paused · last values retained' : state.state === 'waiting' ? 'Connecting to workstation…' : alert ? alert.message : ['online', 'limited','partial'].includes(status) ? (status !== 'online' ? 'Live · limited hardware access' : 'Workstation telemetry online') : 'Live · hardware sensors unavailable';
  text('health-copy', message); $('health-copy').title = state.state === 'live' && !alert ? sensorDetail(latest) : message;
  $('health-dot').className = `status-dot ${state.state === 'stale' ? 'stale' : alert?.level || ''}`;
}
function acceptSnapshot(snapshot) {
  if (!snapshot || snapshot.sequence === 0 || (latest && snapshot.capturedAtMs <= latest.capturedAtMs)) return;
  latest = snapshot; history.push(snapshot);
  if (!inventory?.hostname && !inventoryPending) {
    inventoryPending=true;
    invoke('get_inventory').then((value)=>{inventory=value;text('host-name',value.hostname || 'YOUR WORKSTATION');}).catch(showFailure).finally(()=>{inventoryPending=false;});
  }
  if (document.hidden) return;
  text('uptime', `UPTIME ${uptime(snapshot.uptimeSecs)}`); text('sensor-count', snapshot.sensors?.length || 0); text('alert-count', snapshot.alerts?.length || 0);
  if (!settings?.expanded && $('settings-panel').hidden) renderCompact(snapshot); renderActive(); renderFreshness();
  if (!$('settings-panel').hidden) syncAdapters(snapshot.network?.availableAdapters || []);
}
function syncAdapters(adapters) {
  const select = $('set-adapter'), names = [...new Set([...adapters, ...(settings?.selectedAdapter ? [settings.selectedAdapter] : [])])].sort();
  const signature = JSON.stringify(names);
  if (select.dataset.signature !== signature) {
    select.dataset.signature = signature; select.replaceChildren(el('option', '', 'Auto · most active adapter')); select.firstChild.value = '';
    for (const name of names) { const option = el('option', '', name); option.value = name; select.append(option); }
  }
  if (document.activeElement !== select) select.value = settings?.selectedAdapter || '';
}
function syncThresholds() {
  const thresholds = settings?.thresholds || {};
  for (const [label, warn, critical, max] of THRESHOLDS) {
    if (!finite(thresholds[warn]) || !finite(thresholds[critical])) continue;
    let row = $(`threshold-${warn}`);
    if (!row) {
      row = el('div', 'threshold-row'); row.id = `threshold-${warn}`; row.append(el('span', '', label));
      for (const key of [warn, critical]) {
        const input = el('input'); input.type = 'number'; input.min = '1'; input.max = String(max); input.step = '1'; input.id = `threshold-${key}-input`; input.setAttribute('aria-label', `${label} ${key === warn ? 'warning' : 'critical'} threshold`);
        input.addEventListener('change', action(async () => {
          const value = input.valueAsNumber;
          if (!finite(value) || value < 1 || value > max) { input.value = String(settings.thresholds[key]); throw new Error(`${label}: enter a value between 1 and ${max}.`); }
          const next = { ...settings.thresholds, [key]: value };
          if (next[warn] >= next[critical]) { input.value = String(settings.thresholds[key]); throw new Error(`${label}: warning must be lower than critical.`); }
          await persist({ thresholds: next });
        })); row.append(input);
      }
      $('threshold-controls').append(row);
    }
    for (const key of [warn, critical]) { const input = $(`threshold-${key}-input`); if (document.activeElement !== input) input.value = String(thresholds[key]); }
  }
}
function applySettings(next) {
  settings = next; document.documentElement.dataset.expanded = String(Boolean(next.expanded)); $('details').hidden = !next.expanded;
  document.documentElement.style.setProperty('--widget-opacity', next.opacity ?? 1); document.documentElement.style.setProperty('--background-opacity', next.backgroundOpacity ?? .9);
  text('btn-expand', next.expanded ? '↙' : '↗'); $('btn-expand').setAttribute('aria-label', next.expanded ? 'Collapse to compact monitor' : 'Expand workstation details'); $('btn-expand').title = next.expanded ? 'Compact monitor' : 'Workstation details'; text('footer-detail', next.expanded ? 'Compact monitor ↙' : 'Workstation details ↗');
  for (const [id, key] of [['set-startup', 'startup'], ['set-start-hidden', 'startHidden'], ['set-click-through', 'clickThrough'], ['set-toasts', 'toastAlerts'], ['set-advanced', 'advancedSensors']]) $(id).checked = Boolean(next[key]);
  for (const [id, key] of [['opacity', 'opacity'], ['background-opacity', 'backgroundOpacity']]) { if (document.activeElement !== $(`set-${id}`)) $(`set-${id}`).value = String(Math.round((next[key] ?? .9) * 100)); text(`${id}-value`, `${Math.round((next[key] ?? .9) * 100)}%`); }
  syncThresholds(); syncAdapters(latest?.network?.availableAdapters || []);
  requestAnimationFrame(() => { if (latest) { if (!next.expanded) renderCompact(latest); else renderActive(); } });
}
function persist(patch) {
  saveQueue = saveQueue.catch(() => {}).then(async () => {
    const revision = ++settingsRevision;
    try { const next = await invoke('update_settings', { patch }); if (revision === settingsRevision) applySettings(next); return next; }
    catch (error) { if (settings) applySettings(settings); throw new Error(`Could not save setting: ${error?.message || error}`); }
  });
  return saveQueue;
}
async function openSettings() { $('settings-panel').hidden = false; $('btn-settings-close').focus(); applySettings(await invoke('get_settings')); }
function closeSettings() { $('settings-panel').hidden = true; $('btn-settings').focus(); renderActive(); }
function selectTab(tab) {
  activeTab = tab;
  for (const button of document.querySelectorAll('[data-tab]')) { const active = button.dataset.tab === tab; button.classList.toggle('active', active); if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); }
  for (const panel of document.querySelectorAll('.tab-panel')) panel.hidden = panel.id !== `tab-${tab}`;
  $('detail-scroll').scrollTop = 0; renderActive(); if (tab === 'activity') refreshDiagnostics().catch(showFailure);
}
async function refreshDiagnostics() { diagnostics = await invoke('get_diagnostics'); text('diagnostics', JSON.stringify(diagnostics, null, 2)); }

$('btn-settings').addEventListener('click', action(openSettings)); $('btn-settings-close').addEventListener('click', closeSettings);
for (const id of ['btn-expand', 'footer-detail']) $(id).addEventListener('click', action(async () => { if (settings) await persist({ expanded: !settings.expanded }); }));
$('btn-hide').addEventListener('click', action(() => bridge?.window.hide()));
$('notice-dismiss').addEventListener('click', () => { $('notice').hidden = true; });
for (const button of document.querySelectorAll('[data-tab]')) button.addEventListener('click', () => selectTab(button.dataset.tab));
$('sensor-search').addEventListener('input', () => latest && renderSensors(latest));
for (const [id, key] of [['set-startup', 'startup'], ['set-start-hidden', 'startHidden'], ['set-click-through', 'clickThrough'], ['set-toasts', 'toastAlerts'], ['set-advanced', 'advancedSensors']]) $(id).addEventListener('change', action((event) => persist({ [key]: event.target.checked })));
$('set-adapter').addEventListener('change', action((event) => persist({ selectedAdapter: event.target.value || null })));
for (const [id, key, css] of [['opacity', 'opacity', '--widget-opacity'], ['background-opacity', 'backgroundOpacity', '--background-opacity']]) {
  $(`set-${id}`).addEventListener('input', (event) => { text(`${id}-value`, `${event.target.value}%`); document.documentElement.style.setProperty(css, Number(event.target.value) / 100); });
  $(`set-${id}`).addEventListener('change', action((event) => persist({ [key]: Number(event.target.value) / 100 })));
}
$('btn-snap').addEventListener('click', action(() => invoke('snap_to_current_monitor')));
$('btn-elevate').addEventListener('click', () => { $('elevate-confirm').hidden = false; $('btn-elevate-confirm').focus(); });
$('btn-elevate-cancel').addEventListener('click', () => { $('elevate-confirm').hidden = true; });
$('btn-elevate-confirm').addEventListener('click', action(() => invoke('restart_elevated')));
$('btn-refresh-diagnostics').addEventListener('click', action(refreshDiagnostics));
$('btn-diagnostics').addEventListener('click', action(async () => {
  await refreshDiagnostics();
  try { await navigator.clipboard.writeText(JSON.stringify({ diagnostics, inventory, snapshot: latest }, null, 2)); }
  catch { throw new Error('Windows blocked clipboard access. Collection health above can be selected and copied manually.'); }
  text('btn-diagnostics', 'Copied'); setTimeout(() => text('btn-diagnostics', 'Copy diagnostics'), 1800);
}));
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$('settings-panel').hidden) closeSettings(); });
document.addEventListener('mousedown', action(async (event) => {
  if (event.button !== 0 || !event.target.closest('[data-tauri-drag-region]') || event.target.closest('button,input,select')) return;
  event.preventDefault(); await bridge?.window.startDragging();
}));
function renderVisible() { if (document.hidden) return; if (latest) { if (settings?.expanded) renderActive(); else if ($('settings-panel').hidden) renderCompact(latest); } renderFreshness(); }
window.addEventListener('resize', renderVisible);
document.addEventListener('visibilitychange',renderVisible);
window.addEventListener('beforeunload', () => { for (const stop of unlisten) stop(); bridge?.dispose?.(); });

async function start() {
  if (demo) { document.documentElement.dataset.preview = 'true'; $('preview-label').hidden = false; }
  if (!bridge) throw new Error('Open the installed PTMonitor application for live readings. Browser design preview is available with ?demo.');
  // Subscribe first: no collector update can fall between initial reads and event setup.
  unlisten.push(await listen('ptmonitor://snapshot', (event) => acceptSnapshot(event.payload)));
  unlisten.push(await listen('ptmonitor://settings', (event) => { ++settingsRevision; applySettings(event.payload); }));
  unlisten.push(await listen('ptmonitor://open-settings', () => openSettings().catch(showFailure)));
  unlisten.push(await listen('ptmonitor://error', (event) => showFailure(event.payload)));
  unlisten.push(await listen('ptmonitor://resumed', () => {
    Promise.all([invoke('get_history'),invoke('get_snapshot')]).then(([points,snapshot])=>{history.restore(points);acceptSnapshot(snapshot);renderVisible();}).catch(showFailure);
  }));
  const results = await Promise.allSettled([invoke('get_settings'), invoke('get_snapshot'), invoke('get_inventory'), invoke('get_history')]);
  if (results[0].status === 'fulfilled') applySettings(results[0].value); else showFailure(results[0].reason);
  if (results[2].status === 'fulfilled' && !inventory?.hostname) { inventory = results[2].value; text('host-name', inventory.hostname || 'YOUR WORKSTATION'); }
  if (results[3].status === 'fulfilled') {
    history.restore(results[3].value);
  }
  if (results[1].status === 'fulfilled') acceptSnapshot(results[1].value); else showFailure(results[1].reason);
  if (latest) { if (settings?.expanded) renderActive(); else renderCompact(latest); }
  // Freshness clock only; telemetry is pushed by Rust and never browser-polled.
  const freshnessTimer = setInterval(renderFreshness, 1000); unlisten.push(() => clearInterval(freshnessTimer));
}
start().catch(showFailure);
