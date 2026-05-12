// ── Health check ─────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.getElementById('healthDot');
  const uptimeEl = document.getElementById('uptimeEl');
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    dot.classList.remove('health-down');
    dot.classList.add('health-up');
    const s = Math.floor(data.uptime);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    uptimeEl.textContent = `uptime ${h}h ${m}m ${sec}s`;
  } catch {
    dot.classList.remove('health-up');
    dot.classList.add('health-down');
    uptimeEl.textContent = 'API unreachable';
  }
}

// ── Router ────────────────────────────────────────────────────────────────────
const routes = {
  home:     renderHome,
  security: renderSecurity,
};

function route() {
  const hash = location.hash.replace('#', '') || 'home';
  const view = document.getElementById('view');

  // Update active nav link
  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.route === hash);
  });

  const renderer = routes[hash] ?? renderHome;
  renderer(view);
}

// ── Home page ─────────────────────────────────────────────────────────────────
function renderHome(view) {
  view.innerHTML = `
    <div class="page-home">
      <header class="page-header">
        <h1>webapp.rpi.lan</h1>
        <span class="badge-host">rpi · 192.168.1.10</span>
      </header>

      <section class="cards">
        <div class="card">
          <div class="card-icon">🔒</div>
          <div class="card-body">
            <h2>Security Reports</h2>
            <p>Live results from ARP watch, rogue AP detection, Windows event hunting, and more.</p>
          </div>
          <a href="#security" class="card-link">View reports →</a>
        </div>

        <div class="card card-placeholder">
          <div class="card-icon">🌤️</div>
          <div class="card-body">
            <h2>Weather</h2>
            <p>OpenWeatherMap widget — coming soon.</p>
          </div>
        </div>

        <div class="card card-placeholder">
          <div class="card-icon">🎮</div>
          <div class="card-body">
            <h2>Steam</h2>
            <p>Recently played &amp; current status — coming soon.</p>
          </div>
        </div>

        <div class="card card-placeholder">
          <div class="card-icon">📝</div>
          <div class="card-body">
            <h2>Notes</h2>
            <p>OneNote-style notebook — coming soon.</p>
          </div>
        </div>
      </section>
    </div>
  `;
}

// ── Security page ─────────────────────────────────────────────────────────────
let securityRefreshTimer = null;

