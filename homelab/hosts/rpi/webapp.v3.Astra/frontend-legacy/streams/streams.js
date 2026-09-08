// Streams page — tabbed player over stream-station's 4 slots.
//
// Two planes, deliberately separate:
//   control — /api/streams/* (Express injects the bearer token server-side)
//   video   — /hls/slot<N>/index.m3u8, same-origin via nginx straight to noblenumbat
//
// Only the ACTIVE tab holds an hls.js instance. Background slots keep running on the
// server; switching tabs tears down the player, not the stream. The status poll
// self-clears when the page is hidden or unloaded (house rule — an orphaned interval
// in a tab left open for days is the failure mode this avoids), and, because a slot is
// reaped server-side after ~5 min without a playlist fetch, a forgotten tab also stops
// pulling the stream on its own.

const SLOTS = [1, 2, 3, 4];
const POLL_MS = 5000;

let active = 1;
let hls = null;
let pollTimer = null;
let lastStatus = {};      // slot -> status object from /api/streams/status
let busy = false;         // a start/stop is in flight; guards double-clicks

const $ = (id) => document.getElementById(id);
const video = $('video');

// ── data ────────────────────────────────────────────────────────────────────

async function api(path, opts) {
  const res = await fetch(`/api/streams${path}`, opts);
  const data = await res.json().catch(() => ({ error: 'bad JSON from dashboard' }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function refresh() {
  try {
    const d = await api('/status');
    lastStatus = Object.fromEntries(d.slots.map((s) => [s.slot, s]));

    // Tell the station every live slot is still wanted. Only the active tab has a
    // player, so background slots fetch no playlist and the idle reaper would take
    // them out from under a viewer who is watching another tab. This poll stops when
    // the page is hidden or closed, so an abandoned page still loses its slots.
    const live = d.slots.filter((s) => s.state === 'starting' || s.state === 'running')
                        .map((s) => s.slot);
    if (live.length) {
      api('/keepalive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slots: live }),
      }).catch(() => {});   // best-effort: a missed keepalive costs at most one poll
    }
    if (d.idle_secs) {
      $('reaper-hint').textContent =
        `Slots keep running while this page is open — switching tabs does not stop them. ` +
        `Close or hide the page and they all stop after ${Math.round(d.idle_secs / 60)} minutes, ` +
        `so nothing keeps pulling a stream unattended.`;
    }
  } catch (e) {
    // Station down (502) or dashboard restarting: show it, keep polling.
    lastStatus = {};
    for (const n of SLOTS) lastStatus[n] = { slot: n, state: 'unknown', error: e.message };
  }
  render();
}

// ── player ──────────────────────────────────────────────────────────────────

function detachPlayer() {
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute('src');
  video.load();
  video.hidden = true;
  $('placeholder').hidden = false;
  $('playhint').hidden = true;
}

// play() rejects if it is called before there is anything to play, and browsers may
// refuse autoplay outright. Either way the viewer would just see a frozen frame, so
// failure has to become a visible affordance rather than a swallowed promise.
function tryPlay() {
  const p = video.play();
  if (p && p.catch) p.catch(() => { $('playhint').hidden = false; });
}

function attachPlayer(slot) {
  detachPlayer();
  const src = `/hls/slot${slot}/index.m3u8`;
  video.hidden = false;
  $('placeholder').hidden = true;

  if (window.Hls && Hls.isSupported()) {
    hls = new Hls({
      // Ride the live edge: sit 2 segments back and, after a stall or a Twitch ad
      // break, speed up slightly to reel the delay back in instead of drifting.
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 5,
      maxLiveSyncPlaybackRate: 1.05,
      lowLatencyMode: true,
    });
    hls.on(Hls.Events.ERROR, (_evt, data) => {
      if (!data.fatal) return;
      // A slot that just started may 404 for a beat before the first playlist is
      // written; hls.js recovers on its own. Only give up on non-network fatals.
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
      else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
      else detachPlayer();
    });
    // Play only once there is a manifest — calling play() straight after attachMedia
    // races the first playlist fetch and lands on a loaded-but-paused player.
    hls.on(Hls.Events.MANIFEST_PARSED, tryPlay);
    hls.loadSource(src);
    hls.attachMedia(video);
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = src;                // Safari / iOS play HLS natively
    video.addEventListener('loadedmetadata', tryPlay, { once: true });
  } else {
    detachPlayer();
    $('placeholder').innerHTML = '<div class="big">This browser cannot play HLS</div>';
  }
}

// ── render ──────────────────────────────────────────────────────────────────

function slotLabel(s) {
  if (!s || s.state === 'idle') return 'empty';
  if (s.channel) return s.channel;
  if (s.url) { try { return new URL(s.url).hostname; } catch (_) { return 'url'; } }
  return s.state;
}

function render() {
  // tabs
  const tabs = $('tabs');
  tabs.innerHTML = '';
  for (const n of SLOTS) {
    const s = lastStatus[n] || { state: 'idle' };
    const btn = document.createElement('button');
    btn.className = 'tab' + (n === active ? ' active' : '');
    btn.innerHTML = `<span class="dot ${s.state}"></span><span class="label">${n}. ${slotLabel(s)}</span>`;
    btn.addEventListener('click', () => selectSlot(n));
    tabs.appendChild(btn);
  }

  // status bar for the active slot
  const s = lastStatus[active] || { state: 'idle' };
  const bar = $('statusbar');
  bar.innerHTML = '';
  const badge = document.createElement('span');
  badge.className = `badge ${s.state}`;
  badge.textContent = s.state;
  bar.appendChild(badge);

  const bits = [];
  if (s.channel) bits.push(`${s.platform}/${s.channel}`);
  if (s.url) bits.push(s.url);
  if (s.profile) bits.push(s.profile);
  if (s.quality) bits.push(s.quality);
  if (s.uptime_s != null) bits.push(`up ${s.uptime_s}s`);
  if (s.last_segment_age_s != null) bits.push(`last segment ${s.last_segment_age_s}s ago`);
  if (bits.length) {
    const span = document.createElement('span');
    span.textContent = bits.join('  ·  ');
    bar.appendChild(span);
  }
  if (s.error) {
    const err = document.createElement('span');
    err.className = 'err';
    err.textContent = s.error;
    bar.appendChild(err);
  }

  // A stream that is running but whose segments have gone stale is stalled upstream —
  // usually a Twitch ad break or streamlink needing an upgrade. Say so rather than
  // leaving the viewer staring at a frozen frame.
  if (s.state === 'running' && s.last_segment_age_s != null && s.last_segment_age_s > 20) {
    const warn = document.createElement('span');
    warn.className = 'err';
    warn.textContent = 'No new video for a while — the source may be stalled (ad break?) or ending.';
    bar.appendChild(warn);
  }

  $('stop').disabled = busy || !['starting', 'running', 'ended'].includes(s.state);
  $('start-channel').disabled = busy;
  $('start-url').disabled = busy;

  // player follows the active slot's state
  const shouldPlay = s.state === 'running';
  if (shouldPlay && !hls && !video.src) attachPlayer(active);
  if (!shouldPlay && (hls || video.src)) {
    detachPlayer();
    $('placeholder').innerHTML = s.state === 'ended'
      ? '<div class="big">Stream ended</div><div>See the message below the player.</div>'
      : '<div class="big">Nothing playing in this slot</div><div>Pick a preset below, or enter a channel / direct stream URL.</div>';
  }
}

function selectSlot(n) {
  if (n === active) return;
  active = n;
  detachPlayer();   // background slots keep running server-side; only the player stops
  render();
}

// ── actions ─────────────────────────────────────────────────────────────────

async function start(body) {
  busy = true; render();
  try {
    await api('/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot: active, ...body }),
    });
    lastStatus[active] = { slot: active, state: 'starting' };
  } catch (e) {
    lastStatus[active] = { slot: active, state: 'ended', error: e.message };
  } finally {
    busy = false; render();
    setTimeout(refresh, 1500);   // first real state usually lands within a couple of seconds
  }
}

async function stop() {
  busy = true; render();
  try {
    await api('/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot: active }),
    });
  } catch (e) {
    lastStatus[active] = { slot: active, state: 'ended', error: e.message };
  } finally {
    busy = false;
    detachPlayer();
    refresh();
  }
}

