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
  weather:  renderWeather,
  healthdigest: renderHealthdigest,
  jellyfin: renderJellyfin,
  sports:   renderSports,
  hltv:     renderHltv,
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

        <div class="card" id="weather-card">
          <div class="card-icon">🌤️</div>
          <div class="card-body">
            <h2>Weather Bot</h2>
            <p id="weather-body">Loading…</p>
          </div>
          <a href="#weather" class="card-link">Bot settings →</a>
        </div>

        <div class="card" id="healthdigest-card">
          <div class="card-icon">🩺</div>
          <div class="card-body">
            <h2>Health Bot</h2>
            <p id="healthdigest-body">Loading…</p>
          </div>
          <a href="#healthdigest" class="card-link">Bot settings →</a>
        </div>

        <div class="card" id="jellyfinbot-card">
          <div class="card-icon">🎬</div>
          <div class="card-body">
            <h2>Jellyfin Bot</h2>
            <p id="jellyfinbot-body">Loading…</p>
          </div>
          <a href="#jellyfin" class="card-link">Bot settings →</a>
        </div>

        <div class="card" id="sportsbot-card">
          <div class="card-icon">🏟️</div>
          <div class="card-body">
            <h2>Sports Bot</h2>
            <p id="sportsbot-body">Loading…</p>
          </div>
          <a href="#sports" class="card-link">Bot settings →</a>
        </div>

        <div class="card" id="hltvbot-card">
          <div class="card-icon">🎯</div>
          <div class="card-body">
            <h2>HLTV Bot</h2>
            <p id="hltvbot-body">Loading…</p>
          </div>
          <a href="#hltv" class="card-link">Bot settings →</a>
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
  loadWeatherCard();
  loadBotCard('healthdigest', 'healthdigest-body');
  loadBotCard('jellyfin', 'jellyfinbot-body');
  loadBotCard('sports', 'sportsbot-body');
  loadBotCard('hltv', 'hltvbot-body');
}

