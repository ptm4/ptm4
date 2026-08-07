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

// ── Actions: toasts + confirmation ────────────────────────────────────────────
// Every state-changing button on the dashboard goes through these two. The rule they
// encode: an action never happens silently and never reports success it didn't verify.

let toastSeq = 0;
// Text-only by default. Callers that want markup pass { allowHtml: true } and are
// responsible for escHtml()-ing every interpolated value — toast messages routinely
// carry error strings echoed from reports and agents, which is untrusted text.
function toast(msg, tone = 'ok', { sticky = false, allowHtml = false } = {}) {
  let stack = document.getElementById('toastStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toastStack';
    stack.className = 'toast-stack';
    stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
  }
  const el = document.createElement('div');
  el.className = 'toast';
  el.dataset.s = tone;
  el.id = `toast-${++toastSeq}`;
  el.innerHTML = `<span class="toast-msg"></span><button class="toast-x" aria-label="Dismiss">✕</button>`;
  const msgEl = el.querySelector('.toast-msg');
  if (allowHtml) msgEl.innerHTML = msg; else msgEl.textContent = msg;
  const close = () => el.remove();
  el.querySelector('.toast-x').addEventListener('click', close);
  stack.appendChild(el);
  // Errors persist until dismissed — a failure that vanishes on its own is a failure
  // nobody reads.
  if (!sticky && tone === 'ok') setTimeout(close, 5000);
  return el;
}

// Containers whose restart or update has blast radius beyond themselves. Touching these
// needs the name typed out, and says what will actually break. Wording stays neutral
// about which operation it is: both the restart and the update modal render these, and
// an update takes longer than a restart, so "~15s" would be a lie in half the cases.
const CRITICAL_CONTAINERS = {
  pihole: 'Brief LAN-wide DNS blips — Pi-hole is this network\'s only DNS *and* DHCP server.',
  webapp: 'This dashboard stops responding while its container comes back. The operation still completes on the host.',
  'nginx-webapp': 'This dashboard goes offline while TLS comes back.',
  bitwarden: 'Vaultwarden is unavailable while it comes back — password access included.',
  'bitwarden-db': 'Vaultwarden\'s database — Vaultwarden may error until it reconnects.',
  'nginx-bitwarden': 'Vaultwarden\'s TLS front end goes down briefly.',
  gluetun: 'Tears down the VPN tunnel; every *arr and qBittorrent loses network until it re-establishes, and the forwarded port may change.',
  'notes-api': 'The Notes app at /notes/ is unavailable while it comes back.',
};

// Containers that serve this page: touching one kills the response to the very request
// that asked for it. Observed both ways — the fetch fails outright, OR nginx outlives the
// backend and answers 502/504 — so both branches have to recognise it, or a self-update
// that actually succeeded gets reported as a red failure.
const SELF_CONTAINERS = new Set(['webapp', 'nginx-webapp']);
const selfKillNotice = (eName, verb) =>
  `Connection dropped — expected when ${verb} <b>${eName}</b>: the container serving this ` +
  `page was replaced. It is almost certainly back; reload to confirm.`;

// Promise<boolean>. Reuses the existing .modal styling; adds a danger variant and an
// optional type-the-name gate for the critical set above. `body` is caller-built HTML
// (callers must escHtml() their interpolations); title/labels/typed-name are escaped
// here. Only one modal at a time — a double-click on an action button used to stack
// two overlays, and the second answer went nowhere.
function confirmAction({ title, body, tone = 'warn', confirmLabel = 'Confirm', requireTyped = null }) {
  if (document.querySelector('.confirm-overlay')) return Promise.resolve(false);
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay open confirm-overlay';
    overlay.innerHTML = `
      <div class="modal confirm-modal" data-s="${tone}" role="dialog" aria-modal="true" aria-label="${escHtml(title)}">
        <div class="modal-header">
          <span class="modal-title">${escHtml(title)}</span>
          <button class="modal-close" aria-label="Cancel">✕</button>
        </div>
        <div class="modal-body">
          <div class="confirm-body">${body}</div>
          ${requireTyped ? `
            <label class="confirm-type">Type <code>${escHtml(requireTyped)}</code> to confirm
              <input type="text" autocomplete="off" spellcheck="false" />
            </label>` : ''}
        </div>
        <div class="confirm-actions">
          <button class="btn-mini" data-act="cancel">Cancel</button>
          <button class="btn-mini btn-danger" data-act="ok" ${requireTyped ? 'disabled' : ''}>${escHtml(confirmLabel)}</button>
        </div>
      </div>`;

    const done = (val) => {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      resolve(val);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(false);
      if (e.key === 'Enter' && !overlay.querySelector('[data-act="ok"]').disabled) done(true);
    };

    overlay.querySelector('.modal-close').addEventListener('click', () => done(false));
    overlay.querySelector('[data-act="cancel"]').addEventListener('click', () => done(false));
    overlay.querySelector('[data-act="ok"]').addEventListener('click', () => done(true));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });
    document.addEventListener('keydown', onKey);

    const input = overlay.querySelector('.confirm-type input');
    if (input) {
      input.addEventListener('input', () => {
        overlay.querySelector('[data-act="ok"]').disabled = input.value.trim() !== requireTyped;
      });
    }

    document.body.appendChild(overlay);
    (input || overlay.querySelector('[data-act="ok"]')).focus();
  });
}

// Restart one container through its host's architecture agent.
// host/name arrive from data- attributes and reports — treat as untrusted text
// everywhere they land in HTML.
async function restartContainer(host, name, btn) {
  const danger = CRITICAL_CONTAINERS[name];
  const eName = escHtml(name), eHost = escHtml(host);
  const ok = await confirmAction({
    title: `Restart ${name}?`,
    tone: danger ? 'crit' : 'warn',
    confirmLabel: 'Restart',
    requireTyped: danger ? name : null,
    body: `<p>Restarts <code>${eName}</code> on <b>${eHost}</b>.</p>` +
          (danger ? `<p class="confirm-danger">⚠ ${escHtml(danger)}</p>` : '<p>Downtime is a few seconds.</p>'),
  });
  if (!ok) return;

  const orig = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  const pending = toast(`Restarting <b>${eName}</b> on ${eHost}… (~15s)`, 'warn',
    { sticky: true, allowHtml: true });

  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/restart-container`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ container: name }),
      // The backend caps the agent call at 55s; without a client-side cap a wedged
      // nginx left the sticky toast and disabled button hanging on browser defaults.
      signal: AbortSignal.timeout(70_000),
    });
    const d = await res.json().catch(() => ({}));
    pending.remove();
    if (res.ok && d.ok) {
      toast(`<b>${eName}</b> restarted on ${eHost}${d.took_ms ? ` in ${(d.took_ms / 1000).toFixed(1)}s` : ''}.`,
        'ok', { allowHtml: true });
      loadContainers();
    } else if (SELF_CONTAINERS.has(name) && (res.status === 502 || res.status === 504)) {
      // nginx can outlive the backend and answer 502 for it — not a failed restart.
      toast(selfKillNotice(eName, 'restarting'), 'warn', { sticky: true, allowHtml: true });
    } else {
      toast(restartError(res.status, d, host, name), 'crit', { sticky: true, allowHtml: true });
    }
  } catch (e) {
    pending.remove();
    // The dashboard restarting itself kills its own in-flight response; that is not a
    // failure of the restart, so say so rather than claiming an error.
    const msg = SELF_CONTAINERS.has(name)
      ? selfKillNotice(eName, 'restarting')
      : (e.name === 'TimeoutError' || e.name === 'AbortError')
        ? `No response after 70s — the restart of <b>${eName}</b> may still have completed; check the containers panel.`
        : `Restart of <b>${eName}</b> failed: ${escHtml(e.message)}`;
    toast(msg, 'warn', { sticky: true, allowHtml: true });
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

// Map a failed restart onto the thing the operator actually has to go fix.
// Returns HTML (callers pass allowHtml) — every dynamic value is escaped here.
function restartError(status, d, host, name) {
  const detail = escHtml(d.error || `HTTP ${status}`);
  const eHost = escHtml(host), eName = escHtml(name);
  if (status === 403) return `Restart refused: the agent on ${eHost} has no token set. Add HL_ARCH_AGENT_TOKEN to /etc/hl-arch-agent.env and restart hl-arch-agent.`;
  if (status === 401) return `Restart unauthorized: the webapp's HL_ARCH_INGEST_TOKEN doesn't match ${eHost}'s HL_ARCH_AGENT_TOKEN.`;
  if (status === 404 && /no container/i.test(detail)) return `${eHost} has no container named <b>${eName}</b> — Force Sync the agent and retry.`;
  if (status === 404) return `The agent on ${eHost} is too old for restarts (needs v0.2.0).`;
  return `Restart of <b>${eName}</b> failed: ${detail}`;
}

// update_available comes from software-latest.json, which the collector rewrites once a
// day (plus the kick below). Without this, a container you just updated keeps wearing an
// "update" chip until that run lands. Suppression is in-memory only: a page reload before
// the collector re-runs brings the stale chip back, which is annoying but honest.
const RECENT_UPDATES = new Map();
const UPDATE_SUPPRESS_MS = 30 * 60 * 1000;
function recentlyUpdated(host, name) {
  const t = RECENT_UPDATES.get(`${host}/${name}`);
  return t != null && Date.now() - t < UPDATE_SUPPRESS_MS;
}

// One container update with no UI chrome: fetch + result classification only. Shared
// by the single ⬆ button (updateContainer) and the cockpit's update-all loop, so the
// two can never drift on RECENT_UPDATES bookkeeping or timeout values.
// Resolves to { ok, changed, status, d, err } — never rejects.
async function performUpdate(host, name) {
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/update-container`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ container: name }),
      // Between the backend's 220s cap and nginx's 240s read timeout for this path.
      signal: AbortSignal.timeout(230_000),
    });
    const d = await res.json().catch(() => ({}));
    if (res.ok && d.ok) {
      RECENT_UPDATES.set(`${host}/${name}`, Date.now());
      return { ok: true, changed: !!d.changed, status: res.status, d };
    }
    return { ok: false, changed: false, status: res.status, d };
  } catch (e) {
    return { ok: false, changed: false, status: null, d: {}, err: e };
  }
}

// Pull the newest image for one container and recreate it, through its host's agent.
// Same untrusted-text rules as restartContainer: host/name/image come from reports.
async function updateContainer(host, name, image, btn) {
  const danger = CRITICAL_CONTAINERS[name];
  const eName = escHtml(name), eHost = escHtml(host);
  const eImg = escHtml(image || 'its image');
  const ok = await confirmAction({
    title: `Update ${name}?`,
    tone: danger ? 'crit' : 'warn',
    confirmLabel: 'Pull & recreate',
    requireTyped: danger ? name : null,
    body: `<p>Pulls the newest <code>${eImg}</code> on <b>${eHost}</b>, then recreates
           <code>${eName}</code> from it. Only this container is touched.</p>
           <p class="tile-sub">The pull can take a couple of minutes; downtime is the few
           seconds the new container needs to start.</p>` +
          (danger ? `<p class="confirm-danger">⚠ ${escHtml(danger)}</p>` : ''),
  });
  if (!ok) return;

  const orig = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  const pending = toast(`Updating <b>${eName}</b> on ${eHost} — pulling image… (up to ~2 min)`,
    'warn', { sticky: true, allowHtml: true });

  const r = await performUpdate(host, name);
  pending.remove();
  if (r.ok) {
    const d = r.d;
    toast(r.changed
      ? `<b>${eName}</b> updated on ${eHost} (<span class="mono">${escHtml(d.before || '?')}</span> → <span class="mono">${escHtml(d.after || '?')}</span>)${d.took_ms ? ` in ${(d.took_ms / 1000).toFixed(0)}s` : ''}.`
      : `<b>${eName}</b> already runs the newest image — nothing was recreated.`,
      'ok', { allowHtml: true });
    loadContainers();
    // Re-run the inventory collector so the chips reflect reality within minutes
    // instead of at tomorrow's scheduled run. Fire-and-forget: if it fails, the only
    // cost is that the chip waits for the daily run.
    fetch('/api/runners/software-inventory/run', { method: 'POST' }).catch(() => {});
  } else if (r.err) {
    const e = r.err;
    const msg = SELF_CONTAINERS.has(name)
      ? selfKillNotice(eName, 'updating')
      : (e.name === 'TimeoutError' || e.name === 'AbortError')
        ? `No response after 230s — the update of <b>${eName}</b> may still be running; check the containers panel shortly.`
        : `Update of <b>${eName}</b> failed: ${escHtml(e.message)}`;
    toast(msg, 'warn', { sticky: true, allowHtml: true });
  } else if (SELF_CONTAINERS.has(name) && (r.status === 502 || r.status === 504)) {
    // nginx outlived the backend and answered for it — the update itself was fine.
    toast(selfKillNotice(eName, 'updating'), 'warn', { sticky: true, allowHtml: true });
  } else {
    toast(updateError(r.status, r.d, host, name), 'crit', { sticky: true, allowHtml: true });
  }
  if (btn) { btn.disabled = false; btn.textContent = orig; }
}

// Map a failed update onto the thing the operator actually has to go fix.
// Returns HTML (callers pass allowHtml) — every dynamic value is escaped here.
function updateError(status, d, host, name) {
  const detail = escHtml(d.error || `HTTP ${status}`);
  const eHost = escHtml(host), eName = escHtml(name);
  if (status === 403) return `Update refused: the agent on ${eHost} has no token set. Add HL_ARCH_AGENT_TOKEN to /etc/hl-arch-agent.env and restart hl-arch-agent.`;
  if (status === 401) return `Update unauthorized: the webapp's HL_ARCH_INGEST_TOKEN doesn't match ${eHost}'s HL_ARCH_AGENT_TOKEN.`;
  if (status === 404 && /no container/i.test(detail)) return `${eHost} has no container named <b>${eName}</b> — Force Sync the agent and retry.`;
  if (status === 404) return `The agent on ${eHost} is too old for updates (needs v0.3.0) — reinstall hl-arch-agent.py there.`;
  if (status === 409) return `Can't update <b>${eName}</b>: ${detail}`;
  if (status === 503 && d.stage === 'preflight') return `Update aborted before touching <b>${eName}</b>: ${detail}`;
  if (d.stage === 'pull') return `Image pull failed on ${eHost} — <b>${eName}</b> was NOT touched. ${detail}`;
  if (d.stage === 'up') return `Recreate failed on ${eHost} after the pull: ${detail}`;
  return `Update of <b>${eName}</b> failed: ${detail}`;
}

// Pause / resume Pi-hole ad blocking. Pausing always carries a timer server-side, so
// blocking comes back on its own even if this tab is closed.
async function toggleBlocking(enable, seconds = 300) {
  if (!enable) {
    const ok = await confirmAction({
      title: 'Pause ad blocking?',
      tone: 'warn',
      confirmLabel: `Pause ${seconds / 60} min`,
      body: `<p>Disables Pi-hole's blocklists for <b>${seconds / 60} minutes</b>, then resumes automatically.</p>
             <p class="tile-sub">DNS resolution and DHCP are unaffected — only filtering pauses.</p>`,
    });
    if (!ok) return;
  }
  try {
    const res = await fetch('/api/pihole/blocking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enable, seconds }),
      signal: AbortSignal.timeout(15_000),
    });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) { toast(`Pi-hole: ${d.error || 'HTTP ' + res.status}`, 'crit', { sticky: true }); return; }
    toast(enable ? 'Ad blocking resumed.' : `Ad blocking paused — resumes in ${Math.round((d.timer || seconds) / 60)} min.`, 'ok');
    loadPihole();
  } catch (e) {
    toast(`Pi-hole request failed: ${e.message}`, 'crit', { sticky: true });
  }
}

// ── Cockpit: fleet control hub (#cockpit) ─────────────────────────────────────
// One tab that can do everything remote-hands while away: reboot a host (typed
// confirm here, ZFS-DKMS guard server-side), kick the nightly apt unit and watch its
// log, restart the few allowlisted services, bulk-apply container updates, and wake
// opti via WoL. The cards deliberately run on CIFS-free data (/api/agents live
// probes + /api/vitals in-memory ring buffer); the software-latest chips ride opti's
// share and degrade to "unavailable" when it is down — which is exactly the moment
// this tab must still render, to show the Wake button.

// Analogue of CRITICAL_CONTAINERS: what actually breaks while the host is down.
const HOST_REBOOT_IMPACT = {
  opti: 'ZFS pool and \\\\opti\\red drop for every host — reports, container data, Samba and the dispatcher all stall until it returns (~2–3 min). The agent runs a ZFS-DKMS guard first and refuses if the next kernel has no zfs module.',
  rpi: 'LAN DNS + DHCP (Pi-hole) AND this dashboard go down (~2 min). Your WireGuard tunnel survives — it terminates on the router. rpi boots from an SD card: small chance it does not come back, so reboot it remotely only if you must.',
  noblenumbat: 'Jellyfin, the *arr stack and the VPN go down (~2 min). vpn-stack-heal re-establishes the tunnel within 2 minutes of boot.',
};

// Units whose restart is disruptive enough for the typed gate, with blast radius.
const CRITICAL_UNITS = new Set(['smbd.service', 'docker.service']);
const UNIT_IMPACT = {
  'smbd.service': 'Samba drops briefly — hosts with \\\\opti\\red mounted may see I/O errors for a few seconds. (This is also the recovery lever for stale CIFS handles.)',
  'docker.service': 'Restarts the Docker daemon AND every container on the host.',
};
const UNIT_LABELS = {
  'hl-agent-dispatcher.service': 'dispatcher',
  'hl-arch-agent.service': 'agent',
  'smbd.service': 'samba',
  'docker.service': 'docker',
  'vpn-stack-heal.service': 'vpn heal',
};

