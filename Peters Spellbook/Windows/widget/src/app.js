const { invoke } = window.__TAURI__.core;
const { getCurrentWindow, LogicalSize } = window.__TAURI__.window;

// ── Drag (belt-and-suspenders with data-tauri-drag-region) ──
document.addEventListener('mousedown', async (e) => {
  if (e.button !== 0) return;
  if (!e.target.closest('[data-tauri-drag-region]')) return;
  if (e.target.closest('#header-controls')) return;
  e.preventDefault();
  try { await getCurrentWindow().startDragging(); } catch {}
});

const el = (id) => document.getElementById(id);

// ── Header buttons ──
el('btn-gear').addEventListener('click', async (e) => {
  e.stopPropagation();
  const panel = el('settings-panel');
  const opening = panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  if (opening) await loadSettings();
});

el('btn-min').addEventListener('click', (e) => {
  e.stopPropagation();
  getCurrentWindow().hide();
});

el('btn-close').addEventListener('click', async (e) => {
  e.stopPropagation();
  await invoke('quit_app');
});

// ── Settings panel ──
async function loadSettings() {
  const cfg = await invoke('get_config');
  el('set-startup').checked       = cfg.startup;
  el('set-start-hidden').checked  = cfg.start_hidden;
  el('set-click-through').checked = cfg.click_through;
  markActiveOpacity(cfg.opacity);
}

function markActiveOpacity(opacity) {
  document.querySelectorAll('.op-btn').forEach(btn => {
    btn.classList.toggle('active', parseFloat(btn.dataset.op) === opacity);
  });
}

el('set-startup').addEventListener('change', (e) =>
  invoke('toggle_setting', { key: 'startup', value: e.target.checked }));

el('set-start-hidden').addEventListener('change', (e) =>
  invoke('toggle_setting', { key: 'start_hidden', value: e.target.checked }));

el('set-click-through').addEventListener('change', (e) =>
  invoke('toggle_setting', { key: 'click_through', value: e.target.checked }));

document.querySelectorAll('.op-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const value = parseFloat(btn.dataset.op);
    await invoke('set_opacity_cmd', { value });
    markActiveOpacity(value);
  });
});

// ── Formatting helpers ──
function fmt(n, decimals = 1) { return n.toFixed(decimals); }
function pct(v) { return Math.min(100, Math.max(0, v)); }
function fmtMbps(mbPerSec) {
  const mbps = mbPerSec * 8;
  if (mbps >= 1000) return `${fmt(mbps / 1000, 2)} Gbps`;
  return `${fmt(mbps, 2)} Mbps`;
}
function fmtMBs(mbPerSec) {
  if (mbPerSec >= 1) return `${fmt(mbPerSec, 1)} MB/s`;
  return `${fmt(mbPerSec * 1024, 0)} KB/s`;
}
function setBar(barEl, percent) { barEl.style.width = `${pct(percent)}%`; }
function setVal(id, main, sub) {
  el(id).innerHTML = sub ? `${main}<span class="sub">${sub}</span>` : main;
}
function netPct(mbPerSec) { return (mbPerSec / 125) * 100; }

// ── Window resize to fit content ──
async function fitWindow() {
  await new Promise(r => setTimeout(r, 60));
  const h = el('widget').scrollHeight;
  await getCurrentWindow().setSize(new LogicalSize(240, h));
}

// ── Disk rows ──
let diskCount = 0;
function renderDisks(disks) {
  const container = el('disk-rows');
  if (disks.length !== diskCount) {
    diskCount = disks.length;
    container.innerHTML = disks.map(d => `
      <div class="stat-row">
        <span class="label">${d.label}:</span>
        <div class="bar-wrap"><div class="bar disk" id="bar-disk-${d.label}"></div></div>
        <span class="value" id="val-disk-${d.label}">—</span>
      </div>`).join('');
    fitWindow();
  }
  disks.forEach(d => {
    const bar = document.getElementById(`bar-disk-${d.label}`);
    const val = document.getElementById(`val-disk-${d.label}`);
    if (bar) setBar(bar, d.pct);
    if (val) val.innerHTML = `${fmt(d.pct, 0)}%<span class="sub">${fmt(d.used_gb, 0)}/${fmt(d.total_gb, 0)} GB</span>`;
  });
}

// ── Poll loop ──
async function poll() {
  try {
    const stats = await invoke('get_stats');

    setBar(el('bar-cpu'), stats.cpu_pct);
    setVal('val-cpu', `${fmt(stats.cpu_pct, 0)}%`);

    setBar(el('bar-ram'), stats.ram_pct);
    setVal('val-ram', `${fmt(stats.ram_pct, 0)}%`, `${fmt(stats.ram_used_gb, 1)} / ${fmt(stats.ram_total_gb, 0)} GB`);

    setBar(el('bar-gpu'), stats.gpu_pct);
    setVal('val-gpu', `${fmt(stats.gpu_pct, 0)}%`);

    renderDisks(stats.disks);

    setBar(el('bar-rx'), netPct(stats.net_rx_mbps));
    setVal('val-rx', fmtMbps(stats.net_rx_mbps), fmtMBs(stats.net_rx_mbps));

    setBar(el('bar-tx'), netPct(stats.net_tx_mbps));
    setVal('val-tx', fmtMbps(stats.net_tx_mbps), fmtMBs(stats.net_tx_mbps));

    el('status-dot').classList.remove('err');
  } catch {
    el('status-dot').classList.add('err');
  }
}

// ── Uptime counter ──
const startTime = Date.now();
function tickUptime() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;
  el('uptime-label').textContent = `uptime  ${h}h ${m}m ${s}s`;
}

// ── Init ──
invoke('get_opacity').then(opacity => {
  el('widget').style.opacity = opacity;
  markActiveOpacity(opacity);
});

poll();
setInterval(poll, 2000);
setInterval(tickUptime, 1000);
tickUptime();