async function loadWeatherCard() {
  const el = document.getElementById('weather-body');
  if (!el) return;
  try {
    const res = await fetch('/api/weather/status');
    if (!res.ok) { el.textContent = 'Bot unreachable — check discord-weather container.'; return; }
    const d = await res.json();
    const next = d.next_post_at
      ? new Date(d.next_post_at).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
      : null;
    const last = d.last_status || 'no posts yet';
    const lastBad = /fail/i.test(last);
    el.innerHTML = d.enabled
      ? `Next post: <strong>${escHtml(next || '…')}</strong> · Last: ${lastBad ? `<strong style="color:var(--red)">${escHtml(last)}</strong>` : escHtml(last)}`
      : 'Daily posts <strong>paused</strong>.';
  } catch {
    el.textContent = 'Unavailable.';
  }
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
    // Pi-hole runs on one host (rpi) — find whichever host's metrics carry it.
    const p = (Array.isArray(d.hosts)
      ? (d.hosts.find(h => h && h.metrics && h.metrics.pihole) || {}).metrics?.pihole
      : null) || d.pihole;
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
    if (!res.ok) {
      // A 500 means the report file exists but won't parse (corrupt/truncated) —
      // distinct from a 404 "no report yet". Show the real reason so it's fixable.
      let detail = '';
      try { const e = await res.json(); detail = e.detail || ''; } catch (_) {}
      if (res.status === 500) {
        document.getElementById('leetify-page').innerHTML =
          `<div class="sec-empty"><p>Leetify report is corrupt and could not be read.</p>
           ${detail ? `<p class="sec-empty-hint">${detail}</p>` : ''}
           <p class="sec-empty-hint">Re-run the agent to regenerate it (↻ Refresh after).</p></div>`;
        return;
      }
      throw new Error();
    }
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

  // HLTV VRS "players to watch" — role-matched picks from the top-15 teams. Sits directly
  // under the AI coaching review. Refreshed weekly server-side; absent if it's never run.
  const wl = d.watchlist;
  const watchlistHtml = (wl && Array.isArray(wl.teams) && wl.teams.length) ? `
    <div class="watchlist-block">
      <h3 class="detail-section-title">Players to watch — HLTV VRS top ${wl.teams.length}</h3>
      <div class="wl-summary">
        <div class="wl-summary-row">
          <span class="wl-summary-label">Your roles</span>
          <span class="wl-summary-val">${escHtml(wl.my_roles || '—')}</span>
        </div>
        <div class="wl-summary-row">
          <span class="wl-summary-label">VRS as of</span>
          <span class="wl-summary-val">${escHtml(wl.vrs_as_of || '—')}</span>
        </div>
      </div>
      <div class="pos-grid">
        ${wl.teams.map(t => {
          const picks = (t.players || []).map(p => {
            const conf = (p.confidence || '').toLowerCase();
            const confTag = conf === 'low' ? ' <span class="wl-low">(role: low confidence)</span>' : '';
            return `<li>
              <span class="wl-player">${escHtml(p.player || '?')}</span>
              <span class="wl-role">${escHtml(p.role || '')}</span>${confTag}
              ${p.why_for_you ? `<div class="wl-why">${escHtml(p.why_for_you)}</div>` : ''}
            </li>`;
          }).join('');
          return `<div class="pos-card">
            <div class="pos-card-head">#${t.rank ?? '?'} · ${escHtml(t.team || '?')}</div>
            <ul class="wl-players">${picks}</ul>
          </div>`;
        }).join('')}
      </div>
    </div>
  ` : '';

  // AI coaching is the headline — show it FIRST (right after the summary), data below.
  // The notice keys off d.ai_review (the real flag), NOT off logHtml: build_log() always
  // emits the deterministic report (per-map tables, findings) even when the AI call is
  // skipped, so logHtml is almost never empty. Without this, a skipped review (e.g. out of
  // API credits) silently drops the AI narrative with no explanation.
  const missingNotice = `<div class="coaching-missing">
       <strong>AI coaching unavailable for this run.</strong>
       <span>The coaching call didn't complete — usually out of Anthropic API credits, or a
       transient API error. Everything below is the full deterministic analysis; re-run the
       agent once credits are restored to get the AI narrative back.</span>
     </div>`;
  const coachingHtml = logHtml
    ? `<div class="coaching-block">${d.ai_review ? '' : missingNotice}<div class="agent-report-body">${logHtml}</div></div>`
    : `<div class="coaching-block">${missingNotice}</div>`;

  document.getElementById('leetify-page').innerHTML = `
    <p class="report-summary">${escHtml(d.summary || '')}</p>
    <div class="dim-strip">${dimChip('aim')}${dimChip('positioning')}${dimChip('utility')}</div>
    ${coachingHtml}
    ${watchlistHtml}
    <details class="data-fold" open>
      <summary class="data-fold-summary">Supporting data — stats, demos & death maps</summary>
      ${maps.length ? `
        <h3 class="detail-section-title">Per-map ${d.match_count ? `(last ${d.match_count})` : '(recent)'}</h3>
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

// ── Weather bot page ──────────────────────────────────────────────────────────
// Talks to the discord-weather container through /api/weather/* (backend proxy).
// weatherCfg is the working copy — locations/time edits accumulate here and are
// persisted with PUT /api/weather/config, which the bot applies immediately.
let weatherCfg = null;

function weatherError(res, err) {
  if (err) return `Network error reaching the webapp backend: ${err.message}`;
  switch (res && res.status) {
    case 502: return 'discord-weather container unreachable — check `docker ps` on rpi.';
    case 400: return null; // caller shows the validation message from the body
    default:  return `Request failed (HTTP ${res ? res.status : '?'}).`;
  }
}

async function renderWeather(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Weather Channel Bot Settings</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="weatherPreview(this)">Preview report</button>
          <button class="btn-run" onclick="weatherSendNow(this)">Send now</button>
          <button class="btn-refresh" onclick="renderWeather(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="weather-page"><div class="sec-loading">Loading bot settings…</div></div>
    </div>`;
  await loadWeather();
}

async function loadWeather() {
  const page = document.getElementById('weather-page');
  if (!page) return;
  let cfg, status;
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/weather/config'), fetch('/api/weather/status')]);
    if (!cRes.ok || !sRes.ok) {
      page.innerHTML = `<div class="sec-error">${weatherError(cRes.ok ? sRes : cRes)}</div>`;
      return;
    }
    cfg = await cRes.json();
    status = await sRes.json();
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${weatherError(null, e)}</div>`;
    return;
  }
  weatherCfg = cfg;

  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—';
  page.innerHTML = `
    <div class="sec-grid">
      <div class="sec-card ${status.enabled ? 'status-ok' : ''}${status.enabled ? '' : ' card-disabled'}">
        <div class="sec-card-header">
          <span class="sec-status-badge ${status.enabled ? 'status-ok' : 'status-unknown'}">${status.enabled ? 'ACTIVE' : 'PAUSED'}</span>
          <span class="sec-card-title">Daily post</span>
        </div>
        <div class="w-kv"><span>Next post</span><strong>${escHtml(fmt(status.next_post_at))}</strong></div>
        <div class="w-kv"><span>Last post</span><strong>${escHtml(fmt(status.last_post_at))}</strong></div>
        <div class="w-kv"><span>Last result</span><strong>${escHtml(status.last_status || '—')}</strong></div>
        <div class="sec-card-actions">
          <button class="btn-toggle ${status.enabled ? 'on' : 'off'}" onclick="weatherToggleEnabled(${!status.enabled}, this)">${status.enabled ? 'Enabled' : 'Disabled'}</button>
        </div>
      </div>

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Schedule &amp; webhook</span></div>
        <div class="w-field">
          <label for="w-time">Post time (${escHtml(cfg.timezone)})</label>
          <input type="time" id="w-time" class="w-input" value="${escHtml(cfg.post_time)}" />
        </div>
        <div class="w-field">
          <label for="w-message">Message text (sent above the embed — supports @everyone / @here)</label>
          <input type="text" id="w-message" class="w-input" value="${escHtml(cfg.message || '')}"
                 placeholder="e.g. @everyone — leave blank for no message text" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="w-webhook">Discord webhook ${cfg.webhook_configured ? `<span class="w-hint">current: ${escHtml(cfg.webhook_url)}</span>` : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="text" id="w-webhook" class="w-input" placeholder="paste a new webhook URL to replace, or leave blank" autocomplete="off" />
        </div>
        <div class="sec-card-actions">
          <button class="btn-run" onclick="weatherSave(this)">Save settings</button>
          <span id="w-save-msg" class="w-hint"></span>
        </div>
      </div>

      <div class="sec-card w-card-wide">
        <div class="sec-card-header"><span class="sec-card-title">Locations (${cfg.locations.length})</span></div>
        <div id="w-loc-list"></div>
        <div class="w-field">
          <label for="w-search">Add a location</label>
          <div class="w-search-row">
            <input type="text" id="w-search" class="w-input" placeholder="city / town name…"
                   onkeydown="if(event.key==='Enter')weatherGeocode()" autocomplete="off" />
            <button class="btn-view" onclick="weatherGeocode()">Search</button>
          </div>
          <div id="w-search-results"></div>
        </div>
        <p class="w-hint">Changes here are applied when you hit “Save settings”.</p>
      </div>
    </div>`;
  weatherRenderLocations();
}