const cockpitState = {
  agents: null,        // /api/agents rows by host id (reachability + capabilities)
  vitals: null,        // /api/vitals rollup: host -> {latest}
  sw: null,            // software-latest rows by host (chips; null when opti is down)
  llama: null,         // android LLM status (best-effort)
  updCount: 0,         // pending image updates -> "Update all (N)" button
  busy: new Set(),     // hosts with an op in flight; their buttons render disabled
  watch: {},           // host -> {label, t0} while waiting for it to come back
  apt: {},             // host -> last /apt-status snapshot (progress + log tail)
};
let cockpitTimer = null;
const ckSleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ckUptime = (s) => {
  if (s == null) return null;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
};
const agentTooOld = (host, what) =>
  `The agent on ${escHtml(host)} is too old for ${what} (needs v0.4.0) — reinstall hl-arch-agent.py there.`;

function renderCockpit(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header" style="margin-bottom:var(--s4);padding-bottom:var(--s3)">
        <h1>Cockpit</h1>
        <div class="sec-header-actions">
          <button class="btn-mini" id="ck-doctor">▶ Doctor</button>
          <button class="btn-mini" id="ck-sync">⟳ Sync agents</button>
          <button class="btn-mini" id="ck-pihole" title="Pause Pi-hole blocking for 5 minutes">⏸ Pi-hole 5 min</button>
          <button class="btn-mini" id="ck-updall" style="display:none">⬆ Update all</button>
        </div>
      </div>
      <div class="tile-sub" id="ck-cluster-status"></div>
      <div class="cockpit-grid" id="ck-grid">
        <div class="tile"><div class="sk sk-line w40"></div><div class="sk sk-line w80"></div><div class="sk sk-line w60"></div></div>
      </div>
      <div class="tile ck-monitors" id="ck-monitors">
        <div class="tile-head">Monitors <span class="tile-sub" style="margin:0">· Uptime Kuma</span></div>
        <div class="tile-sub">Loading…</div>
      </div>
    </div>`;
  document.getElementById('ck-doctor').addEventListener('click', (e) => ribbonRun(e.currentTarget));
  document.getElementById('ck-sync').addEventListener('click', (e) => ribbonSync(e.currentTarget));
  document.getElementById('ck-pihole').addEventListener('click', () => toggleBlocking(false, 300));
  document.getElementById('ck-updall').addEventListener('click', () => updateAllContainers());
  loadCockpit();
  if (cockpitTimer) clearInterval(cockpitTimer);
  cockpitTimer = setInterval(() => {
    // Self-clearing: no point polling four endpoints for a tab nobody is looking at.
    if (location.hash.replace('#', '') !== 'cockpit') {
      clearInterval(cockpitTimer);
      cockpitTimer = null;
      return;
    }
    loadCockpit();
  }, 30_000);
}

async function loadCockpit() {
  // agents + vitals are the load-bearing pair (both CIFS-free). Everything else is
  // garnish on a short timeout: when opti is down these fetches must fail fast, not
  // hang the tab on a dead CIFS mount.
  const [agents, vitals, sw, containers, llama] = await Promise.all([
    fetch('/api/agents', { signal: AbortSignal.timeout(8000) }).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/vitals', { signal: AbortSignal.timeout(5000) }).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/runners/software-latest', { signal: AbortSignal.timeout(5000) }).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/containers', { signal: AbortSignal.timeout(5000) }).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/llama/status', { signal: AbortSignal.timeout(5000) }).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  if (agents) cockpitState.agents = Object.fromEntries((agents.hosts || []).map(h => [h.id, h]));
  if (vitals) cockpitState.vitals = vitals.hosts || {};
  cockpitState.sw = sw ? Object.fromEntries((sw.hosts || []).map(h => [h.host, h])) : cockpitState.sw;
  cockpitState.llama = llama;
  if (containers) {
    cockpitState.updCount = (containers.hosts || []).reduce((n, h) =>
      n + (h.containers || []).filter(c =>
        c.update_available && !recentlyUpdated(h.host, c.name) && !SELF_CONTAINERS.has(c.name)).length, 0);
  }
  renderCockpitCards();
  loadCockpitMonitors();
}

// Kuma monitors panel: headline count + a dot-chip per monitor. Down/pending sort
// first so a problem is the first thing on the panel, not hidden in a green sea.
async function loadCockpitMonitors() {
  const el = document.getElementById('ck-monitors');
  if (!el) return;
  let d = null;
  try {
    d = await fetch('/api/uptime', { signal: AbortSignal.timeout(10_000) })
      .then(r => r.ok ? r.json() : null);
  } catch (_) {}
  const head = `<div class="tile-head">Monitors <span class="tile-sub" style="margin:0">· <a
    href="http://rpi.lan:3001/" target="_blank" rel="noopener">Uptime Kuma</a></span></div>`;
  if (!d?.ok) {
    el.innerHTML = `${head}<div class="tile-sub">Unavailable${d?.error ? ` — ${escHtml(d.error)}` : ''}.</div>`;
    return;
  }
  const rank = { down: 0, pending: 1, maintenance: 2, up: 3 };
  const list = [...(d.monitors || [])].sort((a, b) =>
    (rank[a.status] ?? 4) - (rank[b.status] ?? 4) || a.name.localeCompare(b.name));
  const tone = d.down ? 'crit' : d.pending ? 'warn' : 'ok';
  const dot = (s) => s === 'up' ? 'ok' : s === 'down' ? 'crit' : 'warn';
  el.innerHTML = `${head}
    <div class="ck-mon-summary"><span class="pill" data-s="${tone}">${d.up}/${d.total} up${d.down ? ` · ${d.down} down` : ''}${d.pending ? ` · ${d.pending} pending` : ''}</span></div>
    <div class="ck-mon-grid">${list.map(m => `
      <span class="ck-mon" data-s="${m.status}" title="${escHtml(m.name)} — ${escHtml(m.status)}${m.ms != null ? `, ${m.ms}ms` : ''}">
        <span class="cdot" data-s="${dot(m.status)}"></span>${escHtml(m.name)}${m.ms != null ? ` <span class="ck-mon-ms">${m.ms}ms</span>` : ''}
      </span>`).join('')}</div>`;
}

function cockpitCard(id) {
  const a = cockpitState.agents?.[id];
  const v = cockpitState.vitals?.[id]?.latest;
  const m = cockpitState.sw?.[id]?.metrics;
  const reachable = !!a?.reachable;
  const hasControls = Array.isArray(a?.allowed_units); // null/undefined -> pre-0.4.0 agent
  const busy = cockpitState.busy.has(id);
  const eId = escHtml(id);

  const stats = v ? [
    v.uptime_s != null ? `up ${ckUptime(v.uptime_s)}` : null,
    v.load1 != null ? `load ${v.load1.toFixed(2)}` : null,
    v.cpu_pct != null ? `cpu ${v.cpu_pct}%` : null,
    v.mem_pct != null ? `mem ${v.mem_pct}%` : null,
    v.temp_c != null ? `${Math.round(v.temp_c)}°C` : null,
  ].filter(Boolean).join(' · ') : 'no vitals';

  const chips = m ? [
    m.reboot_required ? `<span class="chip" data-s="warn" title="${escHtml(m.reboot_pkgs || '')}">reboot req</span>` : '',
    m.pending_count ? `<span class="chip">${m.pending_count} pkg${m.security_count ? ` · <b style="color:var(--crit)">${m.security_count} sec</b>` : ''}</span>` : '',
    m.image_update_count ? `<span class="chip">${m.image_update_count} image${m.image_update_count > 1 ? 's' : ''}</span>` : '',
  ].filter(Boolean).join(' ') || '<span class="tile-sub" style="margin:0">patched · no reboot needed</span>'
    : '<span class="tile-sub" style="margin:0">package info unavailable</span>';

  const watch = cockpitState.watch[id];
  const watchHtml = watch
    ? `<div class="tile-sub ck-status">⏳ ${escHtml(watch.label)} — down ${Math.round((Date.now() - watch.t0) / 1000)}s…</div>` : '';

  const apt = cockpitState.apt[id];
  let aptHtml = '';
  if (apt) {
    const lastLine = (apt.log_tail || []).slice(-1)[0] || '';
    aptHtml = apt.running
      ? `<div class="tile-sub ck-status">⏳ apt running… <span class="mono">${escHtml(lastLine)}</span></div>`
      : `<details class="ck-aptlog"><summary class="tile-sub">apt log · ${escHtml(apt.finished_at || 'last run')}</summary>
           <pre class="mono">${escHtml((apt.log_tail || []).join('\n'))}</pre></details>`;
  }

  // Real shell access goes through Cockpit (the app) on rpi:9090 — its own PAM
  // login, NOT this dashboard's no-auth posture. rpi is local; opti/noblenumbat are
  // federated remote hosts (/etc/cockpit/machines.d/99-homelab.json on rpi).
  const termUrl = id === 'rpi'
    ? 'https://rpi.lan:9090/system/terminal'
    : `https://rpi.lan:9090/@${encodeURIComponent(id)}/system/terminal`;
  const termBtn = reachable
    ? `<a class="btn-mini" href="${termUrl}" target="_blank" rel="noopener"
         title="Terminal on ${eId} via Cockpit (rpi:9090, system login)">⌨ Terminal</a>` : '';

  let buttons;
  if (reachable && hasControls) {
    const rebootHot = !!m?.reboot_required;
    buttons = `
      <button class="btn-mini btn-danger${rebootHot ? ' ck-reboot-hot' : ''}" data-ck-act="reboot" data-ck-host="${eId}"
        ${busy ? 'disabled' : ''} title="Reboot ${eId}${rebootHot ? ' — a pending upgrade wants this' : ''}">Reboot</button>
      <button class="btn-mini" data-ck-act="apt" data-ck-host="${eId}" ${busy ? 'disabled' : ''}
        title="Run homelab-autoupdate (apt update + upgrade) on ${eId} now">Apt upgrade</button>
      ${(a.allowed_units || []).map(u => `<button class="btn-mini" data-ck-act="unit" data-ck-host="${eId}"
        data-ck-unit="${escHtml(u)}" ${busy ? 'disabled' : ''} title="systemctl restart ${escHtml(u)}">↻ ${escHtml(UNIT_LABELS[u] || u)}</button>`).join('')}
      ${termBtn}`;
  } else if (reachable) {
    buttons = `<span class="tile-sub" style="margin:0">controls need agent v0.4.0 — reinstall hl-arch-agent.py on ${eId}</span>${termBtn}`;
  } else {
    // Down. Offer Wake if any REACHABLE agent advertises this host as a wake target.
    const wakeable = Object.values(cockpitState.agents || {})
      .some(h => h.reachable && (h.wake_targets || []).includes(id));
    buttons = wakeable
      ? `<button class="btn-mini" data-ck-act="wake" data-ck-host="${eId}" ${busy ? 'disabled' : ''}
           title="Broadcast a Wake-on-LAN magic packet for ${eId}">⚡ Wake</button>`
      : `<span class="tile-sub" style="margin:0">unreachable — no WoL for this host, physical access needed if it is off</span>`;
  }

  return `<div class="tile ck-card">
    <div class="ck-card-head">
      <span class="mono ck-host">${eId}</span>
      <span class="tile-sub" style="margin:0">${escHtml(HOST_ROLES[id] || '')}</span>
      <span class="spacer"></span>
      <span class="pill" data-s="${reachable ? 'ok' : 'crit'}">${reachable ? 'up' : 'unreachable'}</span>
      ${a?.agent_version ? `<span class="chip" title="hl-arch-agent version">v${escHtml(a.agent_version)}</span>` : ''}
    </div>
    <div class="tile-sub ck-stats">${escHtml(stats)}</div>
    <div class="ck-chips">${chips}</div>
    ${watchHtml}${aptHtml}
    <div class="ck-actions">${buttons}</div>
  </div>`;
}

function cockpitAndroidCard() {
  const up = !!cockpitState.llama;
  return `<div class="tile ck-card">
    <div class="ck-card-head">
      <span class="mono ck-host">android</span>
      <span class="tile-sub" style="margin:0">${escHtml(HOST_ROLES.android || 'local LLM')}</span>
      <span class="spacer"></span>
      <span class="pill" data-s="${up ? 'ok' : 'warn'}">${up ? 'up' : 'offline'}</span>
    </div>
    <div class="tile-sub">Status display only — no agent on this host, and it is often
      offline by design (it is a phone).</div>
  </div>`;
}

function renderCockpitCards() {
  const grid = document.getElementById('ck-grid');
  if (!grid) return;
  grid.innerHTML = ['opti', 'rpi', 'noblenumbat'].map(cockpitCard).join('') + cockpitAndroidCard();
  const updBtn = document.getElementById('ck-updall');
  if (updBtn) {
    updBtn.style.display = cockpitState.updCount ? '' : 'none';
    updBtn.textContent = `⬆ Update all (${cockpitState.updCount})`;
  }
  grid.querySelectorAll('button[data-ck-act]').forEach(b => {
    b.addEventListener('click', () => {
      const host = b.dataset.ckHost;
      if (b.dataset.ckAct === 'reboot') rebootHost(host);
      else if (b.dataset.ckAct === 'apt') aptUpgrade(host);
      else if (b.dataset.ckAct === 'unit') restartServiceUnit(host, b.dataset.ckUnit);
      else if (b.dataset.ckAct === 'wake') wakeHost(host);
    });
  });
}

// Poll until the host answers again; drives the "down Xs" line on its card.
// For rpi (the host serving this page) /api/health is the recovery signal — its own
// agent row would need the backend up anyway.
async function watchHostReturn(host, { label = 'rebooting' } = {}) {
  cockpitState.watch[host] = { label, t0: Date.now() };
  cockpitState.busy.add(host);
  renderCockpitCards();
  const t0 = cockpitState.watch[host].t0;
  const giveUpMs = 10 * 60 * 1000;
  while (Date.now() - t0 < giveUpMs) {
    await ckSleep(5000);
    if (cockpitState.watch[host]?.t0 !== t0) return; // superseded by a newer watch
    let back = false;
    try {
      if (host === 'rpi') {
        // Must parse as JSON, not just res.ok: during the boot window nginx serves
        // the 200 "_restarting" holding page, which would read as a false recovery.
        const r = await fetch('/api/health', { signal: AbortSignal.timeout(4000) });
        back = r.ok && !!(await r.json().catch(() => null));
      }
      if (!back) {
        const a = await fetch('/api/agents', { signal: AbortSignal.timeout(8000) })
          .then(r => r.ok ? r.json() : null);
        if (a) {
          cockpitState.agents = Object.fromEntries((a.hosts || []).map(x => [x.id, x]));
          back = !!cockpitState.agents[host]?.reachable;
        }
      }
    } catch (_) { /* still down — the gap is the honest answer */ }
    renderCockpitCards();
    if (back) {
      delete cockpitState.watch[host];
      cockpitState.busy.delete(host);
      toast(`<b>${escHtml(host)}</b> is back online after ${Math.round((Date.now() - t0) / 1000)}s.`,
        'ok', { allowHtml: true });
      loadCockpit();
      loadContainers(); // harmless no-op unless the Home tab's table is mounted
      return;
    }
  }
  delete cockpitState.watch[host];
  cockpitState.busy.delete(host);
  renderCockpitCards();
  toast(`<b>${escHtml(host)}</b> has not come back after 10 minutes — check it directly.`,
    'crit', { sticky: true, allowHtml: true });
}

async function rebootHost(host) {
  const eHost = escHtml(host);
  const ok = await confirmAction({
    title: `Reboot ${host}?`,
    tone: 'crit',
    confirmLabel: 'Reboot',
    requireTyped: host,
    body: `<p>Reboots <b>${eHost}</b> now. Expect ~2 minutes of downtime.</p>
           <p class="confirm-danger">⚠ ${escHtml(HOST_REBOOT_IMPACT[host] || '')}</p>`,
  });
  if (!ok) return;
  cockpitState.busy.add(host);
  renderCockpitCards();
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/reboot`, {
      method: 'POST',
      signal: AbortSignal.timeout(20_000), // backend caps the agent call at 15s
    });
    const d = await res.json().catch(() => ({}));
    if (res.ok && d.ok) {
      toast(`Reboot accepted — <b>${eHost}</b> goes down in ~2s. Watching for it to return…`,
        'warn', { allowHtml: true });
      watchHostReturn(host);
      return;
    }
    cockpitState.busy.delete(host);
    renderCockpitCards();
    if (res.status === 409 && d.stage === 'zfs-guard') {
      toast(`Reboot of <b>${eHost}</b> REFUSED by the ZFS guard: ${escHtml(d.error || '')}`,
        'crit', { sticky: true, allowHtml: true });
    } else if (res.status === 404) {
      toast(agentTooOld(host, 'reboots'), 'crit', { sticky: true, allowHtml: true });
    } else {
      toast(`Reboot of <b>${eHost}</b> failed: ${escHtml(d.error || `HTTP ${res.status}`)}`,
        'crit', { sticky: true, allowHtml: true });
    }
  } catch (e) {
    if (host === 'rpi') {
      // The host serving this page: a dropped connection here IS the reboot working
      // (same reasoning as SELF_CONTAINERS for container ops).
      toast('Connection dropped — expected when rebooting <b>rpi</b>, it serves this page. Watching for it to return…',
        'warn', { sticky: true, allowHtml: true });
      watchHostReturn(host);
      return;
    }
    cockpitState.busy.delete(host);
    renderCockpitCards();
    toast(`Reboot request to <b>${eHost}</b> failed: ${escHtml(e.message)}`,
      'crit', { sticky: true, allowHtml: true });
  }
}

async function aptUpgrade(host) {
  const eHost = escHtml(host);
  const ok = await confirmAction({
    title: `Apt upgrade on ${host}?`,
    tone: 'warn',
    confirmLabel: 'Upgrade now',
    body: `<p>Runs the nightly <code>homelab-autoupdate</code> unit on <b>${eHost}</b> now
           (apt update + full upgrade + autoremove) — the same code path that already runs
           unattended at 02:00.</p>
           <p class="tile-sub">Progress and the log tail show on the card. If the upgrade
           wants a reboot, the Reboot button lights up afterwards.</p>`,
  });
  if (!ok) return;
  cockpitState.busy.add(host);
  renderCockpitCards();
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/apt-upgrade`, {
      method: 'POST', signal: AbortSignal.timeout(15_000),
    });
    const d = await res.json().catch(() => ({}));
    if (!res.ok || !d.ok) {
      cockpitState.busy.delete(host);
      renderCockpitCards();
      toast(res.status === 404
        ? agentTooOld(host, 'apt upgrades')
        : `Apt upgrade on <b>${eHost}</b> failed to start: ${escHtml(d.error || `HTTP ${res.status}`)}`,
        'crit', { sticky: true, allowHtml: true });
      return;
    }
    if (d.already_running) {
      toast(`An apt run is already in progress on <b>${eHost}</b> — attaching to it.`,
        'warn', { allowHtml: true });
    }
    await pollAptStatus(host);
  } catch (e) {
    cockpitState.busy.delete(host);
    renderCockpitCards();
    toast(`Apt upgrade on <b>${eHost}</b> failed: ${escHtml(e.message)}`,
      'crit', { sticky: true, allowHtml: true });
  }
}

