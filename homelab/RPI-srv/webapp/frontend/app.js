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
  agents:   renderAgents,
  leetify:  renderLeetify,
};

// Quick-link shortcuts shown on the Home page. Edit here (could graduate to /api/links later).
const QUICK_LINKS = [
  { label: 'Cockpit',          url: 'https://rpi:9090/',                              icon: '🖥️' },
  { label: 'Pi-hole',          url: 'http://rpi/admin/login',                          icon: '🛡️' },
  { label: 'Vaultwarden',      url: 'https://bitwarden.rpi.lan/#/vault',               icon: '🔑' },
  { label: 'Vaultwarden admin', url: 'https://bitwarden.rpi.lan/admin/users/overview', icon: '⚙️' },
  { label: 'OMV (opti)',       url: 'http://opti.lan/#/login',                         icon: '🗄️' },
];

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
        <h1 class="home-title"><img src="favicon.svg" alt="" class="home-title-icon" />Pert's Pocket</h1>
        <span class="badge-host">rpi · 192.168.1.10</span>
      </header>

      <section class="cards">
        <div class="card">
          <div class="card-icon">🤖</div>
          <div class="card-body">
            <h2>Agents</h2>
            <p>Homelab hardware, software &amp; network reports — status, history, run-now.</p>
          </div>
          <a href="#agents" class="card-link">View agents →</a>
        </div>

        <div class="card">
          <div class="card-icon">🔒</div>
          <div class="card-body">
            <h2>Security Reports</h2>
            <p>Live results from ARP watch, rogue AP detection, Windows event hunting, and more.</p>
          </div>
          <a href="#security" class="card-link">View reports →</a>
        </div>

        <div class="card" id="leetify-card">
          <div class="card-icon">🎯</div>
          <div class="card-body">
            <h2>CS2 / Leetify</h2>
            <p id="leetify-body">Loading…</p>
          </div>
          <a href="#leetify" class="card-link">View analysis →</a>
        </div>

        <div class="card" id="pihole-card">
          <div class="card-icon">🛡️</div>
          <div class="card-body">
            <h2>Pi-hole</h2>
            <p id="pihole-body">Loading…</p>
          </div>
        </div>

        <div class="card">
          <div class="card-icon">📝</div>
          <div class="card-body">
            <h2>Notes</h2>
            <p>OneNote-style notebook — quick capture, sections &amp; pages.</p>
          </div>
          <a href="/notes/" class="card-link">Open notes →</a>
        </div>

        <div class="card card-links">
          <div class="card-icon">🔗</div>
          <div class="card-body">
            <h2>Quick Links</h2>
            <div class="links-grid">
              ${QUICK_LINKS.map(l => `<a class="link-item" href="${escHtml(l.url)}" target="_blank" rel="noopener">${l.icon} ${escHtml(l.label)}</a>`).join('')}
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
  loadLeetify();
  loadPihole();
}

async function loadLeetify() {
  const el = document.getElementById('leetify-body');
  if (!el) return;
  try {
    const res = await fetch('/api/agents/leetify-latest');
    if (!res.ok) { el.textContent = 'Not configured yet — set LEETIFY_API_KEY + STEAM64_ID on opti.'; return; }
    const d = await res.json();
    el.textContent = d.summary || 'No data yet.';
  } catch {
    el.textContent = 'Unavailable.';
  }
}

async function loadPihole() {
  const el = document.getElementById('pihole-body');
  if (!el) return;
  try {
    const res = await fetch('/api/agents/network-latest');
    if (!res.ok) { el.textContent = 'No network report yet.'; return; }
    const d = await res.json();
    const p = (d.hosts && d.hosts[0] && d.hosts[0].metrics && d.hosts[0].metrics.pihole) || d.pihole;
    if (!p) { el.textContent = 'Pi-hole stats unavailable.'; return; }
    const q = p.dns_queries_today ?? p.queries ?? '?';
    const blocked = p.ads_blocked_today ?? p.blocked ?? '?';
    const pct = p.ads_percentage_today ?? p.percent_blocked;
    const clients = p.unique_clients ?? p.clients ?? '?';
    el.innerHTML = `${q} queries today · <strong>${typeof pct === 'number' ? pct.toFixed(1) : pct}%</strong> blocked (${blocked}) · ${clients} clients`;
  } catch {
    el.textContent = 'Unavailable.';
  }
}