async function renderSecurity(view) {
  clearInterval(securityRefreshTimer);

  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Security Reports</h1>
        <div class="sec-header-actions">
          <span id="sec-last-refresh" class="sec-refresh-label">Loading...</span>
          <button class="btn-refresh" onclick="refreshSecurityReports()">↻ Refresh</button>
        </div>
      </div>
      <div id="sec-grid" class="sec-grid"><div class="sec-loading">Loading reports…</div></div>
    </div>
  `;

  await loadSecurityReports();
  securityRefreshTimer = setInterval(loadSecurityReports, 5 * 60 * 1000);
}

async function refreshSecurityReports() {
  const btn = document.querySelector('.btn-refresh');
  if (btn) { btn.textContent = '↻ Refreshing…'; btn.disabled = true; }
  await loadSecurityReports();
  if (btn) { btn.textContent = '↻ Refresh'; btn.disabled = false; }
}

async function loadSecurityReports() {
  const grid = document.getElementById('sec-grid');
  if (!grid) return;

  let reports;
  try {
    const res = await fetch('/api/reports');
    const data = await res.json();
    reports = data.reports ?? [];
  } catch {
    grid.innerHTML = `<div class="sec-error">Cannot reach /api/reports — is the backend running?</div>`;
    return;
  }

  const label = document.getElementById('sec-last-refresh');
  if (label) label.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;

  if (reports.length === 0) {
    grid.innerHTML = `
      <div class="sec-empty">
        <p>No reports found yet.</p>
        <p class="sec-empty-hint">Run the security tools manually or wait for scheduled tasks to fire.<br>
        Reports are written to <code>\\\\rpi.lan\\ptm\\security-reports\\</code></p>
      </div>
    `;
    return;
  }

  grid.innerHTML = reports.map(r => buildReportCard(r)).join('');
}

function buildReportCard(r) {
  const statusClass = { ok: 'status-ok', warn: 'status-warn', critical: 'status-critical' }[r.status] ?? 'status-unknown';
  const statusLabel = { ok: 'OK', warn: 'WARN', critical: 'CRITICAL', unknown: '?' }[r.status] ?? r.status.toUpperCase();
  const runAt = r.run_at ? new Date(r.run_at).toLocaleString() : '—';
  const mapBtn = r.has_map
    ? `<a href="/api/reports/geoip/map" target="_blank" class="card-link-secondary">Open map ↗</a>`
    : '';

  return `
    <div class="sec-card ${statusClass}">
      <div class="sec-card-header">
        <span class="sec-status-badge ${statusClass}">${statusLabel}</span>
        <span class="sec-card-title">${r.label}</span>
      </div>
      <p class="sec-card-summary">${r.summary || 'No summary available'}</p>
      <div class="sec-card-meta">Last run: ${runAt}</div>
      <div class="sec-card-actions">
        <button class="btn-view" onclick="openReportDetail('${r.name}', '${r.label}')">View details</button>
        ${mapBtn}
      </div>
    </div>
  `;
}

async function openReportDetail(name, label) {
  let data;
  try {
    const res = await fetch(`/api/reports/${name}`);
    data = await res.json();
  } catch {
    alert('Could not load report: ' + name);
    return;
  }

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">${label}</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="modal-body">
        ${renderReportDetail(data)}
      </div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

function renderReportDetail(data) {
  const findings = data.findings ?? [];

  if (findings.length === 0) {
    return `<div class="detail-ok">No findings — all clear.</div>`;
  }

  const rows = findings.map(f => `
    <div class="finding finding-${f.severity}">
      <span class="finding-sev">${f.severity.toUpperCase()}</span>
      <span class="finding-msg">${escHtml(f.message)}</span>
    </div>
  `).join('');

  let extra = '';

  // ARP watch: show current table
  if (data.tool === 'arp-watch' && data.arp_table?.length) {
    const tableRows = data.arp_table.map(e =>
      `<tr><td>${e.ip}</td><td>${e.mac}</td><td>${e.hostname ?? '—'}</td><td>${e.last_seen?.slice(0,19) ?? '—'}</td></tr>`
    ).join('');
    extra = `
      <h3 class="detail-section-title">ARP Table</h3>
      <table class="detail-table">
        <thead><tr><th>IP</th><th>MAC</th><th>Hostname</th><th>Last Seen</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    `;
  }

  // LinkedIn jobs: detailed list
  if (data.tool === 'linkedin-job-watcher' && data.new_jobs?.length) {
    const jobRows = data.new_jobs.map(j => `
      <div class="job-row">
        <div class="job-title"><a href="${escHtml(j.url)}" target="_blank">${escHtml(j.title)}</a></div>
        <div class="job-meta">${escHtml(j.company)} · ${escHtml(j.location)} · ${escHtml(j.posted_text || 'recent')}</div>
      </div>
    `).join('');
    extra = `
      <h3 class="detail-section-title">New Jobs</h3>
      <div class="job-list">${jobRows}</div>
    `;
    return extra;  // skip the default findings list — we render jobs directly
  }

  // GeoIP: top IPs
  if (data.tool === 'geoip-log-mapper' && data.top_ips?.length) {
    const tableRows = data.top_ips.slice(0, 15).map(e =>
      `<tr><td>${e.query ?? e.ip ?? '?'}</td><td>${e.hits ?? '?'}</td><td>${e.country ?? '?'}</td><td>${e.city ?? '?'}</td><td>${e.isp ?? '?'}</td></tr>`
    ).join('');
    extra = `
      <h3 class="detail-section-title">Top External IPs</h3>
      <table class="detail-table">
        <thead><tr><th>IP</th><th>Hits</th><th>Country</th><th>City</th><th>ISP</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    `;
  }

  return `<div class="findings-list">${rows}</div>${extra}`;
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('hashchange', route);
window.addEventListener('load', () => {
  checkHealth();
  setInterval(checkHealth, 30_000);
  route();
});