async function pollAptStatus(host) {
  const eHost = escHtml(host);
  const t0 = Date.now();
  const giveUpMs = 30 * 60 * 1000; // a big upgrade on the Pi genuinely runs long
  while (Date.now() - t0 < giveUpMs) {
    await ckSleep(5000);
    let st = null;
    try {
      st = await fetch(`/api/agents/${encodeURIComponent(host)}/apt-status`,
        { signal: AbortSignal.timeout(10_000) }).then(r => r.ok ? r.json() : null);
    } catch (_) { /* transient — keep polling */ }
    if (!st) continue;
    cockpitState.apt[host] = st;
    renderCockpitCards();
    if (!st.running) {
      cockpitState.busy.delete(host);
      renderCockpitCards();
      const good = st.result === 'success' || st.exit_status === '0';
      toast(good
        ? `Apt upgrade finished on <b>${eHost}</b>${st.reboot_required ? ' — <b>reboot required</b> to finish.' : '.'}`
        : `Apt upgrade on <b>${eHost}</b> ended with result "${escHtml(st.result || '?')}" — see the log on its card.`,
        good ? 'ok' : 'crit', { allowHtml: true, sticky: !good });
      loadCockpit();
      return;
    }
  }
  cockpitState.busy.delete(host);
  renderCockpitCards();
  toast(`Apt upgrade on <b>${eHost}</b> still running after 30 min — check /var/log/homelab-autoupdate.log on the host.`,
    'warn', { sticky: true, allowHtml: true });
}

async function restartServiceUnit(host, unit) {
  const eHost = escHtml(host), eUnit = escHtml(unit);
  const impact = UNIT_IMPACT[unit];
  const selfAgent = unit === 'hl-arch-agent.service';
  const ok = await confirmAction({
    title: `Restart ${unit}?`,
    tone: CRITICAL_UNITS.has(unit) ? 'crit' : 'warn',
    confirmLabel: 'Restart',
    requireTyped: CRITICAL_UNITS.has(unit) ? unit : null,
    body: `<p>Runs <code>systemctl restart ${eUnit}</code> on <b>${eHost}</b>.</p>` +
          (impact ? `<p class="confirm-danger">⚠ ${escHtml(impact)}</p>` : '') +
          (selfAgent ? '<p class="tile-sub">This is the agent itself — it responds first and restarts ~2s later.</p>' : '') +
          (unit === 'vpn-stack-heal.service' ? '<p class="tile-sub">vpn-stack-heal is a oneshot: this simply runs the heal check now.</p>' : ''),
  });
  if (!ok) return;
  cockpitState.busy.add(host);
  renderCockpitCards();
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/restart-service`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ unit }),
      signal: AbortSignal.timeout(170_000), // above the backend's 160s, below nginx's 240s
    });
    const d = await res.json().catch(() => ({}));
    if (res.ok && d.ok) {
      if (d.self_restart) {
        toast(`Agent on <b>${eHost}</b> is restarting itself — its card refreshes shortly.`,
          'warn', { allowHtml: true });
        setTimeout(loadCockpit, 6000);
      } else {
        toast(`<code>${eUnit}</code> restarted on <b>${eHost}</b>${d.took_ms ? ` in ${(d.took_ms / 1000).toFixed(1)}s` : ''} (${escHtml(d.before || '?')} → ${escHtml(d.after || '?')}).`,
          'ok', { allowHtml: true });
      }
    } else if (res.status === 403 && d.allowed) {
      toast(`<code>${eUnit}</code> is not allowlisted on ${eHost} (allowed: ${escHtml((d.allowed || []).join(', '))}).`,
        'crit', { sticky: true, allowHtml: true });
    } else if (res.status === 403) {
      toast(`Restart refused: the agent on ${eHost} has no token set. Add HL_ARCH_AGENT_TOKEN to /etc/hl-arch-agent.env and restart hl-arch-agent.`,
        'crit', { sticky: true });
    } else if (res.status === 401) {
      toast(`Restart unauthorized: the webapp's HL_ARCH_INGEST_TOKEN doesn't match ${eHost}'s HL_ARCH_AGENT_TOKEN.`,
        'crit', { sticky: true });
    } else if (res.status === 404 && !/not found on/i.test(d.error || '')) {
      toast(agentTooOld(host, 'service restarts'), 'crit', { sticky: true, allowHtml: true });
    } else {
      toast(`Restart of <code>${eUnit}</code> on ${eHost} failed: ${escHtml(d.error || `HTTP ${res.status}`)}`,
        'crit', { sticky: true, allowHtml: true });
    }
  } catch (e) {
    toast((e.name === 'TimeoutError' || e.name === 'AbortError')
      ? `No response after 170s — the restart of <code>${eUnit}</code> may still be running on ${eHost}.`
      : `Restart request failed: ${escHtml(e.message)}`,
      'warn', { sticky: true, allowHtml: true });
  } finally {
    cockpitState.busy.delete(host);
    renderCockpitCards();
  }
}

async function wakeHost(host) {
  const eHost = escHtml(host);
  const ok = await confirmAction({
    title: `Wake ${host}?`,
    tone: 'warn',
    confirmLabel: 'Send magic packet',
    body: `<p>Asks a healthy peer agent to broadcast a Wake-on-LAN packet for <b>${eHost}</b>.</p>
           <p class="tile-sub">Booting takes 1–3 minutes; the card watches for it to return.</p>`,
  });
  if (!ok) return;
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(host)}/wake`, {
      method: 'POST', signal: AbortSignal.timeout(15_000),
    });
    const d = await res.json().catch(() => ({}));
    if (res.ok && d.ok) {
      toast(`Magic packet sent for <b>${eHost}</b> via ${escHtml(d.sent_by || '?')} — watching for boot…`,
        'ok', { allowHtml: true });
      watchHostReturn(host, { label: 'waking' });
    } else {
      toast(`Wake failed: ${escHtml(d.error || `HTTP ${res.status}`)}`, 'crit', { sticky: true });
    }
  } catch (e) {
    toast(`Wake request failed: ${escHtml(e.message)}`, 'crit', { sticky: true });
  }
}

// Bulk-apply every pending image update, sequentially, via the same performUpdate
// the single ⬆ button uses. Fetches its own fresh /api/containers — never relies on
// another tab having loaded anything.
async function updateAllContainers() {
  let d = null;
  try {
    d = await fetch('/api/containers', { signal: AbortSignal.timeout(10_000) })
      .then(r => r.ok ? r.json() : null);
  } catch (_) {}
  if (!d?.hosts?.length) {
    toast('Container data unavailable — is opti reachable?', 'crit', { sticky: true });
    return;
  }
  const targets = d.hosts.flatMap(h => (h.containers || [])
    .filter(c => c.update_available && !recentlyUpdated(h.host, c.name) && !SELF_CONTAINERS.has(c.name))
    .map(c => ({ host: h.host, name: c.name })));
  if (!targets.length) {
    toast('Nothing to update — every container already runs its newest image.', 'ok');
    return;
  }
  const criticals = targets.filter(t => CRITICAL_CONTAINERS[t.name]);
  const ok = await confirmAction({
    title: `Update ${targets.length} container${targets.length > 1 ? 's' : ''}?`,
    tone: criticals.length ? 'crit' : 'warn',
    confirmLabel: 'Update all',
    requireTyped: criticals.length ? 'update all' : null,
    body: `<p>Pulls and recreates, one at a time:</p>
           <ul class="ck-updlist">${targets.map(t => `<li><code>${escHtml(t.name)}</code>
             <span class="tile-sub">on ${escHtml(t.host)}</span>${CRITICAL_CONTAINERS[t.name] ? ' ⚠' : ''}</li>`).join('')}</ul>` +
          (criticals.length ? `<p class="confirm-danger">⚠ Includes containers with blast radius: ${criticals.map(t => escHtml(t.name)).join(', ')}.</p>` : '') +
          '<p class="tile-sub">webapp / nginx-webapp are excluded — updating the dashboard mid-run would kill the run itself; use their own ⬆ buttons.</p>',
  });
  if (!ok) return;
  const btn = document.getElementById('ck-updall');
  if (btn) btn.disabled = true;
  const statusEl = () => document.getElementById('ck-cluster-status');
  const failures = [];
  let changed = 0;
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    const el = statusEl();
    if (el) el.innerHTML = `⬆ ${i + 1}/${targets.length} — updating <code>${escHtml(t.name)}</code> on ${escHtml(t.host)}…`;
    const r = await performUpdate(t.host, t.name);
    if (r.ok) {
      if (r.changed) changed++;
    } else {
      // Continue past failures — one bad pull must not strand the rest of the queue.
      failures.push(`<code>${escHtml(t.name)}</code> (${escHtml(r.err ? r.err.message : (r.d?.error || `HTTP ${r.status}`))})`);
    }
  }
  const el = statusEl();
  if (el) el.innerHTML = '';
  if (btn) btn.disabled = false;
  if (failures.length) {
    toast(`Update-all finished: ${targets.length - failures.length}/${targets.length} ok, ${changed} changed. Failed: ${failures.join(', ')}.`,
      'crit', { sticky: true, allowHtml: true });
  } else {
    toast(`Update-all finished: ${targets.length} container${targets.length > 1 ? 's' : ''} processed, ${changed} actually changed.`,
      'ok', { allowHtml: true });
  }
  // One inventory kick for the whole batch, not one per container.
  fetch('/api/runners/software-inventory/run', { method: 'POST' }).catch(() => {});
  loadCockpit();
  loadContainers();
}

// ── Logs tab: Dozzle, embedded ───────────────────────────────────────────────
// Dozzle is proxied same-origin at /dozzle (nginx-wg.conf) precisely so this iframe
// works — an http://rpi.lan:9999 frame inside this https page would be blocked as
// mixed content. The iframe is the whole tab; Dozzle's own UI does the rest.
function renderLogs(view) {
  view.innerHTML = `
    <div class="page-security logs-page">
      <div class="sec-header" style="margin-bottom:var(--s3);padding-bottom:var(--s3)">
        <h1>Container logs</h1>
        <div class="sec-header-actions">
          <span class="sec-refresh-label">Dozzle · rpi + noblenumbat (opti runs no docker)</span>
          <a class="btn-mini" href="/dozzle/" target="_blank" rel="noopener">Open full ↗</a>
        </div>
      </div>
      <iframe class="logs-frame" src="/dozzle/" title="Dozzle container logs"></iframe>
    </div>`;
}

// ── Router ────────────────────────────────────────────────────────────────────
const routes = {
  home:     renderHome,
  cockpit:  renderCockpit,
  logs:     renderLogs,
  security: renderSecurity,
  reports:  renderReports,
  bots:     renderBots,
  leetify:  renderLeetify,
  llm:      renderLlm,
  links:    renderLinks,
};

// The five bots were five sidebar entries and five near-identical page shells. They are
// now one tabbed page. Each bot's *config form* is genuinely different (weather has
// location, healthdigest has Pi-hole, sports has leagues…) so those renderers are kept
// as-is — only the surrounding chrome and navigation were unified.
const BOTS = [
  { id: 'weather',      label: 'Weather',  icon: '🌤️', render: renderWeather },
  { id: 'healthdigest', label: 'Health',   icon: '🩺', render: renderHealthdigest },
  { id: 'jellyfin',     label: 'Jellyfin', icon: '🎬', render: renderJellyfin },
  { id: 'sports',       label: 'Sports',   icon: '🏟️', render: renderSports },
  { id: 'hltv',         label: 'HLTV',     icon: '🎯', render: renderHltv },
];

// Old per-bot hashes stay valid as deep links into the right tab, so existing
// bookmarks don't 404 into the Home page.
BOTS.forEach(b => { routes[b.id] = (view) => renderBots(view, b.id); });

// Quick-link shortcuts shown on the Home page. Edit here (could graduate to /api/links later).
// Every LAN service worth a bookmark, grouped. URLs use the Pi-hole local DNS names
// (`pihole-FTL --config dns.hosts`) rather than raw IPs, so a host that changes address
// doesn't break this list — the one exception is the router, which has no DNS record.
// `fav: true` also surfaces the entry in the compact Home tile.
const LINK_GROUPS = [
  { group: 'Infrastructure', links: [
    { label: 'Router (Archer BE3600)', url: 'http://192.168.1.1/webpages/index.html', icon: '📶' },
    { label: 'Pi-hole',            url: 'http://rpi.lan/admin',                        icon: '🛡️', fav: true },
    // Renamed from "Cockpit (rpi)" — this dashboard now has its own #cockpit tab,
    // and two things called Cockpit in one palette was a mis-click waiting to happen.
    { label: 'Cockpit console (rpi:9090)', url: 'https://rpi.lan:9090/',               icon: '🖥️', fav: true },
    { label: 'Uptime Kuma',        url: 'http://rpi.lan:3001/',                        icon: '📈', fav: true },
    { label: 'Dozzle (logs)',      url: '/dozzle/',                                    icon: '📜', fav: true },
    { label: 'OpenMediaVault',     url: 'http://opti.lan/',                            icon: '🗄️', fav: true },
    { label: 'Portainer',          url: 'http://noblenumbat.lan:9000/',                icon: '🐳', fav: true },
    { label: 'Vaultwarden',        url: 'https://bitwarden.rpi.lan/#/vault',           icon: '🔑', fav: true },
    { label: 'Vaultwarden admin',  url: 'https://bitwarden.rpi.lan/admin/users/overview', icon: '⚙️' },
  ]},
  { group: 'Media', links: [
    { label: 'Jellyfin',           url: 'http://jellyfin.lan:8096/',                   icon: '🎬', fav: true },
    { label: 'Kavita (comics)',    url: 'http://comics.lan:5000/',                     icon: '📚', fav: true },
  ]},
  { group: 'Library management', links: [
    { label: 'Sonarr (TV)',        url: 'http://noblenumbat.lan:8989/',                icon: '📺' },
    { label: 'Radarr (movies)',    url: 'http://noblenumbat.lan:7878/',                icon: '🎞️' },
    { label: 'Lidarr (music)',     url: 'http://noblenumbat.lan:8686/',                icon: '🎵' },
    { label: 'Bazarr (subtitles)', url: 'http://noblenumbat.lan:6767/',                icon: '💬' },
    { label: 'Mylar3 (comics)',    url: 'http://noblenumbat.lan:8090/',                icon: '🦸' },
    { label: 'Prowlarr (indexers)', url: 'http://noblenumbat.lan:9696/',               icon: '🔍' },
  ]},
  { group: 'Downloads', links: [
    { label: 'qBittorrent',        url: 'http://noblenumbat.lan:8081/',                icon: '⬇️', fav: true },
    // FlareSolverr (8191) and the gluetun admin API (8003) are APIs with no UI, so
    // they are deliberately not listed — a link that renders JSON isn't a bookmark.
  ]},
  { group: 'This dashboard', links: [
    { label: 'Architecture map',   url: '/architecture/',                              icon: '◈' },
    { label: 'Agents',             url: '/agents/',                                    icon: '🛰️' },
    { label: 'Samba (opti)',       url: '/samba/',                                     icon: '📁' },
    { label: 'Notes',              url: '/notes/',                                     icon: '📝' },
    { label: 'Agentic workspace',  url: '/agentic/',                                   icon: '⚙' },
  ]},
];

const ALL_LINKS = LINK_GROUPS.flatMap(g => g.links.map(l => ({ ...l, group: g.group })));
const QUICK_LINKS = ALL_LINKS.filter(l => l.fav);

// Internal dashboard pages must not open in a new tab; everything else should.
const isExternal = (url) => !url.startsWith('/');

function route() {
  const hash = location.hash.replace('#', '') || 'home';
  const view = document.getElementById('view');

  // Update active nav link
  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.route === hash);
  });

  const renderer = routes[hash] ?? renderHome;
  // Dense board layouts get the full screen; text-heavy pages keep the 1100px
  // reading width (see .view/.view-wide in style.css).
  view.classList.toggle('view-wide', renderer === renderHome || renderer === renderLinks || renderer === renderCockpit || renderer === renderLogs);
  renderer(view);
}

// ── Home page (bento) ─────────────────────────────────────────────────────────
// Rebuilt 2026-07-25. The old Home was a uniform grid of link cards: every tile the
// same visual weight, no live system state, and a Pi-hole card that had been dead
// since the v6 upgrade. A homelab dashboard's most valuable content is "are my
// machines healthy", so that now leads and is physically the biggest thing on screen.
//
// All vitals come from reports that already exist (hardware-latest / software-latest /
// homelab-doctor-latest / network-latest) — this is presentation, not new collection.
const HOST_ROLES = {
  rpi:         'DNS · DHCP · web',
  opti:        'storage · control plane',
  noblenumbat: 'media stack',
  android:     'local LLM',
};

function pct(used, total) {
  if (!total || used == null) return null;
  return Math.round((used / total) * 100);
}

// Shared thresholds so a number means the same thing everywhere on the page.
function toneFor(p) {
  if (p == null) return '';
  return p >= 90 ? 'crit' : p >= 75 ? 'warn' : 'ok';
}

function meter(p, tone) {
  if (p == null) return '';
  return `<div class="meter-sm"><span data-tone="${tone || toneFor(p)}" style="width:${Math.min(100, p)}%"></span></div>`;
}

function skeletonTile(span = 'sp4') {
  return `<div class="tile ${span}"><div class="sk sk-line w40"></div>
    <div class="sk sk-line w80"></div><div class="sk sk-line w60"></div></div>`;
}

// Duration since an ISO timestamp, phrased as an age ("12h", "7d") rather than an
// event ("12h ago") — used for container uptime, where "up 12h ago" reads wrong.
function durSince(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const m = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h` : `${Math.round(h / 24)}d`;
}