function weatherRenderLocations() {
  const el = document.getElementById('w-loc-list');
  if (!el || !weatherCfg) return;
  el.innerHTML = weatherCfg.locations.map((l, i) => `
    <div class="w-loc-row">
      <span class="w-loc-name">📍 ${escHtml(l.name)}</span>
      <span class="w-loc-coords">${l.lat.toFixed(4)}, ${l.lon.toFixed(4)}</span>
      <button class="w-loc-del" title="Remove" onclick="weatherRemoveLocation(${i})">✕</button>
    </div>`).join('') || '<div class="sec-empty">No locations — add one below.</div>';
  const header = document.querySelector('.w-card-wide .sec-card-title');
  if (header) header.textContent = `Locations (${weatherCfg.locations.length})`;
}

function weatherRemoveLocation(i) {
  weatherCfg.locations.splice(i, 1);
  weatherRenderLocations();
}

async function weatherGeocode() {
  const q = (document.getElementById('w-search')?.value || '').trim();
  const out = document.getElementById('w-search-results');
  if (!q || !out) return;
  out.innerHTML = '<div class="sec-loading">Searching…</div>';
  let res, err;
  try { res = await fetch(`/api/weather/geocode?q=${encodeURIComponent(q)}`); } catch (e) { err = e; }
  if (!res || !res.ok) {
    out.innerHTML = `<div class="sec-error">${weatherError(res, err) || 'Search failed.'}</div>`;
    return;
  }
  const d = await res.json();
  const results = d.results || [];
  if (!results.length) { out.innerHTML = '<div class="sec-empty">No matches.</div>'; return; }
  out.innerHTML = results.map((r, i) => `
    <button class="w-geo-result" onclick='weatherAddLocation(${JSON.stringify(r).replace(/'/g, "&#39;")})'>
      ${escHtml(r.name)}${r.admin1 ? ', ' + escHtml(r.admin1) : ''} <span class="w-loc-coords">${escHtml(r.country)} · ${r.lat.toFixed(3)}, ${r.lon.toFixed(3)}</span>
    </button>`).join('');
}

function weatherAddLocation(r) {
  const suffix = r.country === 'US' && r.admin1 ? `, ${abbrevState(r.admin1)}` : (r.admin1 ? `, ${r.admin1}` : '');
  weatherCfg.locations.push({ name: `${r.name}${suffix}`, lat: r.lat, lon: r.lon });
  document.getElementById('w-search-results').innerHTML = '';
  document.getElementById('w-search').value = '';
  weatherRenderLocations();
}

const US_STATES = { 'New York': 'NY', 'New Jersey': 'NJ', 'Connecticut': 'CT', 'Pennsylvania': 'PA',
  'Louisiana': 'LA', 'Virginia': 'VA', 'California': 'CA', 'Texas': 'TX', 'Florida': 'FL',
  'Massachusetts': 'MA', 'Ohio': 'OH', 'North Carolina': 'NC', 'Georgia': 'GA', 'Maryland': 'MD' };
function abbrevState(s) { return US_STATES[s] || s; }

async function weatherSave(btn) {
  const msg = document.getElementById('w-save-msg');
  const body = {
    enabled: weatherCfg.enabled,
    post_time: document.getElementById('w-time').value || weatherCfg.post_time,
    timezone: weatherCfg.timezone,
    message: document.getElementById('w-message').value,
    locations: weatherCfg.locations,
    webhook_url: (document.getElementById('w-webhook').value || '').trim(),
  };
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/weather/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) {
    msg.textContent = 'Saved ✓ — rescheduled';
    setTimeout(loadWeather, 1200);
  } else if (res && res.status === 400) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = `Rejected: ${d.error || 'invalid settings'}`;
  } else {
    msg.textContent = weatherError(res, err);
  }
}

async function weatherToggleEnabled(enabled, btn) {
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/weather/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
    });
  } catch (e) { err = e; }
  if (res && res.ok) { await loadWeather(); }
  else { alert(weatherError(res, err) || 'Toggle failed.'); btn.disabled = false; }
}

async function weatherSendNow(btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Sending…';
  let res, err;
  try { res = await fetch('/api/weather/send', { method: 'POST' }); } catch (e) { err = e; }
  const d = res ? await res.json().catch(() => ({})) : {};
  if (res && res.ok && d.ok) {
    btn.textContent = 'Sent ✓';
  } else {
    btn.textContent = orig;
    alert(d.detail ? `Send failed: ${d.detail}` : (weatherError(res, err) || 'Send failed.'));
  }
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; loadWeather(); }, 3000);
}