async function loadPresets() {
  const box = $('presets');
  try {
    const d = await api('/presets');
    const groups = d.groups || [];
    if (!groups.length) { box.innerHTML = '<span class="hint">No presets defined.</span>'; return; }
    box.innerHTML = '';
    for (const g of groups) {
      const row = document.createElement('div');
      row.className = 'preset-row';
      const lab = document.createElement('span');
      lab.className = 'group-label';
      lab.textContent = g.label || g.name;
      row.appendChild(lab);
      for (const c of g.channels || []) {
        const chip = document.createElement('button');
        chip.className = 'chip';
        chip.innerHTML = `${c.label || c.channel}<span class="plat">${c.platform}</span>`;
        chip.addEventListener('click', () => {
          $('platform').value = c.platform;
          $('channel').value = c.channel;
          start({ type: 'channel', platform: c.platform, channel: c.channel,
                  quality: $('quality').value || undefined, profile: $('profile').value });
        });
        row.appendChild(chip);
      }
      box.appendChild(row);
    }
  } catch (e) {
    box.innerHTML = `<span class="hint">Presets unavailable: ${e.message}</span>`;
  }
}

// ── polling lifecycle ───────────────────────────────────────────────────────

function startPolling() {
  if (pollTimer) return;
  refresh();
  pollTimer = setInterval(refresh, POLL_MS);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

document.addEventListener('visibilitychange', () => {
  document.hidden ? stopPolling() : startPolling();
});
window.addEventListener('pagehide', () => { stopPolling(); detachPlayer(); });

// ── wire up ─────────────────────────────────────────────────────────────────

$('start-channel').addEventListener('click', () => {
  const channel = $('channel').value.trim();
  if (!channel) { $('channel').focus(); return; }
  start({ type: 'channel', platform: $('platform').value, channel,
          quality: $('quality').value || undefined, profile: $('profile').value });
});
$('channel').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('start-channel').click(); });