// Multi-terabyte pools read as noise in GB ("3712 GB"), so switch units past 1 TiB.
function fmtCapacity(gb) {
  if (gb == null) return '—';
  return gb >= 1024 ? `${(gb / 1024).toFixed(1)} TB` : `${Math.round(gb)} GB`;
}

function fmtRate(bps) {
  if (bps == null) return '—';
  const b = bps * 8;   // bytes/s in, bits/s out — network speeds are quoted in bits
  if (b >= 1e9) return (b / 1e9).toFixed(1) + ' Gb/s';
  if (b >= 1e6) return (b / 1e6).toFixed(1) + ' Mb/s';
  if (b >= 1e3) return Math.round(b / 1e3) + ' kb/s';
  return Math.round(b) + ' b/s';
}

// Hand-rolled SVG sparkline — no chart library, no build step (see CLAUDE.md: this app
// is deliberately dependency-free). One series per chart, so there is no legend: the
// label and latest value sit beside it in ink, never in the series colour.
// nulls BREAK the line rather than interpolating — a gap is a real fact (agent down),
// and drawing through it would invent data.
function sparkline(values, o = {}) {
  const w = o.w ?? 120, h = o.h ?? 30, pad = 2;
  const nums = values.filter(v => v != null && Number.isFinite(v));
  if (nums.length < 2) return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg>`;

  const lo = o.min ?? Math.min(...nums);
  const hiRaw = o.max ?? Math.max(...nums);
  const hi = hiRaw === lo ? lo + 1 : hiRaw;   // flat series still draws a centred line
  const x = (i) => pad + i * (w - 2 * pad) / Math.max(1, values.length - 1);
  const y = (v) => pad + (h - 2 * pad) * (1 - (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo));

  let d = '', drawing = false, lastPt = null;
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) { drawing = false; return; }
    d += `${drawing ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
    drawing = true;
    lastPt = [x(i), y(v)];
  });

  const stroke = o.tone ? `var(--${o.tone})` : 'var(--brand)';
  const area = o.area === false ? '' :
    `<path d="${d}L${lastPt[0].toFixed(1)} ${h - pad} L${pad} ${h - pad} Z" fill="${stroke}" opacity=".08" stroke="none"/>`;
  const avg = nums.reduce((a, b) => a + b, 0) / nums.length;
  const title = `min ${Math.round(Math.min(...nums) * 10) / 10} · avg ${Math.round(avg * 10) / 10} · now ${Math.round(nums[nums.length - 1] * 10) / 10}`;

  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><title>${title}</title>
    ${area}<path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.5"
      vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastPt[0].toFixed(1)}" cy="${lastPt[1].toFixed(1)}" r="1.8" fill="${stroke}"/></svg>`;
}

function renderHome(view) {
  view.innerHTML = `
    <div class="page-home">
      <header class="page-header">
        <h1 class="home-title"><img src="favicon.svg" alt="" class="home-title-icon" />Pert's Pocket</h1>
        <span class="badge-host" id="home-generated">loading…</span>
        <span class="spacer"></span>
        <span class="ribbon" id="home-ribbon"></span>
        <button class="btn-mini" id="rb-doctor" title="Run the Homelab Doctor collector now">▶ Doctor</button>
        <button class="btn-mini" id="rb-sync" title="Force all three architecture agents to collect fresh data">⟳ Agents</button>
      </header>

      <div class="bento" id="home-bento">
        <div id="home-hosts" style="display:contents">
          ${skeletonTile('sp4')}${skeletonTile('sp4')}${skeletonTile('sp4')}
        </div>

        <div class="tile sp8" id="tile-containers">
          <div class="tile-head">Containers<span class="spacer"></span><span id="ct-meta" class="tile-sub" style="margin:0"></span></div>
          <div id="containers-body" class="scrollbody"><div class="sk sk-line w80"></div><div class="sk sk-line w60"></div><div class="sk sk-line w80"></div></div>
        </div>

        <div class="tile-col sp4">
          <div class="tile" id="tile-pihole">
            <div class="tile-head">Pi-hole<span class="spacer"></span><span id="pihole-pill"></span></div>
            <div id="pihole-body"><div class="sk sk-line w60"></div><div class="sk sk-line w40"></div></div>
          </div>
          <div class="tile" id="tile-vpn" style="flex:1">
            <div class="tile-head">VPN<span class="spacer"></span><span class="pill">noblenumbat</span></div>
            <div id="vpn-body"><div class="sk sk-line w60"></div><div class="sk sk-line w40"></div></div>
          </div>
        </div>

        <div class="tile sp4" id="tile-storage">
          <div class="tile-head">Storage &amp; disks<span class="spacer"></span><span class="pill">opti</span></div>
          <div id="storage-body"><div class="sk sk-line w60"></div><div class="sk sk-line w80"></div></div>
        </div>

        <div class="tile sp4" id="tile-network">
          <div class="tile-head">Network</div>
          <div id="network-body"><div class="sk sk-line w60"></div><div class="sk sk-line w80"></div></div>
        </div>

        <div class="tile sp4" id="tile-upkeep">
          <div class="tile-head">Services &amp; upkeep</div>
          <div id="upkeep-body"><div class="sk sk-line w60"></div><div class="sk sk-line w80"></div></div>
        </div>

        <div class="tile sp8" id="tile-activity">
          <div class="tile-head">Activity<span class="spacer"></span><span class="tile-sub" style="margin:0">from latest reports</span></div>
          <div id="activity-body" class="scrollbody"><div class="sk sk-line w80"></div><div class="sk sk-line w60"></div></div>
        </div>

        <div class="tile-col sp4">
          <div class="mini-grid">
            <a class="tile link" href="#cockpit">
              <div class="tile-head">Monitors</div>
              <div class="tile-metric" id="m-monitors">—</div>
              <div class="tile-sub" id="s-monitors">Uptime Kuma</div>
            </a>
            <a class="tile link" href="#reports">
              <div class="tile-head">Reports</div>
              <div class="tile-metric" id="m-reports">—</div>
              <div class="tile-sub" id="s-reports">runner status</div>
            </a>
            <a class="tile link" href="/agents/">
              <div class="tile-head">Agent drift</div>
              <div class="tile-metric" id="m-drift">—</div>
              <div class="tile-sub" id="s-drift">undescribed vs missing</div>
            </a>
            <a class="tile link" href="#bots">
              <div class="tile-head">Bots</div>
              <div class="tile-metric" id="m-bots">—</div>
              <div class="tile-sub" id="s-bots">discord fleet</div>
            </a>
            <a class="tile link" href="#leetify">
              <div class="tile-head">CS2 / Leetify</div>
              <div class="tile-metric" id="m-leetify">—</div>
              <div class="tile-sub" id="leetify-body">loading…</div>
            </a>
          </div>
          <div class="tile" style="flex:1">
            <div class="tile-head">Quick links<span class="spacer"></span>
              <a href="#links" class="tile-head-link">all ${ALL_LINKS.length} →</a></div>
            <div class="qlinks qlinks-col">
              ${QUICK_LINKS.map(l => `<a class="qlink" href="${l.url}"
                ${isExternal(l.url) ? 'target="_blank" rel="noopener"' : ''}>
                <span>${l.icon}</span>${l.label}</a>`).join('')}
            </div>
          </div>
        </div>
      </div>
    </div>`;

  document.getElementById('rb-doctor')?.addEventListener('click', (e) => ribbonRun(e.currentTarget));
  document.getElementById('rb-sync')?.addEventListener('click', (e) => ribbonSync(e.currentTarget));

  loadRibbon();
  loadHostVitals();
  loadContainers();
  loadPihole();
  loadStorageAndVpn();
  loadNetwork();
  loadUpkeep();
  loadActivity();
  loadHomeCounters();
  loadLeetify();

  // Live layer: repaint the fast-moving numbers every 30s while Home is visible
  // (report loaders above stay fetch-on-render — their data doesn't move that fast).
  if (homeLiveTimer) clearInterval(homeLiveTimer);
  homeLiveTimer = setInterval(() => {
    if (!homeIsActive()) {
      clearInterval(homeLiveTimer);
      homeLiveTimer = null;
      return;
    }
    refreshHomeLive();
    loadSparks(['rpi', 'opti', 'noblenumbat']);
  }, 30_000);
}

// ── Quick links page ──────────────────────────────────────────────────────────
// A browser-bookmarks replacement: every LAN service, grouped, addressed by its
// Pi-hole DNS name. Type-to-filter is focused on load so it behaves like the
// bookmark bar it replaces — start typing, hit Enter, you're there.
function renderLinks(view) {
  view.innerHTML = `
    <div class="page-links">
      <header class="page-header">
        <h1 class="home-title"><img src="favicon.svg" alt="" class="home-title-icon" />Quick links</h1>
        <span class="badge-host">${ALL_LINKS.length} services</span>
        <span class="spacer"></span>
        <input id="link-filter" class="link-filter" type="search" placeholder="Filter…  (Enter opens the first match)"
               autocomplete="off" spellcheck="false" aria-label="Filter links" />
      </header>
      <div class="link-groups" id="link-groups">
        ${LINK_GROUPS.map(g => `
          <section class="link-group" data-group="${g.group}">
            <div class="tile-head">${g.group}</div>
            <div class="link-grid">
              ${g.links.map(l => `
                <a class="link-card" href="${l.url}" data-label="${l.label.toLowerCase()}"
                   ${isExternal(l.url) ? 'target="_blank" rel="noopener"' : ''}>
                  <span class="link-icon">${l.icon}</span>
                  <span class="link-text">
                    <span class="link-label">${l.label}</span>
                    <span class="link-url">${l.url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</span>
                  </span>
                  <span class="link-dot" data-s="idle" title="checking…"></span>
                </a>`).join('')}
            </div>
          </section>`).join('')}
      </div>
      <div class="tile-sub" id="link-empty" style="display:none;padding:var(--s5);text-align:center">No match.</div>
    </div>`;

  const input = document.getElementById('link-filter');
  const filter = () => {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    document.querySelectorAll('.link-group').forEach(sec => {
      let any = 0;
      sec.querySelectorAll('.link-card').forEach(card => {
        const hit = !q || card.dataset.label.includes(q) || card.href.toLowerCase().includes(q);
        card.style.display = hit ? '' : 'none';
        if (hit) { any++; shown++; }
      });
      sec.style.display = any ? '' : 'none';
    });
    document.getElementById('link-empty').style.display = shown ? 'none' : '';
  };
  input.addEventListener('input', filter);
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const first = [...document.querySelectorAll('.link-card')].find(c => c.style.display !== 'none');
    if (first) first.click();
  });
  // Auto-focus is the point on a desktop (type-and-Enter, like the bookmark bar this
  // replaces) but on a phone it just pops the keyboard over the list.
  if (matchMedia('(pointer: fine)').matches) input.focus();

  checkLinkHealth();
}

// Colour each card by whether the service actually answers.
//
// External services are probed by the BACKEND (/api/linkcheck): this page is https
// and the services are http, so a browser-side fetch would be blocked as mixed
// content before it ever left — every dot sat grey forever. Node also probes the
// self-signed-https services (Cockpit, Vaultwarden) that a browser page can never
// verify. Results are keyed by origin, so both Vaultwarden links share one probe.
// Internal /pages are same-origin and cheap to check honestly from here.
async function checkLinkHealth() {
  const cards = [...document.querySelectorAll('.link-card')];

  const external = fetch('/api/linkcheck')
    .then(r => r.ok ? r.json() : null)
    .then(d => {
      if (!d?.origins) return;
      for (const card of cards) {
        const url = card.getAttribute('href');
        if (!isExternal(url)) continue;
        const dot = card.querySelector('.link-dot');
        let origin;
        try { origin = new URL(url).origin; } catch (_) { continue; }
        const r = d.origins[origin];
        if (!r) { dot.title = 'not probed'; continue; }
        dot.dataset.s = r.up ? 'ok' : 'crit';
        dot.title = r.up ? `responding (HTTP ${r.status})` : `unreachable (${r.error})`;
      }
    })
    .catch(() => { /* dots stay neutral — never invent an outage */ });

  const internal = Promise.allSettled(cards
    .filter(c => !isExternal(c.getAttribute('href')))
    .map(async (card) => {
      const dot = card.querySelector('.link-dot');
      try {
        const r = await fetch(card.getAttribute('href'), {
          method: 'HEAD', signal: AbortSignal.timeout(4000),
        });
        dot.dataset.s = r.ok ? 'ok' : 'crit';
        dot.title = r.ok ? 'reachable' : `HTTP ${r.status}`;
      } catch (_) {
        dot.dataset.s = 'crit';
        dot.title = 'unreachable';
      }
    }));

  await Promise.allSettled([external, internal]);
}

// ── ribbon: fleet rollup + freshness + run-now buttons ─────────────────────────
async function loadRibbon() {
  const el = document.getElementById('home-ribbon');
  if (!el) return;
  try {
    const [r, a] = await Promise.all([
      fetch('/api/runners').then(x => x.ok ? x.json() : {}),
      fetch('/api/agents').then(x => x.ok ? x.json() : {}),
    ]);
    const runners = r.runners || [];
    // Only runners that have actually reported drive the fleet pill. A manual or
    // never-run runner sits at status "unknown" forever — treating that as critical
    // painted a red "!" over a healthy fleet (hltv-watchlist did exactly this).
    const reporting = runners.filter(x => x.run_at && x.status && x.status !== 'unknown');
    const rank = { critical: 0, warn: 1, ok: 2 };
    const worst = reporting.reduce((w, x) => (rank[x.status] ?? 1) < (rank[w] ?? 2) ? x.status : w, 'ok');
    const tone = worst === 'ok' ? 'ok' : worst === 'warn' ? 'warn' : 'crit';
    const short = { 'Homelab Doctor': 'doctor', 'Hardware Report': 'hw', 'Software Inventory': 'sw', 'Network': 'net', 'Cold Copy Backup': 'backup' };
    const fresh = reporting.map(x => `${short[x.label] || x.name} ${relTime(x.run_at)}`).join(' · ');
    const agents = (a.hosts || []);
    const reach = agents.filter(h => h.reachable).length;
    el.innerHTML = `<span class="pill" data-s="${tone}">${worst === 'ok' ? '✓ fleet ok' : '! ' + worst}</span>
      <span class="pill" id="ribbon-mon" title="Uptime Kuma — live" data-s="ok">…</span>
      <span class="ribbon-fresh" title="report ages">${fresh}</span>
      <span class="ribbon-fresh">· ${reach}/${agents.length || 3} agents</span>`;
    refreshHomeLive();   // fills #ribbon-mon (and the Monitors mini-tile) right away
  } catch (_) {
    el.innerHTML = `<span class="tile-sub">status unavailable</span>`;
  }
}

async function ribbonRun(btn) {
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = 'running…';
  try {
    const res = await fetch('/api/runners/homelab-doctor/run', { method: 'POST' });
    btn.textContent = res.ok ? 'started ✓' : 'failed ✕';
  } catch (_) { btn.textContent = 'failed ✕'; }
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; loadRibbon(); }, 4000);
}

async function ribbonSync(btn) {
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = 'syncing…';
  try {
    const res = await fetch('/api/agents/sync-all', { method: 'POST' });
    btn.textContent = res.ok ? 'synced ✓' : 'failed ✕';
  } catch (_) { btn.textContent = 'failed ✕'; }
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; loadContainers(); }, 2500);
}