// ── Leetify page ────────────────────────────────────────────────────────────────
async function renderLeetify(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>CS2 / Leetify</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="openAgentHistory('leetify-latest','CS2 / Leetify')">History</button>
          <button class="btn-refresh" onclick="renderLeetify(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="leetify-page"><div class="sec-loading">Loading analysis…</div></div>
    </div>
  `;

  let d;
  try {
    const res = await fetch('/api/agents/leetify-latest');
    if (!res.ok) throw new Error();
    d = await res.json();
  } catch {
    document.getElementById('leetify-page').innerHTML =
      `<div class="sec-empty"><p>No Leetify report yet.</p>
       <p class="sec-empty-hint">Set LEETIFY_API_KEY + STEAM64_ID on opti and run the agent.</p></div>`;
    return;
  }

  const dims = d.dimensions || {};
  const dimChip = (k) => {
    const v = dims[k];
    if (v == null) return '';
    const cls = v >= 60 ? 'dim-strong' : (v < 52 ? 'dim-focus' : 'dim-ok');
    return `<div class="dim ${cls}"><span class="dim-name">${k}</span><span class="dim-val">${Math.round(v)}</span></div>`;
  };

  const maps = d.maps || [];
  const mapRows = maps.map(m => {
    const verdict = m.matches < 2 ? 'low sample'
      : (m.win_rate >= 55 && m.avg_rating >= 0 ? 'strong'
      : (m.win_rate <= 40 || m.avg_rating < -0.03 ? 'avoid / practice' : 'even'));
    return `<tr><td>${escHtml(m.map)}</td><td>${m.matches}</td><td>${m.win_rate}%</td>
            <td>${(m.ct_rating ?? 0).toFixed(3)}</td><td>${(m.t_rating ?? 0).toFixed(3)}</td>
            <td>${verdict}</td></tr>`;
  }).join('');

  // Per-demo breakdown (only present when demo parsing ran on opti).
  const demoSummaries = d.demo_summaries || [];
  const demosHtml = demoSummaries.length ? `
    <h3 class="detail-section-title">Recent demos</h3>
    <div class="pos-grid">
      ${demoSummaries.map(ds => {
        const resultCls = ds.result === 'win' ? 'demo-win' : ds.result === 'loss' ? 'demo-loss' : '';
        const hotRows = (ds.hotspots || []).map(h =>
          `<tr><td>${escHtml(h.area)}</td><td>${escHtml(h.side)}</td><td>${h.count}</td><td>${h.pct}%</td></tr>`
        ).join('');
        const kdStr = (ds.kills != null && ds.deaths != null) ? `${ds.kills}/${ds.deaths} K/D` : '';
        const ratingStr = ds.rating != null ? ` · ${ds.rating > 0 ? '+' : ''}${ds.rating.toFixed(3)} rating` : '';
        const hsStr = ds.hs_pct != null ? ` · ${ds.hs_pct}% HS` : '';
        return `<div class="pos-card">
          <div class="pos-card-head">
            <span class="demo-map">${escHtml(ds.map)}</span>
            <span class="demo-date">${escHtml(ds.date)}</span>
            <span class="demo-result ${resultCls}">${ds.result}${ds.score ? ' ' + ds.score : ''}</span>
          </div>
          <div class="demo-stats">${kdStr}${ratingStr}${hsStr}</div>
          ${hotRows ? `<table class="detail-table"><thead><tr><th>Died at</th><th>Side</th><th>×</th><th>%</th></tr></thead>
            <tbody>${hotRows}</tbody></table>` : ''}
        </div>`;
      }).join('')}
    </div>
  ` : '';

  // Match deep-dive — collapsible round-by-round table per parsed demo.
  const deepDives = demoSummaries.filter(ds => (ds.rounds || []).length);
  const deepHtml = deepDives.length ? `
    <h3 class="detail-section-title">Match deep-dive — round by round</h3>
    <div class="deep-list">
      ${deepDives.map(ds => {
        const rounds = ds.rounds || [];
        const won = rounds.filter(r => r.won === true).length;
        const lost = rounds.filter(r => r.won === false).length;
        const resultCls = ds.result === 'win' ? 'demo-win' : ds.result === 'loss' ? 'demo-loss' : '';
        const kdStr = (ds.kills != null && ds.deaths != null) ? ` · ${ds.kills}/${ds.deaths} K/D` : '';
        const rows = rounds.map(r => {
          const rowCls = r.won === true ? 'round-won' : r.won === false ? 'round-lost' : '';
          const kills = (r.kills || []).length;
          const killStr = kills ? `${kills}K` : '—';
          const dmgStr = r.damage ? `${r.damage}` : '—';
          const obj = r.planted ? '💣 plant' : r.defused ? '🛡 defuse' : '';
          const fate = r.died ? (r.killer ? `died → ${escHtml(r.killer)}` : 'died') : 'survived';
          const wl = r.won === true ? 'W' : r.won === false ? 'L' : '?';
          return `<tr class="${rowCls}">
            <td>${r.round}</td><td>${escHtml(r.side || '?')}</td><td class="round-wl">${wl}</td>
            <td>${killStr}</td><td>${dmgStr}</td><td>${escHtml(fate)}</td><td>${obj}</td></tr>`;
        }).join('');
        return `<details class="deep-card">
          <summary>
            <span class="demo-map">${escHtml(ds.map)}</span>
            <span class="demo-date">${escHtml(ds.date)}</span>
            <span class="demo-result ${resultCls}">${ds.result}${ds.score ? ' ' + ds.score : ''}</span>
            <span class="deep-wl">${won}W / ${lost}L rounds${kdStr}</span>
          </summary>
          <table class="detail-table deep-table">
            <thead><tr><th>R</th><th>Side</th><th>W/L</th><th>Kills</th><th>Dmg</th><th>Fate</th><th>Obj</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </details>`;
      }).join('')}
    </div>
    ${d.ai_review ? '<p class="sec-empty-hint">Per-match coaching & recurring-mistake analysis is in the AI review below.</p>' : ''}
  ` : '';

  // Aggregate positional breakdown across all parsed demos.
  const positions = d.positions || {};
  const posMaps = Object.keys(positions);
  const posHtml = posMaps.length ? `
    <h3 class="detail-section-title">Positional breakdown — where you die</h3>
    <div class="pos-grid">
      ${posMaps.map(mp => {
        const p = positions[mp];
        const rows = (p.hotspots || []).map(h =>
          `<tr><td>${escHtml(h.area)}</td><td>${escHtml(h.side)}</td><td>${h.count}</td><td>${h.pct}%</td></tr>`
        ).join('');
        return `<div class="pos-card">
          <div class="pos-card-head">${escHtml(mp)} — ${p.deaths} deaths
            <span class="pos-split">CT ${p.ct_deaths} / T ${p.t_deaths}</span></div>
          <table class="detail-table"><thead><tr><th>Area</th><th>Side</th><th>Deaths</th><th>%</th></tr></thead>
            <tbody>${rows}</tbody></table>
        </div>`;
      }).join('')}
    </div>
    ${d.ai_review ? '<p class="sec-empty-hint">Reposition advice for each hotspot is in the AI coaching review below.</p>' : ''}
  ` : '';

  // Belt-and-suspenders: strip any positional breakdown section from the log (newer reports
  // omit it server-side, but older cached JSON may still embed it) — it's rendered as cards above.
  const logText = d.log ? d.log.replace(/\n+---\n+## Positional breakdown[\s\S]*$/, '') : '';
  const logHtml = logText
    ? (typeof marked !== 'undefined' ? marked.parse(logText) : `<pre>${escHtml(logText)}</pre>`)
    : '';

  // AI coaching is the headline — show it FIRST (right after the summary), data below.
  const coachingHtml = logHtml
    ? `<div class="coaching-block"><div class="agent-report-body">${logHtml}</div></div>`
    : (d.demo_summaries && d.demo_summaries.length
        ? `<div class="coaching-block coaching-missing">
             <strong>AI coaching unavailable for this run.</strong>
             <span>The demo data below was parsed, but the coaching call didn't complete
             (check the agent run / API credits). The structured breakdowns still show what happened.</span>
           </div>`
        : '');

  document.getElementById('leetify-page').innerHTML = `
    <p class="report-summary">${escHtml(d.summary || '')}</p>
    <div class="dim-strip">${dimChip('aim')}${dimChip('positioning')}${dimChip('utility')}</div>
    ${coachingHtml}
    <details class="data-fold" open>
      <summary class="data-fold-summary">Supporting data — stats, demos & death maps</summary>
      ${maps.length ? `
        <h3 class="detail-section-title">Per-map (last 25)</h3>
        <table class="detail-table">
          <thead><tr><th>Map</th><th>Matches</th><th>Win %</th><th>CT</th><th>T</th><th>Verdict</th></tr></thead>
          <tbody>${mapRows}</tbody>
        </table>` : ''}
      ${demosHtml}
      ${deepHtml}
      ${posHtml}
    </details>
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

  grid.innerHTML = reports.map(r => buildReportCard(r, 'reports')).join('');
}