$('start-url').addEventListener('click', () => {
  const url = $('url').value.trim();
  if (!url) { $('url').focus(); return; }
  start({ type: 'url', url, profile: $('profile').value });
});
$('url').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('start-url').click(); });

$('stop').addEventListener('click', stop);
$('playhint').addEventListener('click', () => { $('playhint').hidden = true; tryPlay(); });

// ── theater mode ────────────────────────────────────────────────────────────
// Bigger player without fullscreen: the tabs and status line stay visible, so you
// can still see which slots are live and switch between them. The preference is
// remembered, since whoever wants a big player once usually wants it every time.

function setTheater(on) {
  document.body.classList.toggle('theater', on);
  $('theater').textContent = on ? '⛶ Exit theater' : '⛶ Theater';
  try { localStorage.setItem('streams-theater', on ? '1' : '0'); } catch (_) {}
}

$('theater').addEventListener('click', () => setTheater(!document.body.classList.contains('theater')));

document.addEventListener('keydown', (e) => {
  // Never steal a keystroke aimed at the channel or URL box.
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if (e.key === 't' || e.key === 'T') setTheater(!document.body.classList.contains('theater'));
  // Escape leaves theater, matching what it does in fullscreen. Only when already in
  // theater, so it doesn't swallow Escape from anything else on the page.
  else if (e.key === 'Escape' && document.body.classList.contains('theater')) setTheater(false);
});

try { if (localStorage.getItem('streams-theater') === '1') setTheater(true); } catch (_) {}

loadPresets();
startPolling();