// One fetch of hardware+doctor+software drives every host tile.
async function loadHostVitals() {
  const wrap = document.getElementById('home-hosts');
  if (!wrap) return;
  let hw = {}, doc = {}, sw = {};
  try {
    const [h, d, s] = await Promise.all([
      fetch('/api/runners/hardware-latest').then(r => r.ok ? r.json() : {}),
      fetch('/api/runners/homelab-doctor-latest').then(r => r.ok ? r.json() : {}),
      fetch('/api/runners/software-latest').then(r => r.ok ? r.json() : {}),
    ]);
    hw = h; doc = d; sw = s;
  } catch (_) { /* fall through to the unavailable state below */ }

  const byHost = {};
  (hw.hosts || []).forEach(h => (byHost[h.host] ||= {}).hw = h);
  (doc.hosts || []).forEach(h => (byHost[h.host] ||= {}).doc = h);
  (sw.hosts || []).forEach(h => (byHost[h.host] ||= {}).sw = h);

  // Servers only — android is a phone that is usually off-LAN and would read as a
  // permanently-broken tile rather than useful information.
  const order = ['rpi', 'opti', 'noblenumbat'].filter(n => byHost[n]);
  if (!order.length) {
    wrap.innerHTML = `<div class="tile sp12"><div class="tile-head">Hosts</div>
      <div class="tile-sub">No hardware report yet — run the Hardware runner from Reports.</div></div>`;
    return;
  }

  const stamp = document.getElementById('home-generated');
  // Newest of the three reports — hardware alone runs daily, and stamping with it
  // read "report 8h ago" while the doctor was minutes old.
  const newest = [hw.run_at, doc.run_at, sw.run_at].filter(Boolean).sort().pop();
  if (stamp) stamp.textContent = newest ? `report ${relTime(newest)}` : 'rpi · 192.168.1.10';

  wrap.innerHTML = order.map(name => {
    const m = byHost[name].hw?.metrics || {};
    const dm = byHost[name].doc?.metrics || {};
    const status = byHost[name].doc?.status || byHost[name].hw?.status || 'unknown';
    const sTone = status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : 'crit';
    const sGlyph = status === 'ok' ? '✓' : status === 'warn' ? '!' : '×';

    // Hosts with a storage pool (opti's ZFS `red`) show the pool, not the OS disk —
    // the pool is what fills up and what everyone else's storage rides on. The OS
    // disk stays watched by the doctor's 90% threshold either way.
    const pool = dm.pool || null;
    const disk = pool || (m.disks || [])[0] || {};
    const diskPct = disk.used_pct ?? null;
    const diskLabel = pool ? `Pool · ${pool.pool_name || 'zfs'}` : 'Disk';
    // memory_gib is an OBJECT ({MemTotal, MemAvailable, SwapTotal, SwapFree}); the
    // scalar is mem_used_gib. Treating memory_gib as a number rendered
    // "NaN% of [object Object] GiB".
    const memTotal = m.memory_gib?.MemTotal ?? null;
    const memPct = pct(m.mem_used_gib, memTotal);
    const load1 = Array.isArray(m.load) ? parseFloat(m.load[0]) : null;
    const cores = parseInt((m.cpu || {})['CPU(s)'], 10) || null;
    const loadPct = (load1 != null && cores) ? Math.round((load1 / cores) * 100) : null;
    const temp = pickTemp(m.thermals);
    const containers = (dm.containers || []).length;
    const down = (dm.containers || []).filter(c => !/^up/i.test(c.status || '')).length;
    const updates = byHost[name].sw?.metrics?.image_update_count || 0;

    return `<a class="tile link sp4 host-tile" href="/architecture/" data-host-info="${name}"
        title="Click for host details (ctrl/middle-click opens the architecture map)">
      <div class="tile-head" style="margin-bottom:var(--s2)">
        <span class="host-name">${name}</span>
        <span class="spacer"></span>
        <span class="pill" data-s="${sTone}">${sGlyph} ${escHtml(status)}</span>
      </div>
      <div class="host-role">${HOST_ROLES[name] || ''}</div>
      <div class="vitals">
        <div class="vital">
          <div class="vital-label">CPU load</div>
          <div class="vital-value"><span id="hv-load-${name}">${load1 != null ? load1.toFixed(2) : '—'}</span>
            ${cores ? `<small>/ ${cores} cores</small>` : ''}</div>
          <span id="hm-load-${name}">${meter(loadPct)}</span>
        </div>
        <div class="vital">
          <div class="vital-label">Memory</div>
          <div class="vital-value"><span id="hv-mem-${name}">${memPct != null ? memPct + '%' : '—'}</span>
            ${memTotal ? `<small>of ${memTotal} GiB</small>` : ''}</div>
          <span id="hm-mem-${name}">${meter(memPct)}</span>
        </div>
        <div class="vital">
          <div class="vital-label">${diskLabel}</div>
          <div class="vital-value">${diskPct != null ? diskPct + '%' : '—'}
            ${disk.size_gb ? `<small>of ${Math.round(disk.size_gb)} GB</small>` : ''}</div>
          ${meter(diskPct)}
        </div>
        <div class="vital">
          <div class="vital-label" id="hv4l-${name}">${temp != null ? 'Temp' : 'Uptime'}</div>
          <div class="vital-value" id="hv4v-${name}">${temp != null ? temp + '°C' : (m.uptime || '—')}</div>
          <div class="tile-sub" style="margin-top:2px" id="hv4s-${name}">${temp != null ? (m.uptime || '') : ''}</div>
        </div>
      </div>
      <div class="sparks" id="sparks-${name}"></div>
      <div class="tile-sub" style="margin-top:var(--s3);display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap">
        ${containers ? `<span>${containers - down}/${containers} containers</span>` : ''}
        ${containers ? `<span class="cstrip">${(dm.containers || []).map(c =>
          `<span class="cdot" data-s="${/^up/i.test(c.status || '') ? 'ok' : 'crit'}" title="${escHtml(`${c.name} — ${c.status || 'unknown'}`)}"></span>`).join('')}</span>` : ''}
        ${down ? `<span style="color:var(--crit)">${down} down</span>` : ''}
        ${updates ? `<span style="color:var(--warn)">${updates} image update${updates > 1 ? 's' : ''}</span>` : ''}
      </div>
    </a>`;
  }).join('');

  // Keep the raw report rows around for the host-info modal, and remember cores
  // for the live loop's "load / N cores" label.
  homeHostReports = byHost;

  // Plain click opens the info modal; ctrl/cmd/middle-click keeps the old
  // architecture-map destination (the href is real, so open-in-new-tab still works).
  wrap.querySelectorAll('[data-host-info]').forEach(a => {
    a.addEventListener('click', (e) => {
      if (e.ctrlKey || e.metaKey || e.button === 1) return;
      e.preventDefault();
      showHostInfo(a.dataset.hostInfo);
    });
  });

  loadSparks(order);
  refreshHomeLive();
}

// ── Home live layer ──────────────────────────────────────────────────────────
// The report-driven tiles above are correct but slow-moving (doctor 30 min,
// hardware daily). This layer repaints the fast-moving numbers every 30s from the
// same live sources the cockpit uses: /api/vitals (agents' 30s ring buffer) and
// /api/uptime (Kuma). Reports keep owning disk/SMART/containers — those don't move.
let homeHostReports = {};
let homeLive = { vitals: null, uptime: null };
let homeLiveTimer = null;

function homeIsActive() {
  const h = location.hash.replace('#', '');
  return h === '' || h === 'home';
}