// ── Agents page ───────────────────────────────────────────────────────────────
let agentsRefreshTimer = null;

async function renderAgents(view) {
  clearInterval(agentsRefreshTimer);
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Homelab Agents</h1>
        <div class="sec-header-actions">
          <span id="agt-last-refresh" class="sec-refresh-label">Loading...</span>
          <button class="btn-refresh" onclick="loadAgents()">↻ Refresh</button>
        </div>
      </div>
      <div id="agt-grid" class="sec-grid"><div class="sec-loading">Loading agents…</div></div>
    </div>
  `;
  await loadAgents();
  agentsRefreshTimer = setInterval(loadAgents, 5 * 60 * 1000);
}

async function loadAgents() {
  const grid = document.getElementById('agt-grid');
  if (!grid) return;

  let agents;
  try {
    const res = await fetch('/api/agents');
    const data = await res.json();
    agents = data.agents ?? [];
  } catch {
    grid.innerHTML = `<div class="sec-error">Cannot reach /api/agents — is the backend running?</div>`;
    return;
  }

  const label = document.getElementById('agt-last-refresh');
  if (label) label.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;

  if (agents.length === 0) {
    grid.innerHTML = `
      <div class="sec-empty">
        <p>No agent reports yet.</p>
        <p class="sec-empty-hint">Run them from opti (GitHub Actions or the dispatcher), or hit “Run now” once reports exist.</p>
      </div>`;
    return;
  }

  grid.innerHTML = agents.map(a => buildReportCard(a, 'agents')).join('');
}

function buildReportCard(r, apiBase) {
  const statusClass = { ok: 'status-ok', warn: 'status-warn', critical: 'status-critical' }[r.status] ?? 'status-unknown';
  const statusLabel = { ok: 'OK', warn: 'WARN', critical: 'CRITICAL', unknown: '?' }[r.status] ?? r.status.toUpperCase();
  const runAt = r.run_at ? new Date(r.run_at).toLocaleString() : '—';
  const staleBadge = r.stale ? `<span class="sec-stale-badge" title="No fresh run recently">STALE</span>` : '';
  const alertBadge = r.has_alert ? `<span class="agent-alert-badge" title="Alert flagged in this report">ALERT</span>` : '';
  const safeLabel = (r.label || '').replace(/'/g, "\\'");
  const isAgent = apiBase === 'agents';

  const controls = r.agent ? `
        <button class="btn-toggle ${r.enabled ? 'on' : 'off'}" onclick="toggleAgent('${apiBase}','${r.agent}',${!r.enabled},this)">${r.enabled ? 'Enabled' : 'Disabled'}</button>
        <button class="btn-run" onclick="runAgent('${apiBase}','${r.agent}',this)">Run now</button>` : '';

  // Agents get the full-log viewer ("View latest") + per-run History; security reports keep "View details".
  const viewBtns = isAgent
    ? `<button class="btn-view" onclick="openAgentReport('${r.name}', '${safeLabel}')">View latest</button>
        <button class="btn-view" onclick="openAgentHistory('${r.name}', '${safeLabel}')">History</button>`
    : `<button class="btn-view" onclick="openReportDetail('${r.name}', '${safeLabel}', '${apiBase}')">View details</button>`;

  return `
    <div class="sec-card ${statusClass}${r.enabled === false ? ' card-disabled' : ''}">
      <div class="sec-card-header">
        <span class="sec-status-badge ${statusClass}">${statusLabel}</span>
        <span class="sec-card-title">${r.label} ${alertBadge}</span>
        ${staleBadge}
      </div>
      <p class="sec-card-summary">${r.summary || 'No summary available'}</p>
      <div class="sec-card-meta">Last run: ${runAt}</div>
      <div class="sec-card-actions">
        ${viewBtns}
        ${controls}
      </div>
    </div>
  `;
}

// Turn a failed dispatcher response into a human, diagnosable message.
async function dispatcherError(res, err) {
  if (err) return `Network error reaching the webapp backend: ${err.message}`;
  let detail = '';
  try { const d = await res.json(); detail = d.error || d.raw || ''; } catch (_) {}
  switch (res.status) {
    case 503: return `Dispatcher not configured — set DISPATCHER_URL in the webapp's .env on the Pi. ${detail}`;
    case 502: return `Backend reached, but could not connect to the dispatcher on opti (network/firewall, or wrong DISPATCHER_URL). ${detail}`;
    case 401: return `Dispatcher rejected the request (401) — HL_DISPATCH_TOKEN mismatch between the webapp and opti. ${detail}`;
    default:  return `Run failed (HTTP ${res.status}). ${detail}`;
  }
}