// Renders the bot's exact payload as a Discord-style embed preview in a modal.
async function weatherPreview(btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Building…';
  let res, err;
  try { res = await fetch('/api/weather/preview'); } catch (e) { err = e; }
  btn.textContent = orig;
  btn.disabled = false;
  if (!res || !res.ok) { alert(weatherError(res, err) || 'Preview failed.'); return; }
  const d = await res.json();
  const emb = (d.payload && d.payload.embeds && d.payload.embeds[0]) || {};
  const mdBold = (s) => escHtml(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  const fields = (emb.fields || [])
    .filter(f => (f.name || '').replace(/[​\s]/g, '') !== '')  // hide grid spacers
    .map(f => `
    <div class="embed-field${f.inline ? ' inline' : ''}">
      <div class="embed-field-name">${escHtml(f.name)}</div>
      <div class="embed-field-value">${mdBold(f.value)}</div>
    </div>`).join('');

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">Preview — as it will appear in Discord</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="modal-body">
        ${d.payload.content ? `<div class="msg-content">${mdBold(d.payload.content).replace(/@(everyone|here)/g, '<span class="mention">@$1</span>')}</div>` : ''}
        <div class="embed-preview">
          <div class="embed-author">${escHtml(d.payload.username || 'Daily Weather Report')}</div>
          <div class="embed-title">${escHtml(emb.title || '')}</div>
          <div class="embed-desc">${mdBold(emb.description || '')}</div>
          <div class="embed-fields">${fields}</div>
          ${emb.footer ? `<div class="embed-footer">${escHtml(emb.footer.text)}</div>` : ''}
        </div>
        ${d.failed && d.failed.length ? `<div class="sec-error">No data for: ${escHtml(d.failed.join(', '))}</div>` : ''}
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// ── Shared helpers for the bot-container tabs ─────────────────────────────────
// The healthdigest/jellyfin/sports/cs2 bots all speak the same control-API
// contract as discord-weather, so their tabs share these (weather predates them
// and keeps its own weather* functions).
function botError(bot, res, err) {
  if (err) return `Network error reaching the webapp backend: ${err.message}`;
  switch (res && res.status) {
    case 502: return `discord-${bot} container unreachable — check \`docker ps\` on rpi.`;
    case 400: return null; // caller shows the validation message from the body
    default:  return `Request failed (HTTP ${res ? res.status : '?'}).`;
  }
}

// The "Daily post" status card every bot tab starts with.
function botStatusCard(bot, status) {
  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—';
  return `
      <div class="sec-card ${status.enabled ? 'status-ok' : ' card-disabled'}">
        <div class="sec-card-header">
          <span class="sec-status-badge ${status.enabled ? 'status-ok' : 'status-unknown'}">${status.enabled ? 'ACTIVE' : 'PAUSED'}</span>
          <span class="sec-card-title">Daily post</span>
        </div>
        <div class="w-kv"><span>Next post</span><strong>${escHtml(fmt(status.next_post_at))}</strong></div>
        <div class="w-kv"><span>Last post</span><strong>${escHtml(fmt(status.last_post_at))}</strong></div>
        <div class="w-kv"><span>Last result</span><strong>${escHtml(status.last_status || '—')}</strong></div>
        <div class="sec-card-actions">
          <button class="btn-toggle ${status.enabled ? 'on' : 'off'}" onclick="botToggleEnabled('${bot}', ${!status.enabled}, this)">${status.enabled ? 'Enabled' : 'Disabled'}</button>
        </div>
      </div>`;
}

// Reload function per bot, so toggle/send can refresh the right page.
const BOT_RELOAD = {};

async function botToggleEnabled(bot, enabled, btn) {
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch(`/api/${bot}/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
    });
  } catch (e) { err = e; }
  if (res && res.ok) { await (BOT_RELOAD[bot] || (() => {}))(); }
  else { alert(botError(bot, res, err) || 'Toggle failed.'); btn.disabled = false; }
}

async function botSendNow(bot, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Sending…';
  let res, err;
  try { res = await fetch(`/api/${bot}/send`, { method: 'POST' }); } catch (e) { err = e; }
  const d = res ? await res.json().catch(() => ({})) : {};
  if (res && res.ok && d.ok) {
    btn.textContent = 'Sent ✓';
  } else {
    btn.textContent = orig;
    alert(d.detail ? `Send failed: ${d.detail}` : (botError(bot, res, err) || 'Send failed.'));
  }
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; (BOT_RELOAD[bot] || (() => {}))(); }, 3000);
}

// Renders a bot's exact payload as a Discord-style embed preview in a modal
// (same rendering as weatherPreview).
async function botPreview(bot, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Building…';
  let res, err;
  try { res = await fetch(`/api/${bot}/preview`); } catch (e) { err = e; }
  btn.textContent = orig;
  btn.disabled = false;
  if (!res || !res.ok) {
    let detail = '';
    try { const d = await res.json(); detail = d.error || ''; } catch (_) {}
    alert(botError(bot, res, err) || detail || 'Preview failed.');
    return;
  }
  const d = await res.json();
  const emb = (d.payload && d.payload.embeds && d.payload.embeds[0]) || {};
  const mdBold = (s) => escHtml(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  const fields = (emb.fields || [])
    .filter(f => (f.name || '').replace(/[​\s]/g, '') !== '')  // hide grid spacers
    .map(f => `
    <div class="embed-field${f.inline ? ' inline' : ''}">
      <div class="embed-field-name">${escHtml(f.name)}</div>
      <div class="embed-field-value">${mdBold(f.value)}</div>
    </div>`).join('');

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">Preview — as it will appear in Discord</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="modal-body">
        ${d.payload.content ? `<div class="msg-content">${mdBold(d.payload.content).replace(/@(everyone|here)/g, '<span class="mention">@$1</span>')}</div>` : ''}
        <div class="embed-preview">
          <div class="embed-author">${escHtml(d.payload.username || '')}</div>
          <div class="embed-title">${escHtml(emb.title || '')}</div>
          <div class="embed-desc">${mdBold(emb.description || '')}</div>
          <div class="embed-fields">${fields}</div>
          ${emb.footer ? `<div class="embed-footer">${escHtml(emb.footer.text)}</div>` : ''}
        </div>
        ${d.failed && d.failed.length ? `<div class="sec-error">No data for: ${escHtml(d.failed.join(', '))}</div>` : ''}
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// Home-page status card body for a bot (same shape as loadWeatherCard).
async function loadBotCard(bot, elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  try {
    const res = await fetch(`/api/${bot}/status`);
    if (!res.ok) { el.textContent = `Bot unreachable — check discord-${bot} container.`; return; }
    const d = await res.json();
    const next = d.next_post_at
      ? new Date(d.next_post_at).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
      : null;
    const last = d.last_status || 'no posts yet';
    const lastBad = /fail/i.test(last);
    el.innerHTML = d.enabled
      ? `Next post: <strong>${escHtml(next || '…')}</strong> · Last: ${lastBad ? `<strong style="color:var(--red)">${escHtml(last)}</strong>` : escHtml(last)}`
      : 'Daily posts <strong>paused</strong>.';
  } catch {
    el.textContent = 'Unavailable.';
  }
}

// ── Health digest bot page ────────────────────────────────────────────────────
// Talks to the discord-healthdigest container through /api/healthdigest/*.
let hdCfg = null;
BOT_RELOAD.healthdigest = loadHealthdigest;

async function renderHealthdigest(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Homelab Health Bot Settings</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="botPreview('healthdigest', this)">Preview digest</button>
          <button class="btn-run" onclick="botSendNow('healthdigest', this)">Send now</button>
          <button class="btn-refresh" onclick="renderHealthdigest(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="hd-page"><div class="sec-loading">Loading bot settings…</div></div>
    </div>`;
  await loadHealthdigest();
}

async function loadHealthdigest() {
  const page = document.getElementById('hd-page');
  if (!page) return;
  let cfg, status;
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/healthdigest/config'), fetch('/api/healthdigest/status')]);
    if (!cRes.ok || !sRes.ok) {
      page.innerHTML = `<div class="sec-error">${botError('healthdigest', cRes.ok ? sRes : cRes)}</div>`;
      return;
    }
    cfg = await cRes.json();
    status = await sRes.json();
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${botError('healthdigest', null, e)}</div>`;
    return;
  }
  hdCfg = cfg;

  page.innerHTML = `
    <div class="sec-grid">
      ${botStatusCard('healthdigest', status)}

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Schedule &amp; webhook</span></div>
        <div class="w-field">
          <label for="hd-time">Post time (${escHtml(cfg.timezone)})</label>
          <input type="time" id="hd-time" class="w-input" value="${escHtml(cfg.post_time)}" />
        </div>
        <div class="w-field">
          <label for="hd-mode">Post mode</label>
          <select id="hd-mode" class="w-input">
            <option value="always" ${cfg.post_mode === 'always' ? 'selected' : ''}>Always — post every day</option>
            <option value="alerts_only" ${cfg.post_mode === 'alerts_only' ? 'selected' : ''}>Alerts only — skip quiet days</option>
          </select>
        </div>
        <div class="w-field">
          <label for="hd-message">Message text (sent above the embed — supports @everyone / @here)</label>
          <input type="text" id="hd-message" class="w-input" value="${escHtml(cfg.message || '')}"
                 placeholder="e.g. @here — leave blank for no message text" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="hd-webhook">Discord webhook ${cfg.webhook_configured ? `<span class="w-hint">current: ${escHtml(cfg.webhook_url)}</span>` : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="text" id="hd-webhook" class="w-input" placeholder="paste a new webhook URL to replace, or leave blank" autocomplete="off" />
        </div>
        <div class="sec-card-actions">
          <button class="btn-run" onclick="hdSave(this)">Save settings</button>
          <span id="hd-save-msg" class="w-hint"></span>
        </div>
      </div>

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Data sources</span></div>
        <div class="w-field">
          <label for="hd-pihole-pw">Pi-hole password ${cfg.pihole_password_configured ? '<span class="w-hint">configured ✓ — leave blank to keep</span>' : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="password" id="hd-pihole-pw" class="w-input" placeholder="paste to replace, or leave blank" autocomplete="new-password" />
        </div>
        <div class="w-field">
          <label for="hd-top-n">Top blocked domains shown (1–10)</label>
          <input type="number" id="hd-top-n" class="w-input" min="1" max="10" value="${cfg.top_blocked_count}" />
        </div>
        <div class="w-field">
          <label><input type="checkbox" id="hd-fresh" ${cfg.request_fresh_report ? 'checked' : ''} />
            Kick a fresh doctor run before posting (adds up to ~90s)</label>
        </div>
        <p class="w-hint">Host/VPN/update data comes from homelab-doctor's report (refreshed every
        30 min from opti); Pi-hole stats are queried live. Changes apply on “Save settings”.</p>
      </div>
    </div>`;
}

// ── Jellyfin arrivals bot page ────────────────────────────────────────────────
// Talks to the discord-jellyfin container through /api/jellyfin/*.
let jfCfg = null;
BOT_RELOAD.jellyfin = loadJellyfin;

async function renderJellyfin(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Jellyfin Arrivals Bot Settings</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="botPreview('jellyfin', this)">Preview digest</button>
          <button class="btn-run" onclick="botSendNow('jellyfin', this)">Send now</button>
          <button class="btn-refresh" onclick="renderJellyfin(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="jf-page"><div class="sec-loading">Loading bot settings…</div></div>
    </div>`;
  await loadJellyfin();
}

async function loadJellyfin() {
  const page = document.getElementById('jf-page');
  if (!page) return;
  let cfg, status;
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/jellyfin/config'), fetch('/api/jellyfin/status')]);
    if (!cRes.ok || !sRes.ok) {
      page.innerHTML = `<div class="sec-error">${botError('jellyfin', cRes.ok ? sRes : cRes)}</div>`;
      return;
    }
    cfg = await cRes.json();
    status = await sRes.json();
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${botError('jellyfin', null, e)}</div>`;
    return;
  }
  jfCfg = cfg;

  page.innerHTML = `
    <div class="sec-grid">
      ${botStatusCard('jellyfin', status)}

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Schedule &amp; webhook</span></div>
        <div class="w-field">
          <label for="jf-time">Post time (${escHtml(cfg.timezone)})</label>
          <input type="time" id="jf-time" class="w-input" value="${escHtml(cfg.post_time)}" />
        </div>
        <div class="w-field">
          <label for="jf-message">Message text (sent above the embed — supports @everyone / @here)</label>
          <input type="text" id="jf-message" class="w-input" value="${escHtml(cfg.message || '')}"
                 placeholder="e.g. @here — leave blank for no message text" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="jf-webhook">Discord webhook ${cfg.webhook_configured ? `<span class="w-hint">current: ${escHtml(cfg.webhook_url)}</span>` : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="text" id="jf-webhook" class="w-input" placeholder="paste a new webhook URL to replace, or leave blank" autocomplete="off" />
        </div>
        <div class="sec-card-actions">
          <button class="btn-run" onclick="jfSave(this)">Save settings</button>
          <span id="jf-save-msg" class="w-hint"></span>
        </div>
      </div>

      <div class="sec-card">
        <div class="sec-card-header">
          <span class="sec-card-title">Jellyfin server</span>
          <div class="sec-card-actions"><button class="btn-view" onclick="jfCheck(this)">Test connection</button></div>
        </div>
        <div class="w-field">
          <label for="jf-url">Server URL</label>
          <input type="text" id="jf-url" class="w-input" value="${escHtml(cfg.jellyfin_url)}" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="jf-key">API key ${cfg.api_key_configured ? '<span class="w-hint">configured ✓ — leave blank to keep</span>' : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="password" id="jf-key" class="w-input" placeholder="paste to replace, or leave blank" autocomplete="new-password" />
        </div>
        <div class="w-field">
          <label for="jf-max">Max items listed (1–25)</label>
          <input type="number" id="jf-max" class="w-input" min="1" max="25" value="${cfg.max_items}" />
        </div>
        <div class="w-field">
          <label><input type="checkbox" id="jf-empty" ${cfg.post_when_empty ? 'checked' : ''} />
            Post a "Nothing new" embed on empty days (off = skip quiet days)</label>
        </div>
        <p class="w-hint" id="jf-check-msg">Changes apply on “Save settings”.</p>
      </div>
    </div>`;
}

async function jfCheck(btn) {
  const msg = document.getElementById('jf-check-msg');
  btn.disabled = true;
  let res, err;
  try { res = await fetch('/api/jellyfin/check'); } catch (e) { err = e; }
  btn.disabled = false;
  const d = res ? await res.json().catch(() => ({})) : {};
  msg.textContent = (res && res.ok && d.ok)
    ? `Connected ✓ — ${d.server_name} (v${d.version})`
    : `Connection failed: ${d.error || botError('jellyfin', res, err) || 'unknown error'}`;
}

async function jfSave(btn) {
  const msg = document.getElementById('jf-save-msg');
  const body = {
    enabled: jfCfg.enabled,
    post_time: document.getElementById('jf-time').value || jfCfg.post_time,
    timezone: jfCfg.timezone,
    message: document.getElementById('jf-message').value,
    webhook_url: (document.getElementById('jf-webhook').value || '').trim(),
    jellyfin_url: (document.getElementById('jf-url').value || '').trim(),
    api_key: document.getElementById('jf-key').value,
    max_items: parseInt(document.getElementById('jf-max').value, 10) || jfCfg.max_items,
    post_when_empty: document.getElementById('jf-empty').checked,
  };
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/jellyfin/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) {
    msg.textContent = 'Saved ✓ — rescheduled';
    setTimeout(loadJellyfin, 1200);
  } else if (res && res.status === 400) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = `Rejected: ${d.error || 'invalid settings'}`;
  } else {
    msg.textContent = botError('jellyfin', res, err);
  }
}

// ── Sports bot page ───────────────────────────────────────────────────────────
// Talks to the discord-sports container through /api/sports/*. spCfg is the
// working copy — team edits accumulate here and are persisted with PUT config.
let spCfg = null;
BOT_RELOAD.sports = loadSports;

// NBA only by design — mirror any league added to the bot's LEAGUES map here
const SPORTS_LEAGUES = ['nba'];
const SPORTS_EMOJI = { nba: '🏀' };

async function renderSports(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Sports Bot Settings</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="botPreview('sports', this)">Preview report</button>
          <button class="btn-run" onclick="botSendNow('sports', this)">Send now</button>
          <button class="btn-refresh" onclick="renderSports(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="sp-page"><div class="sec-loading">Loading bot settings…</div></div>
    </div>`;
  await loadSports();
}

async function loadSports() {
  const page = document.getElementById('sp-page');
  if (!page) return;
  let cfg, status;
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/sports/config'), fetch('/api/sports/status')]);
    if (!cRes.ok || !sRes.ok) {
      page.innerHTML = `<div class="sec-error">${botError('sports', cRes.ok ? sRes : cRes)}</div>`;
      return;
    }
    cfg = await cRes.json();
    status = await sRes.json();
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${botError('sports', null, e)}</div>`;
    return;
  }
  spCfg = cfg;

  page.innerHTML = `
    <div class="sec-grid">
      ${botStatusCard('sports', status)}

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Schedule &amp; webhook</span></div>
        <div class="w-field">
          <label for="sp-time">Post time (${escHtml(cfg.timezone)})</label>
          <input type="time" id="sp-time" class="w-input" value="${escHtml(cfg.post_time)}" />
        </div>
        <div class="w-field">
          <label for="sp-message">Message text (sent above the embed — supports @everyone / @here)</label>
          <input type="text" id="sp-message" class="w-input" value="${escHtml(cfg.message || '')}"
                 placeholder="e.g. @here — leave blank for no message text" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="sp-webhook">Discord webhook ${cfg.webhook_configured ? `<span class="w-hint">current: ${escHtml(cfg.webhook_url)}</span>` : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="text" id="sp-webhook" class="w-input" placeholder="paste a new webhook URL to replace, or leave blank" autocomplete="off" />
        </div>
        <div class="sec-card-actions">
          <button class="btn-run" onclick="spSave(this)">Save settings</button>
          <span id="sp-save-msg" class="w-hint"></span>
        </div>
      </div>

      <div class="sec-card w-card-wide">
        <div class="sec-card-header"><span class="sec-card-title">Teams (${cfg.teams.length})</span></div>
        <div id="sp-team-list"></div>
        <div class="w-field">
          <label for="sp-search">Add a team</label>
          <div class="w-search-row">
            <select id="sp-league" class="w-input" style="max-width:7rem">
              ${SPORTS_LEAGUES.map(l => `<option value="${l}">${SPORTS_EMOJI[l]} ${l.toUpperCase()}</option>`).join('')}
            </select>
            <input type="text" id="sp-search" class="w-input" placeholder="team name…"
                   onkeydown="if(event.key==='Enter')spSearchTeams()" autocomplete="off" />
            <button class="btn-view" onclick="spSearchTeams()">Search</button>
          </div>
          <div id="sp-search-results"></div>
        </div>
        <p class="w-hint">Changes here are applied when you hit “Save settings”.</p>
      </div>
    </div>`;
  spRenderTeams();
}

function spRenderTeams() {
  const el = document.getElementById('sp-team-list');
  if (!el || !spCfg) return;
  el.innerHTML = spCfg.teams.map((t, i) => `
    <div class="w-loc-row">
      <span class="w-loc-name">${SPORTS_EMOJI[t.league] || '🏟️'} ${escHtml(t.name)}</span>
      <span class="w-loc-coords">${escHtml(t.league.toUpperCase())} · ${escHtml(t.abbrev || '')}</span>
      <button class="w-loc-del" title="Remove" onclick="spRemoveTeam(${i})">✕</button>
    </div>`).join('') || '<div class="sec-empty">No teams — add one below.</div>';
  const header = document.querySelector('#sp-page .w-card-wide .sec-card-title');
  if (header) header.textContent = `Teams (${spCfg.teams.length})`;
}

function spRemoveTeam(i) {
  spCfg.teams.splice(i, 1);
  spRenderTeams();
}

async function spSearchTeams() {
  const league = document.getElementById('sp-league')?.value || 'nba';
  const q = (document.getElementById('sp-search')?.value || '').trim();
  const out = document.getElementById('sp-search-results');
  if (!q || !out) return;
  out.innerHTML = '<div class="sec-loading">Searching…</div>';
  let res, err;
  try { res = await fetch(`/api/sports/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(q)}`); } catch (e) { err = e; }
  if (!res || !res.ok) {
    out.innerHTML = `<div class="sec-error">${botError('sports', res, err) || 'Search failed.'}</div>`;
    return;
  }
  const d = await res.json();
  const results = d.results || [];
  if (!results.length) { out.innerHTML = '<div class="sec-empty">No matches.</div>'; return; }
  out.innerHTML = results.map(r => `
    <button class="w-geo-result" onclick='spAddTeam(${JSON.stringify(r).replace(/'/g, "&#39;")})'>
      ${SPORTS_EMOJI[r.league] || '🏟️'} ${escHtml(r.name)} <span class="w-loc-coords">${escHtml(r.league.toUpperCase())} · ${escHtml(r.abbrev)}</span>
    </button>`).join('');
}

function spAddTeam(r) {
  spCfg.teams.push(r);
  document.getElementById('sp-search-results').innerHTML = '';
  document.getElementById('sp-search').value = '';
  spRenderTeams();
}

async function spSave(btn) {
  const msg = document.getElementById('sp-save-msg');
  const body = {
    enabled: spCfg.enabled,
    post_time: document.getElementById('sp-time').value || spCfg.post_time,
    timezone: spCfg.timezone,
    message: document.getElementById('sp-message').value,
    webhook_url: (document.getElementById('sp-webhook').value || '').trim(),
    teams: spCfg.teams,
  };
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/sports/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) {
    msg.textContent = 'Saved ✓ — rescheduled';
    setTimeout(loadSports, 1200);
  } else if (res && res.status === 400) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = `Rejected: ${d.error || 'invalid settings'}`;
  } else {
    msg.textContent = botError('sports', res, err);
  }
}

// ── HLTV games-of-the-day bot page ────────────────────────────────────────────
// Talks to the discord-hltv container through /api/hltv/*. Only matches with a
// VRS top-N team or a top-tier tournament make the daily post.
let hltvCfg = null;
BOT_RELOAD.hltv = loadHltv;

async function renderHltv(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>HLTV Games of the Day Bot Settings</h1>
        <div class="sec-header-actions">
          <button class="btn-view" onclick="botPreview('hltv', this)">Preview digest</button>
          <button class="btn-run" onclick="botSendNow('hltv', this)">Send now</button>
          <button class="btn-refresh" onclick="renderHltv(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="hltv-page"><div class="sec-loading">Loading bot settings…</div></div>
    </div>`;
  await loadHltv();
}

async function loadHltv() {
  const page = document.getElementById('hltv-page');
  if (!page) return;
  let cfg, status;
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/hltv/config'), fetch('/api/hltv/status')]);
    if (!cRes.ok || !sRes.ok) {
      page.innerHTML = `<div class="sec-error">${botError('hltv', cRes.ok ? sRes : cRes)}</div>`;
      return;
    }
    cfg = await cRes.json();
    status = await sRes.json();
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${botError('hltv', null, e)}</div>`;
    return;
  }
  hltvCfg = cfg;

  const tierBox = (t) => `
    <label style="margin-right:1rem"><input type="checkbox" class="hltv-tier" value="${t}"
      ${cfg.tiers.includes(t) ? 'checked' : ''} /> Tier ${t.toUpperCase()}</label>`;

  page.innerHTML = `
    <div class="sec-grid">
      ${botStatusCard('hltv', status)}

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Schedule &amp; webhook</span></div>
        <div class="w-field">
          <label for="hltv-time">Post time (${escHtml(cfg.timezone)})</label>
          <input type="time" id="hltv-time" class="w-input" value="${escHtml(cfg.post_time)}" />
        </div>
        <div class="w-field">
          <label for="hltv-message">Message text (sent above the embed — supports @everyone / @here)</label>
          <input type="text" id="hltv-message" class="w-input" value="${escHtml(cfg.message || '')}"
                 placeholder="e.g. @here — leave blank for no message text" autocomplete="off" />
        </div>
        <div class="w-field">
          <label for="hltv-webhook">Discord webhook ${cfg.webhook_configured ? `<span class="w-hint">current: ${escHtml(cfg.webhook_url)}</span>` : '<span class="w-hint w-warn">not configured!</span>'}</label>
          <input type="text" id="hltv-webhook" class="w-input" placeholder="paste a new webhook URL to replace, or leave blank" autocomplete="off" />
        </div>
        <div class="sec-card-actions">
          <button class="btn-run" onclick="hltvSave(this)">Save settings</button>
          <span id="hltv-save-msg" class="w-hint"></span>
        </div>
      </div>

      <div class="sec-card">
        <div class="sec-card-header">
          <span class="sec-card-title">Match filter</span>
          <div class="sec-card-actions"><button class="btn-view" onclick="hltvShowVrs(this)">Show VRS list</button></div>
        </div>
        <div class="w-field">
          <label for="hltv-topn">Always include teams in the VRS top… (1–100)</label>
          <input type="number" id="hltv-topn" class="w-input" min="1" max="100" value="${cfg.vrs_top_n}" />
        </div>
        <div class="w-field">
          <label>Always include tournaments of…</label>
          <div>${['s', 'a', 'b'].map(tierBox).join('')}</div>
        </div>
        <div class="w-field">
          <label><input type="checkbox" id="hltv-empty" ${cfg.post_when_empty ? 'checked' : ''} />
            Post a "no notable games" embed on quiet days (off = skip them)</label>
        </div>
        <p class="w-hint" id="hltv-vrs-note">VRS = Valve Regional Standings (official ranking, refreshed ~weekly).</p>
        <div id="hltv-vrs-list"></div>
      </div>
    </div>`;
}

async function hltvShowVrs(btn) {
  const out = document.getElementById('hltv-vrs-list');
  if (!out) return;
  btn.disabled = true;
  out.innerHTML = '<div class="sec-loading">Loading VRS…</div>';
  let res, err;
  try { res = await fetch('/api/hltv/vrs'); } catch (e) { err = e; }
  btn.disabled = false;
  const d = res ? await res.json().catch(() => ({})) : {};
  if (!res || !res.ok) {
    out.innerHTML = `<div class="sec-error">${escHtml(d.error || botError('hltv', res, err) || 'VRS unavailable.')}</div>`;
    return;
  }
  out.innerHTML = `
    <p class="w-hint">As of ${escHtml(d.as_of)}:</p>
    ${(d.teams || []).map((t, i) => `
      <div class="w-loc-row">
        <span class="w-loc-name">#${i + 1} ${escHtml(t)}</span>
      </div>`).join('')}`;
}

async function hltvSave(btn) {
  const msg = document.getElementById('hltv-save-msg');
  const tiers = Array.from(document.querySelectorAll('.hltv-tier'))
    .filter(cb => cb.checked).map(cb => cb.value);
  const body = {
    enabled: hltvCfg.enabled,
    post_time: document.getElementById('hltv-time').value || hltvCfg.post_time,
    timezone: hltvCfg.timezone,
    message: document.getElementById('hltv-message').value,
    webhook_url: (document.getElementById('hltv-webhook').value || '').trim(),
    vrs_top_n: parseInt(document.getElementById('hltv-topn').value, 10) || hltvCfg.vrs_top_n,
    tiers,
    post_when_empty: document.getElementById('hltv-empty').checked,
  };
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/hltv/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) {
    msg.textContent = 'Saved ✓ — rescheduled';
    setTimeout(loadHltv, 1200);
  } else if (res && res.status === 400) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = `Rejected: ${d.error || 'invalid settings'}`;
  } else {
    msg.textContent = botError('hltv', res, err);
  }
}

async function hdSave(btn) {
  const msg = document.getElementById('hd-save-msg');
  const body = {
    enabled: hdCfg.enabled,
    post_time: document.getElementById('hd-time').value || hdCfg.post_time,
    timezone: hdCfg.timezone,
    message: document.getElementById('hd-message').value,
    webhook_url: (document.getElementById('hd-webhook').value || '').trim(),
    post_mode: document.getElementById('hd-mode').value,
    pihole_password: document.getElementById('hd-pihole-pw').value,
    top_blocked_count: parseInt(document.getElementById('hd-top-n').value, 10) || hdCfg.top_blocked_count,
    request_fresh_report: document.getElementById('hd-fresh').checked,
  };
  btn.disabled = true;
  let res, err;
  try {
    res = await fetch('/api/healthdigest/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) {
    msg.textContent = 'Saved ✓ — rescheduled';
    setTimeout(loadHealthdigest, 1200);
  } else if (res && res.status === 400) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = `Rejected: ${d.error || 'invalid settings'}`;
  } else {
    msg.textContent = botError('healthdigest', res, err);
  }
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