async function refreshHomeLive() {
  const [v, u] = await Promise.all([
    fetch('/api/vitals', { signal: AbortSignal.timeout(5000) }).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/uptime', { signal: AbortSignal.timeout(10_000) }).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  if (v) homeLive.vitals = v.hosts || {};
  if (u?.ok) homeLive.uptime = u;

  for (const [name, st] of Object.entries(homeLive.vitals || {})) {
    const s = st.latest;
    if (!s) continue;
    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    const setHtml = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
    if (s.load1 != null) set(`hv-load-${name}`, s.load1.toFixed(2));
    if (s.cpu_pct != null) setHtml(`hm-load-${name}`, meter(Math.round(s.cpu_pct)));
    if (s.mem_pct != null) {
      set(`hv-mem-${name}`, `${Math.round(s.mem_pct)}%`);
      setHtml(`hm-mem-${name}`, meter(Math.round(s.mem_pct)));
    }
    const up = s.uptime_s != null ? `up ${ckUptime(s.uptime_s)}` : '';
    if (s.temp_c != null) {
      set(`hv4l-${name}`, 'Temp');
      set(`hv4v-${name}`, `${Math.round(s.temp_c)}°C`);
      set(`hv4s-${name}`, up);
    } else if (up) {
      set(`hv4l-${name}`, 'Uptime');
      set(`hv4v-${name}`, ckUptime(s.uptime_s));
    }
  }

  const ku = homeLive.uptime;
  const mon = document.getElementById('ribbon-mon');
  if (mon && ku) {
    mon.dataset.s = ku.down ? 'crit' : ku.pending ? 'warn' : 'ok';
    mon.textContent = `${ku.up}/${ku.total} monitors`;
  }
  const mm = document.getElementById('m-monitors');
  if (mm && ku) {
    mm.textContent = `${ku.up}/${ku.total}`;
    const sub = document.getElementById('s-monitors');
    if (sub) {
      const bad = (ku.monitors || []).filter(m => m.status !== 'up').map(m => m.name);
      sub.textContent = bad.length ? `down: ${bad.join(', ')}` : 'all up · Uptime Kuma';
      sub.style.color = bad.length ? 'var(--crit)' : '';
    }
  }
}

// Basic host info on click — the tile used to jump straight to the architecture
// map, which is a lot of page for "what's this box doing right now".
function showHostInfo(name) {
  const rep = homeHostReports[name] || {};
  const live = homeLive.vitals?.[name]?.latest;
  const m = rep.hw?.metrics || {};
  const dm = rep.doc?.metrics || {};
  const swm = rep.sw?.metrics || {};
  const status = rep.doc?.status || 'unknown';
  const ips = { rpi: '192.168.1.10', opti: '192.168.1.11', noblenumbat: '192.168.1.6' };
  const cs = dm.containers || [];
  const downList = cs.filter(c => !/^up/i.test(c.status || '')).map(c => c.name);
  // Kuma rows for this host: its ping monitor + the "<prefix>:" service monitors.
  const pfx = { rpi: 'rpi:', opti: 'opti:', noblenumbat: 'nn:' }[name];
  const kmon = (homeLive.uptime?.monitors || []).filter(x =>
    x.name.startsWith(`host: ${name}`) || (pfx && x.name.startsWith(pfx)));
  const dot = (s) => s === 'up' ? 'ok' : s === 'down' ? 'crit' : 'warn';
  const kv = (k, val) => val ? `<div class="kv-row"><span>${k}</span><span>${val}</span></div>` : '';

  infoModal(`${name} — ${HOST_ROLES[name] || 'host'}`, `
    <div class="kv-rows">
      ${kv('status', `<span class="pill" data-s="${status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : 'crit'}">${escHtml(status)}</span>`)}
      ${kv('address', `<span class="mono">${ips[name] || '—'}</span>`)}
      ${kv('uptime', live?.uptime_s != null ? ckUptime(live.uptime_s) : escHtml(m.uptime || '—'))}
      ${kv('cpu', live ? `load ${live.load1?.toFixed(2) ?? '—'}${live.cpu_pct != null ? ` · ${Math.round(live.cpu_pct)}%` : ''}` : null)}
      ${kv('memory', live?.mem_pct != null ? `${Math.round(live.mem_pct)}%` : null)}
      ${kv('temp', live?.temp_c != null ? `${Math.round(live.temp_c)}°C` : null)}
      ${kv('containers', cs.length ? `${cs.length - downList.length}/${cs.length} up${downList.length ? ` — <b style="color:var(--crit)">down: ${escHtml(downList.join(', '))}</b>` : ''}` : null)}
      ${kv('packages', swm.pending_count ? `${swm.pending_count} pending${swm.reboot_required ? ' · <b style="color:var(--warn)">reboot required</b>' : ''}` : (swm.reboot_required ? '<b style="color:var(--warn)">reboot required</b>' : null))}
    </div>
    ${kmon.length ? `<div class="tile-sub" style="margin-top:var(--s3)">Monitors</div>
      <div class="ck-mon-grid" style="margin-top:var(--s1)">${kmon.map(x => `
        <span class="ck-mon" data-s="${x.status}"><span class="cdot" data-s="${dot(x.status)}"></span>${escHtml(x.name)}${x.ms != null ? ` <span class="ck-mon-ms">${x.ms}ms</span>` : ''}</span>`).join('')}</div>` : ''}
    <div class="ck-actions" style="margin-top:var(--s3)">
      <a class="btn-mini" href="#cockpit">🎛 Cockpit</a>
      ${name !== 'android' ? `<a class="btn-mini" target="_blank" rel="noopener"
        href="${name === 'rpi' ? 'https://rpi.lan:9090/system/terminal' : `https://rpi.lan:9090/@${name}/system/terminal`}">⌨ Terminal</a>` : ''}
      <a class="btn-mini" href="/architecture/">◈ Architecture map</a>
    </div>`);
}

// Lightweight info-only modal: same chrome as confirmAction, no confirm semantics.
function infoModal(title, bodyHtml) {
  if (document.querySelector('.confirm-overlay')) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay open confirm-overlay';
  overlay.innerHTML = `
    <div class="modal confirm-modal" role="dialog" aria-modal="true" aria-label="${escHtml(title)}">
      <div class="modal-header">
        <span class="modal-title">${escHtml(title)}</span>
        <button class="modal-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
    </div>`;
  const close = () => { document.removeEventListener('keydown', onKey); overlay.remove(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  overlay.querySelector('.modal-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
    // In-app links inside the modal (e.g. #cockpit) should also dismiss it.
    if (e.target.closest('a[href^="#"]')) close();
  });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
}

// Host-tile sparklines. Phase 3 wires /api/vitals (30s live series from the arch
// agents); until that backend exists this quietly renders nothing — the tiles are
// complete without it, so an older backend never shows a broken strip.
async function loadSparks(hostNames) {
  for (const name of hostNames) {
    const el = document.getElementById(`sparks-${name}`);
    if (!el) continue;
    try {
      const res = await fetch(`/api/vitals/${name}?points=240`);
      if (!res.ok) continue;
      const d = await res.json();
      const s = d.samples || [];
      if (s.length < 2) {
        // Distinguish "no data yet" from "this agent can't provide it" — an agent
        // still on v0.1.x has no /vitals, and it will never "warm up".
        const stale = /404/.test(d.error || '');
        el.innerHTML = `<div class="tile-sub" style="margin:6px 0 0">${stale
          ? 'live charts need arch-agent v0.2.0 on this host'
          : d.error ? `live charts unavailable — ${d.error}` : 'live charts warming up…'}</div>`;
        continue;
      }
      const series = (k) => s.map(x => x[k] ?? null);
      const last = (k) => { const v = series(k).filter(x => x != null); return v.length ? v[v.length - 1] : null; };
      const spark = (k, label, unit, opts) => {
        const latest = last(k);
        if (latest == null) return '';
        return `<div class="spark-cell">
          <div class="spark-label">${label} <b>${typeof latest === 'number' ? Math.round(latest * 10) / 10 : latest}${unit}</b></div>
          ${sparkline(series(k), { tone: opts?.pct ? toneFor(latest) : null, min: opts?.pct ? 0 : undefined, max: opts?.pct ? 100 : undefined })}
        </div>`;
      };
      const net = s.map(x => (x.rx_bps != null && x.tx_bps != null) ? x.rx_bps + x.tx_bps : null);
      const netLatest = [...net].reverse().find(v => v != null);
      el.innerHTML = `<div class="spark-grid">
        ${spark('cpu_pct', 'CPU', '%', { pct: true })}
        ${spark('mem_pct', 'Mem', '%', { pct: true })}
        ${spark('temp_c', 'Temp', '°C')}
        ${netLatest != null ? `<div class="spark-cell">
          <div class="spark-label">Net <b>${fmtRate(netLatest)}</b></div>
          ${sparkline(net, {})}</div>` : ''}
      </div>`;
    } catch (_) { /* vitals endpoint absent — tile is fine without sparks */ }
  }
}

// thermals shape varies by host (and by sensor); take the highest plausible CPU reading
// rather than guessing at a specific key that may not exist on every box.
function pickTemp(thermals) {
  if (!thermals) return null;
  const vals = [];
  const walk = (v) => {
    if (typeof v === 'number') { if (v > 0 && v < 130) vals.push(v); return; }
    if (Array.isArray(v)) return v.forEach(walk);
    if (v && typeof v === 'object') return Object.values(v).forEach(walk);
  };
  walk(thermals);
  return vals.length ? Math.round(Math.max(...vals)) : null;
}

function relTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 2) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

// ── Storage & disks (pool + SMART + 30-day trend) and VPN detail ─────────────
async function loadStorageAndVpn() {
  let doc = null;
  try { doc = await fetch('/api/runners/homelab-doctor-latest').then(r => r.ok ? r.json() : null); } catch (_) {}

  const sel = document.getElementById('storage-body');
  if (sel) {
    try {
      const [hw, trends] = await Promise.all([
        fetch('/api/runners/hardware-latest').then(r => r.ok ? r.json() : null),
        fetch('/api/trends?days=30').then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      const opti = doc?.hosts?.find(h => h.host === 'opti');
      const pool = opti?.metrics?.pool;
      const smart = hw?.hosts?.find(h => h.host === 'opti')?.metrics?.smart || {};

      const poolHtml = pool ? `
        <div style="display:flex;align-items:baseline;gap:8px">
          <div class="tile-metric">${Math.round(pool.used_pct)}%</div>
          <div class="tile-sub" style="margin:0">${pool.size_gb
            ? `of ${fmtCapacity(pool.size_gb)}${pool.pool_name ? ` · ${escHtml(pool.pool_name)}` : ' pool'}`
            : 'pool'}</div>
        </div>
        ${meter(Math.round(pool.used_pct))}
        ${pool.avail_gb ? `<div class="tile-sub">${fmtCapacity(pool.avail_gb)} free</div>` : ''}`
        : `<div class="tile-sub">No storage pool detected on opti.</div>`;

      // A pool_name change means a DIFFERENT pool (mergerfs era vs zpool "red"), and
      // percentages across pools aren't comparable — splicing them made the trend
      // read "min 15.9 · avg 63". Chart only the current era; it regrows daily.
      const pts = trends?.pool || [];
      const currentEra = pts.length ? (pts[pts.length - 1].pool_name || null) : null;
      let eraStart = pts.length;
      while (eraStart > 0 && (pts[eraStart - 1].pool_name || null) === currentEra) eraStart--;
      const eraVals = pts.slice(eraStart).map(p => p.used_pct);
      const trendHtml = (eraVals.length > 2) ? `
        <div class="spark-cell" style="margin-top:8px">
          <div class="spark-label">pool fill, last ${eraVals.length} days${currentEra ? ` (${escHtml(currentEra)})` : ''}</div>
          ${sparkline(eraVals, { min: 0, max: 100 })}
        </div>` : '';

      const sevFor = (d) => (d.health !== 'PASSED') ? 'crit' : (d.reallocated > 0 || d.pending > 0) ? 'severe' : 'ok';
      const smartHtml = Object.keys(smart).length ? `
        <div class="smart-list">${Object.entries(smart).map(([dev, d]) => `
          <div class="smart-row">
            <span class="mono">${escHtml(dev)}</span>
            <span class="chip" data-s="${sevFor(d)}">${d.health === 'PASSED' ? (sevFor(d) === 'severe' ? 'worn' : 'ok') : escHtml(d.health)}</span>
            <span class="tile-sub" style="margin:0">
              ${d.reallocated ? `<b style="color:var(--severe)">${d.reallocated} realloc</b> · ` : ''}${d.pending ? `<b style="color:var(--crit)">${d.pending} pending</b> · ` : ''}${d.temp_c ? d.temp_c + '°C · ' : ''}${d.power_on_hours ? Math.round(d.power_on_hours / 24 / 365 * 10) / 10 + 'y on' : ''}
            </span>
          </div>`).join('')}</div>` : '';

      sel.innerHTML = poolHtml + trendHtml + smartHtml;
    } catch (_) {
      sel.innerHTML = `<div class="tile-sub">Unavailable.</div>`;
    }
  }

  // VPN detail straight from the doctor's healer block (public IP, port match, watchdog).
  const vel = document.getElementById('vpn-body');
  if (!vel) return;
  try {
    const vpn = doc?.hosts?.find(h => h.host === 'noblenumbat')?.metrics?.vpn;
    if (!vpn) { vel.innerHTML = `<div class="tile-sub">No VPN data in the doctor report.</div>`; return; }
    const up = vpn.gluetun_running !== false && vpn.status !== 'down';
    const portsMatch = vpn.forwarded_port && vpn.forwarded_port === vpn.qbt_listen_port;
    const lastAction = (vpn.actions || [])[0];
    vel.innerHTML = `
      <div class="tile-metric" style="color:var(--${up ? 'ok' : 'crit'})">${up ? 'Up' : 'Down'}</div>
      <div class="kv-rows">
        ${vpn.public_ip ? `<div class="kv-row"><span>exit IP</span><span class="mono">${escHtml(vpn.public_ip)}</span></div>` : ''}
        ${vpn.forwarded_port ? `<div class="kv-row"><span>port fwd</span><span class="mono">${escHtml(vpn.forwarded_port)}
          <span class="chip" data-s="${portsMatch ? 'ok' : 'warn'}">${portsMatch ? 'qBt ✓' : 'qBt ' + escHtml(vpn.qbt_listen_port || '?')}</span></span></div>` : ''}
        <div class="kv-row"><span>watchdog</span><span>${escHtml(vpn.status || '—')}${vpn.ts ? ' · ' + relTime(vpn.ts) : ''}</span></div>
        ${lastAction ? `<div class="kv-row"><span>last heal</span><span>${escHtml(typeof lastAction === 'string' ? lastAction : (lastAction.action || ''))}</span></div>` : ''}
      </div>`;
  } catch (_) {
    vel.innerHTML = `<div class="tile-sub">Unavailable.</div>`;
  }
}

// ── Containers fleet table ─────────────────────────────────────────────────────
async function loadContainers() {
  const el = document.getElementById('containers-body');
  if (!el) return;
  try {
    const d = await fetch('/api/containers').then(r => r.ok ? r.json() : null);
    if (!d?.hosts?.length) { el.innerHTML = `<div class="tile-sub">No container data yet.</div>`; return; }
    let total = 0, up = 0, updates = 0;
    const rows = d.hosts.flatMap(h => h.containers.map(c => {
      total++; if (c.up) up++;
      // One flag drives the chip, the counter and the ⬆ button, so a just-updated
      // container can't show "update" in one place and not the other.
      const showUpd = !!c.update_available && !recentlyUpdated(h.host, c.name);
      if (showUpd) updates++;
      const since = c.status_since ? durSince(c.status_since) : (c.status || '');
      const img = (c.image || '').replace(/^(lscr\.io|ghcr\.io|docker\.io)\//, '').replace(/@sha256.*$/, '');
      return `<tr>
        <td><span class="cdot" data-s="${c.up ? 'ok' : 'crit'}"></span></td>
        <td class="mono ct-name">${escHtml(c.name)}${showUpd ? ' <span class="chip" data-s="warn" title="newer image available">update</span>' : ''}</td>
        <td><span class="chip">${escHtml(h.host)}</span></td>
        <td class="tile-sub" style="margin:0">${c.up ? 'up ' + escHtml(since) : '<b style="color:var(--crit)">down</b>'}</td>
        <td class="mono ct-img" title="${escHtml(c.image || '')}">${escHtml(img)}</td>
        <td class="ct-act">${showUpd ? `<button class="btn-icon" title="Update ${escHtml(c.name)} on ${escHtml(h.host)} — pull newer image and recreate"
          data-upd-host="${escHtml(h.host)}" data-upd-container="${escHtml(c.name)}" data-upd-image="${escHtml(c.image || '')}">⬆</button>` : ''}<button class="btn-icon" title="Restart ${escHtml(c.name)} on ${escHtml(h.host)}"
          data-host="${escHtml(h.host)}" data-container="${escHtml(c.name)}">⟳</button></td>
      </tr>`;
    }));
    const meta = document.getElementById('ct-meta');
    if (meta) meta.textContent = `${up}/${total} up${updates ? ` · ${updates} updates` : ''}`;
    el.innerHTML = `<table class="ctable"><tbody>${rows.join('')}</tbody></table>`;
    // Distinct attribute names, so the restart selector can't also match an ⬆ button.
    el.querySelectorAll('.btn-icon[data-container]').forEach(b => {
      b.addEventListener('click', () => restartContainer(b.dataset.host, b.dataset.container, b));
    });
    el.querySelectorAll('.btn-icon[data-upd-container]').forEach(b => {
      b.addEventListener('click', () => updateContainer(b.dataset.updHost, b.dataset.updContainer, b.dataset.updImage, b));
    });
  } catch (_) {
    el.innerHTML = `<div class="tile-sub">Unavailable — is opti reachable?</div>`;
  }
}

// ── Network panel ──────────────────────────────────────────────────────────────
async function loadNetwork() {
  const el = document.getElementById('network-body');
  if (!el) return;
  try {
    const d = await fetch('/api/runners/network-latest').then(r => r.ok ? r.json() : null);
    if (!d?.hosts?.length) { el.innerHTML = `<div class="tile-sub">No network report yet.</div>`; return; }
    const hosts = d.hosts.filter(h => h.host !== 'android');
    const ms = (v) => v == null ? '—' : (Math.round(v * 10) / 10) + '<small>ms</small>';
    const rows = hosts.map(h => {
      const m = h.metrics || {};
      const arp = (m.arp_failed || []).length;
      return `<div class="kv-row">
        <span class="mono">${escHtml(h.host)}</span>
        <span>gw ${ms(m.gateway_avg_ms)} · net ${ms(m.internet_avg_ms)} · ${(m.listening_ports || []).length} ports${arp ? ` · <b style="color:var(--warn)">${arp} arp✕</b>` : ''}</span>
      </div>`;
    }).join('');
    const rpiDns = hosts.find(h => h.host === 'rpi')?.metrics?.dns_lookups_ms || {};
    const dns = Object.entries(rpiDns).map(([k, v]) => `${escHtml(k)} ${Math.round(v)}ms`).join(' · ');
    el.innerHTML = `<div class="kv-rows">${rows}</div>
      ${dns ? `<div class="tile-sub" style="margin-top:8px">DNS via Pi-hole: ${dns}</div>` : ''}`;
  } catch (_) {
    el.innerHTML = `<div class="tile-sub">Unavailable.</div>`;
  }
}

// ── Services & upkeep (uptime board + cert countdown + patch posture) ─────────
async function loadUpkeep() {
  const el = document.getElementById('upkeep-body');
  if (!el) return;
  try {
    const [doc, sw, timers] = await Promise.all([
      fetch('/api/runners/homelab-doctor-latest').then(r => r.ok ? r.json() : null),
      fetch('/api/runners/software-latest').then(r => r.ok ? r.json() : null),
      fetch('/api/timers').then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    const services = (doc?.services || []).map(s => {
      const cert = s.cert_days_left;
      const certChip = (cert != null && cert < 3000)
        ? ` <span class="chip" data-s="${cert < 14 ? 'crit' : cert < 45 ? 'warn' : ''}">cert ${cert}d</span>` : '';
      return `<div class="kv-row">
        <span><span class="cdot" data-s="${s.up ? 'ok' : 'crit'}"></span> ${escHtml(s.name)}</span>
        <span class="tile-sub" style="margin:0">${s.up ? escHtml(s.detail || 'up') : '<b style="color:var(--crit)">down</b>'}${certChip}</span>
      </div>`;
    }).join('');

    const posture = (sw?.hosts || []).filter(h => h.host !== 'android').map(h => {
      const m = h.metrics || {};
      const bits = [];
      if (m.pending_count) bits.push(`${m.pending_count} pkg${m.security_count ? ` (<b style="color:var(--crit)">${m.security_count} sec</b>)` : ''}`);
      if (m.reboot_required) bits.push('<b style="color:var(--warn)">reboot req</b>');
      if (m.image_update_count) bits.push(`${m.image_update_count} image${m.image_update_count > 1 ? 's' : ''}`);
      return bits.length ? `<div class="kv-row"><span class="mono">${h.host}</span><span>${bits.join(' · ')}</span></div>` : '';
    }).join('');

    const cold = (doc || sw) ? await fetch('/api/runners/coldcopy-latest').then(r => r.ok ? r.json() : null).catch(() => null) : null;
    const coldHtml = cold ? `<div class="kv-row"><span>cold copy</span>
      <span><span class="chip" data-s="${cold.status === 'ok' ? 'ok' : 'warn'}">${escHtml(cold.status)}</span> ${cold.run_at ? relTime(cold.run_at) : ''}</span></div>` : '';

    // systemd timers from the agent fragments — the homelab's own automation only
    // (backend already strips distro housekeeping). Shows the last-fired note so a
    // silently dead watchdog is visible here rather than discovered during an outage.
    const homelabTimers = /vpn-stack-heal|media-import|homelab-|bb-kavita|podman-auto|coldcopy|agentic/;
    const timerRows = (timers?.hosts || []).flatMap(h =>
      (h.timers || [])
        .filter(t => homelabTimers.test(t.unit))
        .map(t => `<div class="kv-row">
          <span class="mono">${escHtml(t.unit.replace('.timer', ''))}</span>
          <span class="tile-sub" style="margin:0"><span class="chip">${escHtml(h.host)}</span> ${escHtml(t.passed || '—')}</span>
        </div>`))
      .slice(0, 7).join('');

    el.innerHTML = `<div class="kv-rows">${services}</div>
      ${(posture || coldHtml) ? `<div class="upkeep-sep"></div><div class="kv-rows">${posture}${coldHtml}</div>` : ''}
      ${!posture ? `<div class="tile-sub" style="margin-top:6px">all hosts patched · no reboots pending</div>` : ''}
      ${timerRows ? `<div class="upkeep-sep"></div><div class="tile-head" style="margin-bottom:var(--s2)">Timers</div><div class="kv-rows">${timerRows}</div>` : ''}`;
  } catch (_) {
    el.innerHTML = `<div class="tile-sub">Unavailable.</div>`;
  }
}

// ── Activity feed ──────────────────────────────────────────────────────────────
async function loadActivity() {
  const el = document.getElementById('activity-body');
  if (!el) return;
  try {
    const d = await fetch('/api/activity?limit=40').then(r => r.ok ? r.json() : null);
    const events = d?.events || [];
    if (!events.length) { el.innerHTML = `<div class="tile-sub">Nothing to report — quiet fleet.</div>`; return; }
    const tone = (s) => ['critical', 'high', 'crit'].includes(s) ? 'crit' : ['warn', 'warning', 'medium'].includes(s) ? 'warn' : '';
    // Finding messages echo raw log lines (nginx access logs, dmesg, apt output) —
    // the single most attacker-influenced text on this page. Escape everything.
    el.innerHTML = `<div class="feed">${events.map(e => `
      <div class="feed-item">
        <span class="cdot" data-s="${tone(e.severity) || 'idle'}"></span>
        <span class="feed-msg">${escHtml(e.message)}</span>
        <span class="feed-meta">${e.host ? `<span class="chip">${escHtml(e.host)}</span>` : ''}${escHtml(e.source)} · ${e.ts ? relTime(e.ts) : ''}</span>
      </div>`).join('')}</div>`;
  } catch (_) {
    el.innerHTML = `<div class="tile-sub">Unavailable.</div>`;
  }
}

async function loadHomeCounters() {
  // Reports: how many runners are not OK.
  try {
    const d = await fetch('/api/runners').then(r => r.ok ? r.json() : {});
    const rs = d.runners || [];
    const bad = rs.filter(r => r.status !== 'ok').length;
    setText('m-reports', bad ? `${bad}` : '✓');
    setText('s-reports', bad ? `of ${rs.length} need attention` : `all ${rs.length} healthy`);
  } catch (_) { setText('s-reports', 'unavailable'); }

  // Agents: total drift across hosts.
  try {
    const d = await fetch('/api/agents').then(r => r.ok ? r.json() : {});
    const hosts = d.hosts || [];
    const drift = hosts.reduce((n, h) => n + (h.drift_count || 0), 0);
    const unreachable = hosts.filter(h => !h.reachable).length;
    setText('m-drift', String(drift));
    setText('s-drift', unreachable ? `${unreachable} agent unreachable` : `across ${hosts.length} hosts`);
  } catch (_) { setText('s-drift', 'unavailable'); }

  // Bots: how many are actually enabled/running.
  try {
    const states = await Promise.all(BOTS.map(b =>
      fetch(`/api/${b.id}/status`).then(r => r.ok ? r.json() : null).catch(() => null)));
    const live = states.filter(Boolean).length;
    setText('m-bots', `${live}/${BOTS.length}`);
    setText('s-bots', live === BOTS.length ? 'all reachable' : 'some unreachable');
  } catch (_) { setText('s-bots', 'unavailable'); }
}

function setText(id, txt) {
  const el = document.getElementById(id);
  if (el) el.textContent = txt;
}

async function loadLeetify() {
  const el = document.getElementById('leetify-body');
  if (!el) return;
  try {
    const res = await fetch('/api/runners/leetify-latest');
    if (!res.ok) { el.textContent = 'Not configured yet — set LEETIFY_API_KEY + STEAM64_ID on opti.'; return; }
    const d = await res.json();
    el.textContent = d.summary || 'No data yet.';
  } catch {
    el.textContent = 'Unavailable.';
  }
}

// Live FTL stats (/api/pihole/summary), falling back to the network report's snapshot.
// The report's pihole block has gone null before (v6 API/session issues), which is what
// left this tile reading "unavailable" — the live route is now the primary source.
async function loadPihole() {
  const el = document.getElementById('pihole-body');
  const pill = document.getElementById('pihole-pill');
  if (!el) return;

  let p = null, live = false;
  try {
    const res = await fetch('/api/pihole/summary');
    if (res.ok) { p = await res.json(); live = true; }
  } catch (_) { /* fall through to the report */ }

  if (!p) {
    try {
      const d = await fetch('/api/runners/network-latest').then(r => r.ok ? r.json() : null);
      const hosts = Array.isArray(d?.hosts) ? d.hosts : [];
      // Pi-hole runs on rpi. Prefer that host explicitly rather than "first host with a
      // truthy pihole key" — the key is present (as null) on every host, so any change
      // that made it falsy-but-not-null would silently pick the wrong machine.
      p = (hosts.find(h => h?.host === 'rpi') || hosts.find(h => h?.metrics?.pihole))
        ?.metrics?.pihole || d?.pihole || null;
    } catch (_) { /* nothing left to try */ }
  }

  if (!p) {
    el.innerHTML = `<div class="tile-sub">Stats unavailable — check PIHOLE_WEB_PASSWORD in the webapp env, or the network runner.</div>`;
    return;
  }

  const q = p.dns_queries_today ?? p.queries ?? null;
  const blocked = p.ads_blocked_today ?? p.blocked ?? null;
  const pct = p.ads_percentage_today ?? p.percent_blocked;
  const clients = p.unique_clients ?? p.clients ?? null;
  const blockingOn = p.blocking ? p.blocking.enabled : true;

  if (pill) pill.innerHTML = live
    ? `<span class="pill" data-s="${blockingOn ? 'ok' : 'warn'}">${blockingOn ? '✓ blocking' : '⏸ paused'}</span>`
    : `<span class="pill">from report</span>`;

  el.innerHTML = `
    <div style="display:flex;align-items:baseline;gap:8px">
      <div class="tile-metric">${typeof pct === 'number' ? pct.toFixed(1) + '%' : '—'}</div>
      <div class="tile-sub" style="margin:0">blocked today</div>
    </div>
    ${meter(typeof pct === 'number' ? Math.round(pct) : null, 'ok')}
    <div class="kv-rows" style="margin-top:8px">
      <div class="kv-row"><span>queries</span><span class="mono">${q != null ? q.toLocaleString() : '—'}</span></div>
      <div class="kv-row"><span>blocked</span><span class="mono">${blocked != null ? blocked.toLocaleString() : '—'}</span></div>
      <div class="kv-row"><span>clients</span><span class="mono">${clients ?? '—'}</span></div>
      ${p.queries_cached != null ? `<div class="kv-row"><span>cached</span><span class="mono">${p.queries_cached.toLocaleString()}</span></div>` : ''}
      ${p.gravity_domains != null ? `<div class="kv-row"><span>blocklist</span><span class="mono">${p.gravity_domains.toLocaleString()} domains</span></div>` : ''}
    </div>
    ${live ? `<div class="tile-actions">
      ${blockingOn
        ? `<button class="btn-mini" id="ph-pause">⏸ Pause 5 min</button>`
        : `<button class="btn-mini" id="ph-resume">▶ Resume blocking${p.blocking?.timer ? ` (auto in ${Math.round(p.blocking.timer / 60)}m)` : ''}</button>`}
    </div>` : ''}`;

  document.getElementById('ph-pause')?.addEventListener('click', () => toggleBlocking(false, 300));
  document.getElementById('ph-resume')?.addEventListener('click', () => toggleBlocking(true));
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
    const res = await fetch('/api/runners/leetify-latest');
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

// ── Reports page (the 4 scheduled runners: homelab-doctor, hardware, software, network) ──
let reportsRefreshTimer = null;

async function renderReports(view) {
  clearInterval(reportsRefreshTimer);
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Homelab Reports</h1>
        <div class="sec-header-actions">
          <span id="rpt-last-refresh" class="sec-refresh-label">Loading...</span>
          <button class="btn-refresh" onclick="loadReports()">↻ Refresh</button>
        </div>
      </div>
      <div id="rpt-agents-strip" style="margin-bottom:14px"></div>
      <div id="rpt-grid" class="sec-grid"><div class="sec-loading">Loading reports…</div></div>
    </div>
  `;
  await loadReports();
  loadAgentsStrip();
  reportsRefreshTimer = setInterval(loadReports, 5 * 60 * 1000);
}

// Compact link-out to the Agents config page — a different control plane (per-host
// collectors) from the runners above, so it gets its own page rather than a card in
// this grid. Best-effort: any failure just leaves the plain link with no summary.
async function loadAgentsStrip() {
  const el = document.getElementById('rpt-agents-strip');
  if (!el) return;
  const base = 'border:1px solid var(--border);border-radius:8px;padding:10px 14px;'
             + 'display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--muted)';
  el.innerHTML = `<div style="${base}">🛰️ Architecture agents — <a href="/agents/">view status →</a></div>`;
  try {
    const res = await fetch('/api/agents');
    if (!res.ok) return;
    const data = await res.json();
    const hosts = data.hosts || [];
    const unreachable = hosts.filter(h => !h.reachable).length;
    const drift = hosts.reduce((n, h) => n + (h.drift_count || 0), 0);
    const bits = [`${hosts.length} host(s)`];
    if (unreachable) bits.push(`<span style="color:var(--crit)">${unreachable} unreachable</span>`);
    if (drift) bits.push(`<span style="color:var(--warn)">${drift} drift</span>`);
    el.innerHTML = `<div style="${base}">🛰️ Architecture agents — ${bits.join(' · ')}
      — <a href="/agents/">view status →</a></div>`;
  } catch (_) { /* strip already shows the plain link */ }
}

async function loadReports() {
  const grid = document.getElementById('rpt-grid');
  if (!grid) return;

  let runners;
  try {
    const res = await fetch('/api/runners');
    const data = await res.json();
    runners = data.runners ?? [];
  } catch {
    grid.innerHTML = `<div class="sec-error">Cannot reach /api/runners — is the backend running?</div>`;
    return;
  }

  const label = document.getElementById('rpt-last-refresh');
  if (label) label.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;

  if (runners.length === 0) {
    grid.innerHTML = `
      <div class="sec-empty">
        <p>No runner reports yet.</p>
        <p class="sec-empty-hint">Run them from opti (GitHub Actions or the dispatcher), or hit “Run now” once reports exist.</p>
      </div>`;
    return;
  }

  grid.innerHTML = runners.map(a => buildReportCard(a, 'runners')).join('');
}

function buildReportCard(r, apiBase) {
  const statusClass = { ok: 'status-ok', warn: 'status-warn', critical: 'status-critical' }[r.status] ?? 'status-unknown';
  const statusLabel = { ok: 'OK', warn: 'WARN', critical: 'CRITICAL', unknown: '?' }[r.status] ?? r.status.toUpperCase();
  const runAt = r.run_at ? new Date(r.run_at).toLocaleString() : '—';
  const staleBadge = r.stale ? `<span class="sec-stale-badge" title="No fresh run recently">STALE</span>` : '';
  const alertBadge = r.has_alert ? `<span class="agent-alert-badge" title="Alert flagged in this report">ALERT</span>` : '';
  const safeLabel = (r.label || '').replace(/'/g, "\\'");
  const isRunner = apiBase === 'runners';

  const controls = r.agent ? `
        <button class="btn-toggle ${r.enabled ? 'on' : 'off'}" onclick="toggleAgent('${apiBase}','${r.agent}',${!r.enabled},this)">${r.enabled ? 'Enabled' : 'Disabled'}</button>
        <button class="btn-run" onclick="runAgent('${apiBase}','${r.agent}',this)">Run now</button>` : '';

  // Runners get the full-log viewer ("View latest") + per-run History; security reports keep "View details".
  const viewBtns = isRunner
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
  const url = date ? `/api/runners/${name}/report/${date}` : `/api/runners/${name}`;
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
    const res = await fetch(`/api/runners/${name}/history`);
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
          <button class="btn-refresh" onclick="renderWeather(botPanel())">↻ Refresh</button>
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
  weatherCfg.witty_names = cfg.witty_names || [];  // old bot build during deploy skew

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

      <div class="sec-card w-card-wide${cfg.witty_enabled ? '' : ' card-disabled'}">
        <div class="sec-card-header"><span class="sec-card-title">Witty morning messages</span></div>
        <div class="w-field">
          <label><input type="checkbox" id="w-witty-enabled" ${cfg.witty_enabled ? 'checked' : ''}
                 onchange="weatherCfg.witty_enabled = this.checked" />
                 Append a generated one-liner after the message text each morning</label>
        </div>
        <div id="w-witty-info"><div class="sec-loading">Loading pool status…</div></div>
        <div id="w-name-list"></div>
        <div class="w-field">
          <label for="w-name-add">Add a name</label>
          <div class="w-search-row">
            <input type="text" id="w-name-add" class="w-input" placeholder="first name / nickname / full name…"
                   onkeydown="if(event.key==='Enter')weatherAddName()" autocomplete="off" />
            <button class="btn-view" onclick="weatherAddName()">Add</button>
          </div>
        </div>
        <div class="sec-card-actions">
          <button class="btn-view" onclick="weatherReroll(this)">Reroll next line</button>
        </div>
        <p class="w-hint">One line featuring a random name is appended after the message text each morning —
        generated locally, no API calls. Nothing repeats until the pool runs out, then it reshuffles itself.
        “Send now” and “Reroll” each use up a line. Name changes apply on “Save settings” and rebuild the pool.</p>
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
  weatherRenderNames();
  weatherLoadWitty();  // fire-and-forget — fills #w-witty-info when it lands
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

// ── witty message pool (same list-editor pattern as locations) ────────────────
function weatherRenderNames() {
  const el = document.getElementById('w-name-list');
  if (!el || !weatherCfg) return;
  el.innerHTML = (weatherCfg.witty_names || []).map((n, i) => `
    <div class="w-loc-row">
      <span class="w-loc-name">🎯 ${escHtml(n)}</span>
      <button class="w-loc-del" title="Remove" onclick="weatherRemoveName(${i})">✕</button>
    </div>`).join('') || '<div class="sec-empty">No names — the one-liner needs at least one victim.</div>';
}

function weatherAddName() {
  const input = document.getElementById('w-name-add');
  const n = (input?.value || '').trim();
  if (!n) return;
  const names = weatherCfg.witty_names || (weatherCfg.witty_names = []);
  if (!names.some(x => x.toLowerCase() === n.toLowerCase())) names.push(n);
  input.value = '';
  weatherRenderNames();
}

function weatherRemoveName(i) {
  weatherCfg.witty_names.splice(i, 1);
  weatherRenderNames();
}

async function weatherLoadWitty() {
  const el = document.getElementById('w-witty-info');
  if (!el) return;
  let res, err;
  try { res = await fetch('/api/weather/witty'); } catch (e) { err = e; }
  if (!res || !res.ok) {
    el.innerHTML = `<div class="sec-error">Witty pool unavailable${res ? ` (HTTP ${res.status})` : ''} —
      an old bot build may still be deploying. Hit ↻ Refresh in a minute.</div>`;
    return;
  }
  const d = await res.json();
  if (!d.available) {
    el.innerHTML = `<div class="sec-error">${escHtml(d.reason || 'witty module not loaded')}</div>`;
    return;
  }
  el.innerHTML = `
    <div class="w-kv"><span>Lines left this cycle</span><strong>${d.remaining} (cycle ${d.cycle})</strong></div>
    <div class="w-kv"><span>Next up*</span><strong id="w-witty-next">${escHtml(d.next_generic || '—')}</strong></div>
    <div class="w-kv"><span>Last posted</span><strong>${escHtml(d.last_posted?.text || '—')}</strong></div>
    <p class="w-hint">*generic preview — the posted line adapts to the day's weather and weekday.
    “Preview report” shows exactly what will post.</p>`;
}

async function weatherReroll(btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rerolling…';
  let res, err;
  try { res = await fetch('/api/weather/witty/reroll', { method: 'POST' }); } catch (e) { err = e; }
  btn.textContent = orig;
  btn.disabled = false;
  const d = res ? await res.json().catch(() => ({})) : {};
  if (!res || !res.ok || !d.ok) {
    alert(d.error || weatherError(res, err) || 'Reroll failed.');
    return;
  }
  await weatherLoadWitty();
  // the reroll response knows today's actual weather — show that pick, not the generic one
  const next = document.getElementById('w-witty-next');
  if (next && d.next) next.textContent = d.next;
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
    witty_enabled: !!document.getElementById('w-witty-enabled')?.checked,
    witty_names: weatherCfg.witty_names || [],
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

// Home-page status card body for a bot.
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
          <button class="btn-refresh" onclick="renderHealthdigest(botPanel())">↻ Refresh</button>
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
          <button class="btn-refresh" onclick="renderJellyfin(botPanel())">↻ Refresh</button>
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
          <button class="btn-refresh" onclick="renderSports(botPanel())">↻ Refresh</button>
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
          <button class="btn-refresh" onclick="renderHltv(botPanel())">↻ Refresh</button>
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

// ── Local LLM page (android phone) ─────────────────────────────────────────────
// Talks to the phone through /api/llama/* (backend proxy). Two upstream services
// on the phone: llama-server (inference, :8080) and llama-ctl (management, :8081) —
// see routes/llama.js. llmRunbooks is the working copy of the runbook list.
let llmRunbooks = [];
let llmEditingIndex = null;
let llmElapsedTimer = null;

function llmError(res, err) {
  if (err) return `Network error reaching the webapp backend: ${err.message}`;
  switch (res && res.status) {
    case 502: return 'phone unreachable — check llama-server/llama-ctl are up (`sv status llama`, `sv status llama-ctl` on the phone).';
    case 400: return null; // caller shows the validation message from the body
    default:  return `Request failed (HTTP ${res ? res.status : '?'}).`;
  }
}

// Trigger the docs-generator agent on opti (via the dispatcher run endpoint the
// webapp already proxies). Fire-and-forget: opti rebuilds the reference docs from
// the latest agent reports; the phone picks them up on its next ~2-min sync.
async function llmRegenDocs(btn) {
  if (!confirm('Rebuild the auto-generated homelab docs from the latest agent reports on opti?\n\n'
    + 'The docs regenerate in a few seconds; the phone syncs them within ~2 minutes.')) return;
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = '⟳ Regenerating…';
  let res, err;
  try {
    res = await fetch('/api/runners/docs-generator/run', { method: 'POST' });
  } catch (e) { err = e; }
  btn.disabled = false;
  btn.textContent = orig;
  if (res && res.ok) {
    alert('Docs regeneration queued on opti. They will sync to the phone within ~2 minutes.');
  } else {
    alert(err ? `Failed to reach dispatcher: ${err.message}` : `Regeneration failed (HTTP ${res ? res.status : '?'}).`);
  }
}

async function renderLlm(view) {
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header">
        <h1>Local LLM (android)</h1>
        <div class="sec-header-actions">
          <button class="btn-run" onclick="llmRegenDocs(this)" title="Rebuild the auto-generated homelab docs from the latest agent reports">⟳ Regenerate docs</button>
          <button class="btn-refresh" onclick="renderLlm(document.getElementById('view'))">↻ Refresh</button>
        </div>
      </div>
      <div id="llm-page"><div class="sec-loading">Loading…</div></div>
    </div>`;
  await loadLlm();
}

async function loadLlm() {
  const page = document.getElementById('llm-page');
  if (!page) return;
  let status, models, runbooksData;
  try {
    const [sRes, mRes, rRes] = await Promise.all([
      fetch('/api/llama/status'), fetch('/api/llama/models'), fetch('/api/llama/runbooks'),
    ]);
    if (!sRes.ok) { page.innerHTML = `<div class="sec-error">${llmError(sRes)}</div>`; return; }
    status = await sRes.json();
    models = mRes.ok ? await mRes.json() : { models: [], current: null };
    runbooksData = rRes.ok ? await rRes.json() : { runbooks: [] };
  } catch (e) {
    page.innerHTML = `<div class="sec-error">${llmError(null, e)}</div>`;
    return;
  }
  llmRunbooks = runbooksData.runbooks || [];

  const b = status.battery || {};
  page.innerHTML = `
    <div class="sec-grid">
      <div class="sec-card ${status.llama_healthy ? 'status-ok' : ''}">
        <div class="sec-card-header">
          <span class="sec-status-badge ${status.llama_healthy ? 'status-ok' : 'status-unknown'}">${status.llama_healthy ? 'ONLINE' : 'UNREACHABLE'}</span>
          <span class="sec-card-title">Server status</span>
        </div>
        <div class="w-kv"><span>Model</span><strong>${escHtml(status.current_model || '—')}</strong></div>
        <div class="w-kv"><span>Battery</span><strong>${b.percentage != null ? b.percentage + '%' : '—'} (${escHtml(b.status || '—')})</strong></div>
        <div class="w-kv"><span>Temp</span><strong>${b.temperature != null ? Number(b.temperature).toFixed(1) + '°C' : '—'}</strong></div>
        <div class="w-kv"><span>Service</span><strong>${escHtml((status.sv_status || '—').split(';')[0])}</strong></div>
      </div>

      <div class="sec-card">
        <div class="sec-card-header"><span class="sec-card-title">Model</span></div>
        <div class="w-field">
          <label for="llm-model-select">Switch active model (restarts the server, ~1–2 min reload)</label>
          <div class="w-search-row">
            <select id="llm-model-select" class="w-input">
              ${(models.models || []).map(m => `<option value="${escHtml(m)}" ${m === models.current ? 'selected' : ''}>${escHtml(m)}</option>`).join('')}
            </select>
            <button class="btn-run" onclick="llmSwitchModel(this)">Switch</button>
          </div>
          <span id="llm-model-msg" class="w-hint"></span>
        </div>
      </div>
    </div>

    <div class="sec-card w-card-wide llm-section">
      <div class="sec-card-header"><span class="sec-card-title">Prompt console</span></div>
      <div class="w-field">
        <label for="llm-mode">Mode</label>
        <select id="llm-mode" class="w-input">
          <option value="ask">Grounded — answers only from the runbooks below</option>
          <option value="chat">Raw chat — no grounding</option>
        </select>
      </div>
      <div class="w-field">
        <label for="llm-prompt">Prompt</label>
        <textarea id="llm-prompt" class="w-input llm-textarea" rows="4" placeholder="Ask the homelab assistant something…"></textarea>
      </div>
      <div class="sec-card-actions">
        <button class="btn-run" onclick="llmSend(this)">Send</button>
        <span id="llm-send-msg" class="w-hint"></span>
      </div>
      <div id="llm-response" class="llm-response"></div>
    </div>

    <div class="sec-card w-card-wide llm-section">
      <div class="sec-card-header"><span class="sec-card-title">Runbooks (${llmRunbooks.length})</span></div>
      <div id="llm-runbook-list"></div>
      <div class="sec-card-actions">
        <button class="btn-view" onclick="llmNewRunbook()">+ New runbook</button>
      </div>
      <div id="llm-runbook-editor"></div>
    </div>`;
  llmRenderRunbookList();
}

function llmRenderRunbookList() {
  const el = document.getElementById('llm-runbook-list');
  if (!el) return;
  el.innerHTML = llmRunbooks.map((r, i) => `
    <div class="w-loc-row">
      <span class="w-loc-name">📄 ${escHtml(r.name)}${r.editable ? '' : ' <span class="w-hint">(auto-generated — read only)</span>'}</span>
      <span class="w-loc-coords">${r.content.length} chars</span>
      ${r.editable
        ? `<button class="btn-view" onclick="llmEditRunbook(${i})">Edit</button>
           <button class="w-loc-del" title="Delete" onclick="llmDeleteRunbook(${i})">✕</button>`
        : `<button class="btn-view" onclick="llmEditRunbook(${i})">View</button>`}
    </div>`).join('') || '<div class="sec-empty">No runbooks yet.</div>';
}

function llmEditRunbook(i) {
  llmEditingIndex = i;
  const r = llmRunbooks[i];
  const editor = document.getElementById('llm-runbook-editor');
  if (!r.editable) {
    editor.innerHTML = `
      <div class="w-field">
        <label>${escHtml(r.name)} — auto-generated from the homelab agent reports on opti.
          Edits here would just get overwritten by the next sync; use "⟳ Regenerate docs"
          above instead, or edit the source collector if the data itself is wrong.</label>
        <textarea class="w-input llm-textarea llm-textarea-lg" rows="14" readonly>${escHtml(r.content)}</textarea>
      </div>
      <div class="sec-card-actions">
        <button class="btn-refresh" onclick="document.getElementById('llm-runbook-editor').innerHTML=''">Close</button>
      </div>`;
    return;
  }
  editor.innerHTML = `
    <div class="w-field">
      <label for="llm-rb-name">Filename</label>
      <input type="text" id="llm-rb-name" class="w-input" value="${escHtml(r.name)}" />
    </div>
    <div class="w-field">
      <label for="llm-rb-content">Content (markdown)</label>
      <textarea id="llm-rb-content" class="w-input llm-textarea llm-textarea-lg" rows="14">${escHtml(r.content)}</textarea>
    </div>
    <div class="sec-card-actions">
      <button class="btn-run" onclick="llmSaveRunbook()">Save</button>
      <button class="btn-refresh" onclick="document.getElementById('llm-runbook-editor').innerHTML=''">Cancel</button>
      <span id="llm-rb-msg" class="w-hint"></span>
    </div>`;
}

function llmNewRunbook() {
  llmEditingIndex = null;
  const editor = document.getElementById('llm-runbook-editor');
  editor.innerHTML = `
    <div class="w-field">
      <label for="llm-rb-name">Filename (must end in .md)</label>
      <input type="text" id="llm-rb-name" class="w-input" placeholder="07-new-runbook.md" />
    </div>
    <div class="w-field">
      <label for="llm-rb-content">Content (markdown)</label>
      <textarea id="llm-rb-content" class="w-input llm-textarea llm-textarea-lg" rows="14" placeholder="# Title..."></textarea>
    </div>
    <div class="sec-card-actions">
      <button class="btn-run" onclick="llmSaveRunbook()">Save</button>
      <button class="btn-refresh" onclick="document.getElementById('llm-runbook-editor').innerHTML=''">Cancel</button>
      <span id="llm-rb-msg" class="w-hint"></span>
    </div>`;
}

async function llmSaveRunbook() {
  const name = (document.getElementById('llm-rb-name')?.value || '').trim();
  const content = document.getElementById('llm-rb-content')?.value || '';
  const msg = document.getElementById('llm-rb-msg');
  if (!name.endsWith('.md')) { msg.textContent = 'Filename must end in .md'; return; }
  let res, err;
  try {
    res = await fetch(`/api/llama/runbooks/${encodeURIComponent(name)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }),
    });
  } catch (e) { err = e; }
  if (res && res.ok) {
    msg.textContent = 'Saved.';
    await loadLlm();
  } else {
    msg.textContent = llmError(res, err) || 'Save failed.';
  }
}

async function llmDeleteRunbook(i) {
  const r = llmRunbooks[i];
  if (!confirm(`Delete ${r.name}?`)) return;
  let res, err;
  try { res = await fetch(`/api/llama/runbooks/${encodeURIComponent(r.name)}`, { method: 'DELETE' }); } catch (e) { err = e; }
  if (res && res.ok) await loadLlm();
  else alert(llmError(res, err) || 'Delete failed.');
}

async function llmSwitchModel(btn) {
  const sel = document.getElementById('llm-model-select');
  const msg = document.getElementById('llm-model-msg');
  const name = sel && sel.value;
  if (!name) return;
  if (!confirm(`Switch to ${name}? The server restarts and is unavailable for ~1–2 minutes while it reloads.`)) return;
  btn.disabled = true;
  msg.textContent = 'Switching (server is restarting)…';
  let res, err;
  try {
    res = await fetch('/api/llama/model', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    });
  } catch (e) { err = e; }
  btn.disabled = false;
  if (res && res.ok) msg.textContent = 'Switched — reloading in the background.';
  else msg.textContent = llmError(res, err) || 'Switch failed.';
}

async function llmSend(btn) {
  const mode = (document.getElementById('llm-mode') || {}).value || 'ask';
  const prompt = (document.getElementById('llm-prompt')?.value || '').trim();
  const msg = document.getElementById('llm-send-msg');
  const respEl = document.getElementById('llm-response');
  if (!prompt) return;
  btn.disabled = true;
  const started = Date.now();
  clearInterval(llmElapsedTimer);
  llmElapsedTimer = setInterval(() => {
    msg.textContent = `Thinking… ${Math.floor((Date.now() - started) / 1000)}s (local model — can take up to ~90s)`;
  }, 1000);
  respEl.innerHTML = '';
  let res, err;
  try {
    if (mode === 'ask') {
      res = await fetch('/api/llama/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: prompt }),
      });
    } else {
      res = await fetch('/api/llama/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] }),
      });
    }
  } catch (e) { err = e; }
  clearInterval(llmElapsedTimer);
  btn.disabled = false;
  if (res && res.ok) {
    const data = await res.json();
    const text = mode === 'ask' ? data.answer : ((data.choices && data.choices[0] && data.choices[0].message.content) || '');
    msg.textContent = `Done in ${Math.floor((Date.now() - started) / 1000)}s.`;
    respEl.innerHTML = (typeof marked !== 'undefined') ? marked.parse(text || '') : `<pre>${escHtml(text || '')}</pre>`;
  } else {
    msg.textContent = llmError(res, err) || 'Request failed.';
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('hashchange', route);
window.addEventListener('load', () => {
  checkHealth();
  setInterval(checkHealth, 30_000);
  route();
});

// ═══════════════════════════════════════════════════════════════════════════
// Shell v2 — bots tab page, nav status dots, theme, command palette (2026-07-25)
// ═══════════════════════════════════════════════════════════════════════════

// ── Bots: one page, five tabs ────────────────────────────────────────────────
// Replaces five sidebar entries and five page shells. Each bot's own renderer is
// reused untouched — it already takes a container element, so it doesn't care that
// the container is now a tab panel rather than the whole view.
function botPanel() { return document.getElementById('bot-panel'); }

let activeBotTab = 'weather';

function renderBots(view, initial) {
  activeBotTab = initial || activeBotTab || BOTS[0].id;
  view.innerHTML = `
    <div class="page-security">
      <div class="sec-header" style="margin-bottom:var(--s4);padding-bottom:var(--s3)">
        <h1>Discord bots</h1>
        <div class="sec-header-actions">
          <span class="sec-refresh-label">${BOTS.length} bots · one config page</span>
        </div>
      </div>
      <div class="tabs" role="tablist" aria-label="Bots" id="bot-tabs"
           style="display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:var(--s4)">
        ${BOTS.map(b => `<button class="tab" role="tab" data-bot="${b.id}"
            aria-selected="${b.id === activeBotTab}"
            style="font:inherit;font-size:13px;background:none;border:0;border-bottom:2px solid transparent;
                   padding:9px 14px;cursor:pointer;white-space:nowrap">${b.icon} ${b.label}</button>`).join('')}
      </div>
      <div id="bot-panel"></div>
    </div>`;

  document.querySelectorAll('#bot-tabs .tab').forEach(t => {
    paintBotTab(t);
    t.onclick = () => {
      activeBotTab = t.dataset.bot;
      // Keep the URL honest so a reload/bookmark lands on the same tab.
      history.replaceState(null, '', `#${activeBotTab}`);
      document.querySelectorAll('#bot-tabs .tab').forEach(x => {
        x.setAttribute('aria-selected', String(x.dataset.bot === activeBotTab));
        paintBotTab(x);
      });
      showBotTab();
    };
  });
  showBotTab();
}

function paintBotTab(t) {
  const on = t.getAttribute('aria-selected') === 'true';
  t.style.color = on ? 'var(--ink)' : 'var(--ink-3)';
  t.style.borderBottomColor = on ? 'var(--accent)' : 'transparent';
}

function showBotTab() {
  const panel = botPanel();
  const bot = BOTS.find(b => b.id === activeBotTab);
  if (!panel || !bot) return;
  panel.innerHTML = `<div class="sec-grid">
    <div class="tile"><div class="sk sk-line w40"></div><div class="sk sk-line w80"></div>
      <div class="sk sk-line w60"></div></div></div>`;
  bot.render(panel);
}

// ── Nav status dots ──────────────────────────────────────────────────────────
// The sidebar should tell you where to look before you click. Best-effort: a failed
// fetch leaves the dot neutral rather than implying health.
async function refreshNavStatus() {
  try {
    const d = await fetch('/api/runners').then(r => r.ok ? r.json() : null);
    if (d) {
      const rs = d.runners || [];
      const worst = rs.some(r => r.status === 'critical') ? 'crit'
                  : rs.some(r => r.status !== 'ok') ? 'warn' : 'ok';
      setDot('dot-reports', worst);
    }
  } catch (_) {}
  try {
    const d = await fetch('/api/reports').then(r => r.ok ? r.json() : null);
    if (d) {
      const rs = d.reports || [];
      const worst = rs.some(r => r.status === 'critical') ? 'crit'
                  : rs.some(r => r.status !== 'ok') ? 'warn' : 'ok';
      setDot('dot-security', worst);
    }
  } catch (_) {}
  try {
    const d = await fetch('/api/agents').then(r => r.ok ? r.json() : null);
    if (d) {
      const hosts = d.hosts || [];
      const worst = hosts.some(h => !h.reachable) ? 'crit'
                  : hosts.some(h => h.drift_count > 0) ? 'warn' : 'ok';
      setDot('dot-agents', worst);
    }
  } catch (_) {}
  try {
    const r = await fetch('/api/llama/status');
    setDot('dot-llm', r.ok ? 'ok' : 'warn');
  } catch (_) { setDot('dot-llm', 'warn'); }
}

function setDot(id, state) {
  const el = document.getElementById(id);
  if (el && state) el.dataset.s = state;
}

// ── Theme ────────────────────────────────────────────────────────────────────
// Shares the `arch-theme` key with the architecture and agents pages so the whole
// dashboard flips together rather than per-page.
function initTheme() {
  let t = null;
  try { t = localStorage.getItem('arch-theme'); } catch (_) {}
  if (!t) t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
}

function toggleTheme() {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('arch-theme', t); } catch (_) {}
}

// ── Command palette ──────────────────────────────────────────────────────────
// Additive to the (now grouped) nav, not a substitute for it: everything reachable
// here is also reachable by clicking.
const CMDK_ITEMS = [
  { group: 'Go to', icon: '⌂',  label: 'Home',               action: () => (location.hash = '#home') },
  { group: 'Go to', icon: '🎛️', label: 'Cockpit',            hint: 'host controls', action: () => (location.hash = '#cockpit') },
  { group: 'Go to', icon: '📜', label: 'Logs',               hint: 'Dozzle', action: () => (location.hash = '#logs') },
  { group: 'Go to', icon: '▤',  label: 'Reports',            action: () => (location.hash = '#reports') },
  { group: 'Go to', icon: '🔒', label: 'Security',           action: () => (location.hash = '#security') },
  { group: 'Go to', icon: '🎯', label: 'CS2 / Leetify',      action: () => (location.hash = '#leetify') },
  { group: 'Go to', icon: '🧠', label: 'Local LLM',          action: () => (location.hash = '#llm') },
  { group: 'Go to', icon: '◈',  label: 'Architecture map',   action: () => (location.href = '/architecture/') },
  { group: 'Go to', icon: '🛰️', label: 'Agents',             action: () => (location.href = '/agents/') },
  { group: 'Go to', icon: '🗄', label: 'Samba',              action: () => (location.href = '/samba/') },
  { group: 'Go to', icon: '📝', label: 'Notes',              action: () => (location.href = '/notes/') },
  { group: 'Go to', icon: '🔗', label: 'Quick Links',        action: () => (location.hash = '#links') },
  // Every bookmarked service is reachable from the palette — this is the bit that
  // actually replaces the browser bookmark bar (⌘K, "radarr", Enter).
  ...ALL_LINKS.map(l => ({
    group: 'Open', icon: l.icon, label: l.label, hint: l.group,
    action: () => {
      if (isExternal(l.url)) window.open(l.url, '_blank', 'noopener');
      else location.href = l.url;
    },
  })),
  { group: 'Go to', icon: '⚙',  label: 'Agentic Workspace',  action: () => (location.href = '/agentic/') },
  ...BOTS.map(b => ({ group: 'Bots', icon: b.icon, label: `${b.label} bot`,
                      action: () => { location.hash = `#${b.id}`; } })),
  { group: 'Actions', icon: '⟳', label: 'Force Sync all agents', hint: 'runs now',
    action: async () => {
      const pending = toast('Syncing all agents…', 'warn', { sticky: true });
      try {
        const r = await fetch('/api/agents/sync-all', { method: 'POST' });
        const d = await r.json();
        const results = d.results || [];
        const ok = results.filter(x => x.ok).length;
        pending.remove();
        toast(`Force Sync: ${ok}/${results.length} hosts synced.`,
              ok === results.length ? 'ok' : 'warn', { sticky: ok !== results.length });
      } catch (e) { pending.remove(); toast(`Force Sync failed: ${e.message}`, 'crit', { sticky: true }); }
    } },
  { group: 'Actions', icon: '▶', label: 'Run Homelab Doctor now', hint: 'collector',
    action: async () => {
      try {
        const r = await fetch('/api/runners/homelab-doctor/run', { method: 'POST' });
        toast(r.ok ? 'Homelab Doctor started — results land in a minute.' : 'Could not start the Doctor runner.',
              r.ok ? 'ok' : 'crit', { sticky: !r.ok });
      } catch (e) { toast(`Run failed: ${e.message}`, 'crit', { sticky: true }); }
    } },
  { group: 'Actions', icon: '⏸', label: 'Pause Pi-hole blocking (5 min)', hint: 'auto-resumes',
    action: () => toggleBlocking(false, 300) },
  { group: 'Actions', icon: '◐', label: 'Toggle light / dark', action: toggleTheme },
];

let cmdkIdx = 0, cmdkMatches = [];

function openCmdk() {
  const b = document.getElementById('cmdkBackdrop');
  const i = document.getElementById('cmdkInput');
  if (!b || !i) return;
  b.classList.add('open');
  i.value = '';
  filterCmdk('');
  i.focus();
}

function closeCmdk() {
  document.getElementById('cmdkBackdrop')?.classList.remove('open');
}

function filterCmdk(q) {
  const list = document.getElementById('cmdkList');
  if (!list) return;
  const s = q.trim().toLowerCase();
  cmdkMatches = CMDK_ITEMS.filter(it =>
    !s || it.label.toLowerCase().includes(s) || it.group.toLowerCase().includes(s));
  cmdkIdx = 0;
  if (!cmdkMatches.length) {
    list.innerHTML = `<div class="cmdk-empty">No matches for “${escHtml(q)}”.</div>`;
    return;
  }
  let html = '', lastGroup = null;
  cmdkMatches.forEach((it, n) => {
    if (it.group !== lastGroup) { html += `<div class="cmdk-group">${it.group}</div>`; lastGroup = it.group; }
    html += `<button class="cmdk-item" data-i="${n}" aria-selected="${n === 0}">
      <span class="ci-icon">${it.icon}</span>${escHtml(it.label)}
      ${it.hint ? `<span class="ci-hint">${escHtml(it.hint)}</span>` : ''}</button>`;
  });
  list.innerHTML = html;
  list.querySelectorAll('.cmdk-item').forEach(el => {
    el.onclick = () => runCmdk(parseInt(el.dataset.i, 10));
  });
}

function moveCmdk(delta) {
  if (!cmdkMatches.length) return;
  cmdkIdx = (cmdkIdx + delta + cmdkMatches.length) % cmdkMatches.length;
  const items = document.querySelectorAll('#cmdkList .cmdk-item');
  items.forEach(el => el.setAttribute('aria-selected', String(parseInt(el.dataset.i, 10) === cmdkIdx)));
  items[cmdkIdx]?.scrollIntoView({ block: 'nearest' });
}

function runCmdk(i) {
  const it = cmdkMatches[i];
  closeCmdk();
  if (it) it.action();
}

function initShell() {
  initTheme();
  document.getElementById('themeBtn')?.addEventListener('click', toggleTheme);
  document.getElementById('cmdkBtn')?.addEventListener('click', openCmdk);

  const input = document.getElementById('cmdkInput');
  input?.addEventListener('input', () => filterCmdk(input.value));
  input?.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveCmdk(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveCmdk(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); runCmdk(cmdkIdx); }
    else if (e.key === 'Escape') { closeCmdk(); }
  });
  document.getElementById('cmdkBackdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'cmdkBackdrop') closeCmdk();
  });

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openCmdk(); }
    else if (e.key === 'Escape') closeCmdk();
  });

  refreshNavStatus();
  setInterval(refreshNavStatus, 5 * 60 * 1000);
}

initShell();