async function toggleAgent(apiBase, agent, enabled, btn) {
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch(`/api/${apiBase}/${encodeURIComponent(agent)}/enabled`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch (e) { err = e; }

  if (res && res.ok) {
    btn.textContent = enabled ? 'Enabled' : 'Disabled';
    btn.classList.toggle('on', enabled);
    btn.classList.toggle('off', !enabled);
    btn.setAttribute('onclick', `toggleAgent('${apiBase}','${agent}',${!enabled},this)`);
    btn.closest('.sec-card')?.classList.toggle('card-disabled', !enabled);
  } else {
    alert(await dispatcherError(res, err));
  }
  btn.disabled = false;
}

async function runAgent(apiBase, agent, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Queued…';
  let res, err;
  try {
    res = await fetch(`/api/${apiBase}/${encodeURIComponent(agent)}/run`, { method: 'POST' });
  } catch (e) { err = e; }

  if (res && (res.ok || res.status === 202)) {
    btn.textContent = 'Queued ✓ — refresh shortly';
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 5000);
  } else {
    btn.textContent = orig;
    btn.disabled = false;
    alert(await dispatcherError(res, err));
  }
}

// ── Agent full-log viewer + history ─────────────────────────────────────────────
// `date` optional — when set, opens that specific dated report instead of the latest.
async function openAgentReport(name, label, date) {
  const url = date ? `/api/agents/${name}/report/${date}` : `/api/agents/${name}`;
  let data;
  try {
    const res = await fetch(url);
    data = await res.json();
  } catch {
    alert('Could not load report: ' + name);
    return;
  }

  const dateLabel = date ? ` — ${date}` : (data.run_at ? ` — ${new Date(data.run_at).toLocaleString()}` : '');

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">${escHtml(label)}${escHtml(dateLabel)}</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="modal-body agent-report-body">${renderAgentReport(data)}</div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// Render a full agent report. We always show what the run produced — never a bare
// "all clear" — so an OK report still shows its summary, findings, recommendations,
// the full markdown log (new collectors), or a structured dump of the data (legacy).
function renderAgentReport(data) {
  let html = '';

  // Status + summary header (always present, so OK runs still show context).
  const status = (data.status || 'unknown').toLowerCase();
  const statusClass = { ok: 'status-ok', warn: 'status-warn', critical: 'status-critical' }[status] ?? 'status-unknown';
  html += `<div class="report-status-line">
             <span class="sec-status-badge ${statusClass}">${escHtml(status.toUpperCase())}</span>
             ${data.run_at ? `<span class="report-runat">ran ${escHtml(new Date(data.run_at).toLocaleString())}</span>` : ''}
           </div>`;
  if (data.summary) html += `<p class="sec-card-summary report-summary">${escHtml(data.summary)}</p>`;

  // Findings (problems detected this run).
  const findings = data.findings ?? [];
  if (findings.length) {
    html += `<h3 class="detail-section-title">Findings</h3>${renderFindingList(findings)}`;
  }

  // Recommendations / watch list.
  const recs = data.recommendations ?? [];
  if (recs.length) {
    html += `<h3 class="detail-section-title">Recommendations / watch list</h3>${renderFindingList(recs)}`;
  }

  // The full human-readable log (new collectors).
  if (data.log) {
    html += (typeof marked !== 'undefined') ? marked.parse(data.log) : `<pre>${escHtml(data.log)}</pre>`;
  } else {
    // Legacy reports (no log) — show the structured data so the run is still visible.
    html += renderReportData(data);
  }

  return html || '<div class="detail-ok">No report content.</div>';
}

function renderFindingList(items) {
  const rows = items.map(f => `
    <div class="finding finding-${escHtml((f.severity || 'info').toLowerCase())}">
      <span class="finding-sev">${escHtml((f.severity || 'info').toUpperCase())}</span>
      <span class="finding-msg">${escHtml(f.message || '')}</span>
    </div>`).join('');
  return `<div class="findings-list">${rows}</div>`;
}

// Generic structured view of an agent report's data (for legacy reports without a `log`).
// Renders per-host metric tables when present, otherwise a flat key/value table of the
// report's scalar/array fields — so you always see what the agent ran and found.
function renderReportData(data) {
  const SKIP = new Set(['tool', 'run_at', 'status', 'summary', 'findings', 'recommendations', 'log', 'hosts', 'name', 'label']);
  let html = '';

  if (Array.isArray(data.hosts) && data.hosts.length) {
    for (const h of data.hosts) {
      html += `<h3 class="detail-section-title">${escHtml(h.host || 'host')}</h3>`;
      if (h.summary) html += `<p class="sec-card-summary">${escHtml(h.summary)}</p>`;
      if (h.metrics) html += kvTable(h.metrics);
    }
  }

  const rest = {};
  for (const [k, v] of Object.entries(data)) {
    if (!SKIP.has(k)) rest[k] = v;
  }
  if (Object.keys(rest).length) {
    html += `<h3 class="detail-section-title">Details</h3>${kvTable(rest)}`;
  }
  return html || '<div class="detail-ok">No additional detail in this report.</div>';
}

// Render an object as a two-column table; nested objects/arrays are JSON-stringified compactly.
function kvTable(obj) {
  const rows = Object.entries(obj).map(([k, v]) => {
    let val;
    if (v === null || v === undefined) val = '—';
    else if (Array.isArray(v) || typeof v === 'object') val = JSON.stringify(v);
    else val = String(v);
    return `<tr><td>${escHtml(k)}</td><td>${escHtml(val)}</td></tr>`;
  }).join('');
  return `<table class="detail-table"><tbody>${rows}</tbody></table>`;
}

async function openAgentHistory(name, label) {
  let data;
  try {
    const res = await fetch(`/api/agents/${name}/history`);
    data = await res.json();
  } catch {
    alert('Could not load history: ' + name);
    return;
  }
  const items = data.history ?? [];
  const rows = items.length
    ? items.map(h => `
        <div class="history-row">
          <button class="history-link" onclick="document.querySelector('.modal-overlay').remove(); openAgentReport('${name}', '${(label || '').replace(/'/g, "\\'")}', '${h.date}')">${escHtml(h.date)}</button>
          <span class="history-meta">${h.mtime ? new Date(h.mtime).toLocaleString() : '—'} · ${h.size}b</span>
        </div>`).join('')
    : `<div class="sec-empty">No history yet.</div>`;

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">${escHtml(label)} — history</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="modal-body">${rows}</div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

async function openReportDetail(name, label, apiBase = 'reports') {
  let data;
  try {
    const res = await fetch(`/api/${apiBase}/${name}`);
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
