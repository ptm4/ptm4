#!/usr/bin/env python3
"""
stream-station.py — server-side vlcwatcher: resolves live streams (streamlink) and
remuxes them to browser-playable HLS (VLC livehttp), driven by the rpi dashboard's
Streams page. Runs as a container on noblenumbat (see ../docker-compose.custom.yaml);
the rpi webapp proxies control calls here and nginx proxies /hls same-origin.

WHY REMUX, NOT TRANSCODE
  Twitch/YouTube/Kick already deliver H.264+AAC in TS — VLC only re-cuts it into
  HLS segments (~5-15% of one core per slot). This host is a laptop with a thermal
  outage on record (2026-07-16); transcode is deliberately not offered. If it ever
  is, copy jellyfin's /dev/dri + group_add 992 passthrough from the compose overlay.

PIPELINE (per slot, up to 4)
  channel: streamlink --stdout <watch-url> <quality>  |  cvlc - --sout livehttp
  url:     cvlc <url> --sout livehttp                 (no streamlink)
  Segments land in /hls/slot<N>/ (a tmpfs — never the NVMe). --play-and-exit makes
  VLC exit on stdin EOF, so "stream ended" surfaces as clean process death, which
  the monitor thread turns into state=ended + a stderr tail in /status.

ENDPOINTS (token = Authorization: Bearer $HL_STREAM_TOKEN, required on POSTs)
  GET  /status            per-slot state machine (idle|starting|running|ended)
  GET  /presets           channel groups from the bind-mounted presets.json
  GET  /hls/slot<N>/<f>   playlist + segments, no token (nginx-proxied to browsers);
                          each index.m3u8 fetch stamps the slot's watch time
  POST /start             {slot, type: channel|url, platform?, channel?, url?,
                           quality?, profile?}   profile: low-latency (default)|smooth
  POST /stop              {slot}
  POST /keepalive         {slots:[N,…]} — "these are still wanted"; see below

IDLE REAPER
  A slot nobody has fetched the playlist for in HL_STREAM_IDLE_SECS (default 300)
  is stopped with error "reaped: idle" — the thermal/bandwidth backstop: nothing
  pulls a live stream unattended past ~5 minutes.

  "Attended" deliberately means the Streams page is OPEN AND VISIBLE, not "currently
  on screen in the player". The page is tabbed: only the active tab holds a player, so
  a background slot fetches no playlist and would otherwise be reaped out from under a
  viewer who is watching a different tab. The page therefore posts /keepalive for every
  slot it still wants while it polls, and stops posting the moment it is hidden or
  closed — so an abandoned page still loses every slot on schedule.

SECURITY POSTURE
  Direct-URL /start makes this host dial an arbitrary URL — that is the feature,
  same LAN-trust stance as the dashboard's other write buttons (cf. the fixed-list
  reasoning in webapp routes/dashboard.js linkcheck). Mitigations: token-gated
  POSTs (token held only by the webapp backend), scheme whitelist, channel-name
  regex, argv exec (no shell), and only /hls GETs are ever exposed through nginx.
"""

import hmac
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

VERSION = "0.1.0"

TOKEN = os.environ.get("HL_STREAM_TOKEN", "")
PORT = int(os.environ.get("HL_STREAM_PORT", "8098"))
HLS_ROOT = os.environ.get("HL_STREAM_HLS_ROOT", "/hls")
PRESETS_PATH = os.environ.get("HL_STREAM_PRESETS", "/config/presets.json")
IDLE_SECS = int(os.environ.get("HL_STREAM_IDLE_SECS", "300"))
SLOT_COUNT = 4
# streamlink resolution + first VLC segment cut normally lands in <10s; past this
# the pipeline is declared dead rather than left spinning in "starting" forever.
START_TIMEOUT = 45

QUALITY_DEFAULT = "best,1440p60,1440p,1080p60,1080p,720p60,720p,worst"

# seglen must stay a multiple of the source keyframe interval (Twitch: 2s) or VLC
# cuts mid-GOP and hls.js stalls. numsegs bounds the tmpfs window per slot.
PROFILES = {
    "low-latency": {"seglen": 2, "numsegs": 8, "live_edge": 2},
    "smooth": {"seglen": 4, "numsegs": 6, "live_edge": 3},
}

# Same mapping as homelab/tools/misc/vlcwatcher stream_url() — keep in sync.
PLATFORM_URLS = {
    "twitch": "https://www.twitch.tv/{}",
    "youtube": "https://www.youtube.com/@{}/live",
    "kick": "https://kick.com/{}",
}

CHANNEL_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")
QUALITY_RE = re.compile(r"^[A-Za-z0-9_,\-.]{1,128}$")
HLS_FILE_RE = re.compile(r"^[A-Za-z0-9_-]+\.(ts|m3u8)$")
ALLOWED_SCHEMES = ("http", "https", "rtsp", "rtmp")


def _drain(pipe, tail):
    """Drain a child's stderr into a bounded tail so /status can show why it died
    without an unread pipe ever blocking the child."""
    try:
        for line in iter(pipe.readline, b""):
            tail.append(line.decode("utf-8", "replace").rstrip())
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


class Slot:
    def __init__(self, n):
        self.n = n
        self.lock = threading.Lock()
        self.dir = os.path.join(HLS_ROOT, f"slot{n}")
        self._reset_locked()

    def _reset_locked(self):
        self.state = "idle"
        self.type = None
        self.platform = None
        self.channel = None
        self.url = None
        self.quality = None
        self.profile = None
        self.started_at = None
        self.error = None
        self.procs = []
        self.tails = []
        self.last_index_fetch = None
        self.stop_reason = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self, req):
        """Validate and launch. Returns (http_code, payload)."""
        stype = req.get("type")
        profile_name = req.get("profile", "low-latency")
        if profile_name not in PROFILES:
            return 400, {"error": f"unknown profile: {profile_name}"}
        profile = PROFILES[profile_name]

        quality = req.get("quality") or QUALITY_DEFAULT
        if not QUALITY_RE.match(quality):
            return 400, {"error": "bad quality string"}

        if stype == "channel":
            platform = str(req.get("platform", "")).lower()
            channel = str(req.get("channel", ""))
            if platform not in PLATFORM_URLS:
                return 400, {"error": f"unsupported platform: {platform or '(none)'}"}
            if not CHANNEL_RE.match(channel):
                return 400, {"error": "bad channel name"}
            source_desc = {"platform": platform, "channel": channel}
        elif stype == "url":
            url = str(req.get("url", ""))
            scheme = urlparse(url).scheme.lower()
            if scheme not in ALLOWED_SCHEMES:
                return 400, {"error": f"scheme must be one of {'/'.join(ALLOWED_SCHEMES)}"}
            source_desc = {"url": url}
        else:
            return 400, {"error": "type must be 'channel' or 'url'"}

        with self.lock:
            if self.state in ("starting", "running"):
                return 409, {"error": f"slot {self.n} is {self.state}"}
            self._reset_locked()
            self.state = "starting"
            self.type = stype
            self.quality = quality
            self.profile = profile_name
            self.started_at = time.time()
            # Counts as "watched" until a real playlist fetch arrives, so the idle
            # reaper doesn't kill a slot the viewer is still connecting to.
            self.last_index_fetch = time.time()
            self.platform = source_desc.get("platform")
            self.channel = source_desc.get("channel")
            self.url = source_desc.get("url")

            try:
                self._clean_dir()
                self._spawn_locked(profile)
            except Exception as exc:  # noqa: BLE001
                self._kill_procs_locked()
                self.state = "ended"
                self.error = f"spawn failed: {exc}"
                return 500, {"error": self.error}

        threading.Thread(target=self._monitor, daemon=True).start()
        return 200, {"ok": True, "slot": self.n, "state": "starting"}

    def _clean_dir(self):
        os.makedirs(self.dir, exist_ok=True)
        for f in os.listdir(self.dir):
            if f.endswith((".ts", ".m3u8")):
                try:
                    os.unlink(os.path.join(self.dir, f))
                except OSError:
                    pass

    def _sout(self, profile):
        return (
            "#std{access=livehttp{"
            f"seglen={profile['seglen']},delsegs=true,numsegs={profile['numsegs']},"
            f"index={self.dir}/index.m3u8,index-url=seg-########.ts"
            "},mux=ts{use-key-frames},"
            f"dst={self.dir}/seg-########.ts}}"
        )

    def _spawn_locked(self, profile):
        sout = self._sout(profile)
        if self.type == "channel":
            watch_url = PLATFORM_URLS[self.platform].format(self.channel)
            sl_argv = [
                "streamlink", "--stdout",
                "--hls-live-edge", str(profile["live_edge"]),
                "--ringbuffer-size", "32M",
                "--loglevel", "info",
            ]
            if self.platform == "twitch":
                sl_argv += ["--twitch-disable-ads", "--twitch-low-latency"]
            sl_argv += [watch_url, self.quality]
            vlc_argv = ["cvlc", "-", "--play-and-exit", "--sout", sout]

            sl_tail, vlc_tail = deque(maxlen=50), deque(maxlen=50)
            sl = subprocess.Popen(sl_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                vlc = subprocess.Popen(vlc_argv, stdin=sl.stdout, stderr=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL)
            except Exception:
                sl.kill()
                sl.wait()
                raise
            # Parent must drop its copy of the pipe or VLC never sees EOF when
            # streamlink exits (stream over) — the whole death-detection hinges here.
            sl.stdout.close()
            self.procs = [("streamlink", sl, sl_tail), ("vlc", vlc, vlc_tail)]
            threading.Thread(target=_drain, args=(sl.stderr, sl_tail), daemon=True).start()
            threading.Thread(target=_drain, args=(vlc.stderr, vlc_tail), daemon=True).start()
        else:
            vlc_tail = deque(maxlen=50)
            vlc = subprocess.Popen(
                ["cvlc", self.url, "--play-and-exit", "--network-caching=1000", "--sout", sout],
                stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
            self.procs = [("vlc", vlc, vlc_tail)]
            threading.Thread(target=_drain, args=(vlc.stderr, vlc_tail), daemon=True).start()

    def _monitor(self):
        """Owns the slot from spawn to death: flips starting→running when the first
        playlist lands, then waits for any process to exit and cleans up the rest."""
        index = os.path.join(self.dir, "index.m3u8")
        deadline = time.time() + START_TIMEOUT
        while True:
            with self.lock:
                if self.state != "starting":
                    break  # stopped while starting
                procs = list(self.procs)
                if os.path.exists(index):
                    self.state = "running"
                    break
            if any(p.poll() is not None for _, p, _ in procs):
                self._finish("pipeline died before producing a playlist")
                return
            if time.time() > deadline:
                self._finish(f"timed out after {START_TIMEOUT}s waiting for first playlist")
                return
            time.sleep(0.5)

        while True:
            with self.lock:
                if self.state != "running":
                    break  # stopped externally; stop() already finished the slot
                procs = list(self.procs)
            if any(p.poll() is not None for _, p, _ in procs):
                self._finish("stream ended")
                return
            time.sleep(0.5)

    def _finish(self, default_reason):
        """Terminate whatever is left and record why. Called by the monitor thread
        (natural death) — user stops go through stop() which does its own finish."""
        with self.lock:
            if self.state in ("idle", "ended"):
                return
            details = self._kill_procs_locked()
            self.state = "ended"
            self.error = f"{default_reason}{details}"

    def _kill_procs_locked(self):
        """SIGTERM then SIGKILL the pipeline; returns a compact death report built
        from exit codes + the last stderr line of whichever process failed."""
        notes = []
        for name, p, tail in self.procs:
            if p.poll() is None:
                p.terminate()
        deadline = time.time() + 5
        for name, p, tail in self.procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for name, p, tail in self.procs:
            # 0 = clean; negative = died by our signal (not interesting)
            if p.returncode and p.returncode > 0:
                last = next((l for l in reversed(tail) if l.strip()), "")
                notes.append(f"{name} exit {p.returncode}" + (f": {last}" if last else ""))
        return (" — " + "; ".join(notes)) if notes else ""

    def stop(self, reason=None):
        """User stop → idle; reaper stop → ended with the reason left visible."""
        with self.lock:
            if self.state not in ("starting", "running"):
                # stop on an idle/ended slot just clears any stale error
                self._reset_locked()
                return 200, {"ok": True, "slot": self.n, "state": "idle"}
            self._kill_procs_locked()
            if reason:
                self.state = "ended"
                self.error = reason
            else:
                self._reset_locked()
            return 200, {"ok": True, "slot": self.n, "state": self.state}

    # ── reporting ──────────────────────────────────────────────────────────────

    def status(self):
        with self.lock:
            now = time.time()
            seg_age = None
            if self.state == "running":
                try:
                    mtimes = [os.path.getmtime(os.path.join(self.dir, f))
                              for f in os.listdir(self.dir) if f.endswith(".ts")]
                    if mtimes:
                        seg_age = round(now - max(mtimes), 1)
                except OSError:
                    pass
            return {
                "slot": self.n,
                "state": self.state,
                "type": self.type,
                "platform": self.platform,
                "channel": self.channel,
                "url": self.url,
                "quality": self.quality,
                "profile": self.profile,
                "started_at": self.started_at,
                "uptime_s": round(now - self.started_at) if self.started_at and self.state in ("starting", "running") else None,
                "last_index_fetch_s": round(now - self.last_index_fetch) if self.last_index_fetch and self.state == "running" else None,
                "last_segment_age_s": seg_age,
                "error": self.error,
            }


SLOTS = {n: Slot(n) for n in range(1, SLOT_COUNT + 1)}


def _reaper():
    while True:
        time.sleep(30)
        for slot in SLOTS.values():
            with slot.lock:
                stale = (slot.state == "running" and slot.last_index_fetch
                         and time.time() - slot.last_index_fetch > IDLE_SECS)
            if stale:
                print(f"[reaper] slot {slot.n}: no playlist fetch in {IDLE_SECS}s — stopping", flush=True)
                slot.stop(reason="reaped: idle")


# ── HTTP ───────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = f"stream-station/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # /hls playlist polls arrive every ~2s per viewer — logging them would be
        # pure noise. Control-plane requests still log.
        if not self.path.startswith("/hls/"):
            print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not TOKEN:
            self._json(503, {"error": "HL_STREAM_TOKEN not configured on stream-station"})
            return False
        got = self.headers.get("Authorization", "")
        if hmac.compare_digest(got, f"Bearer {TOKEN}"):
            return True
        self._json(401, {"error": "unauthorized"})
        return False

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def _slot_from(self, req):
        slot = req.get("slot")
        if not isinstance(slot, int) or slot not in SLOTS:
            return None
        return SLOTS[slot]

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/status":
            return self._json(200, {
                "version": VERSION,
                "idle_secs": IDLE_SECS,
                "profiles": sorted(PROFILES),
                "slots": [SLOTS[n].status() for n in sorted(SLOTS)],
            })
        if path == "/presets":
            try:
                with open(PRESETS_PATH, encoding="utf-8") as f:
                    return self._json(200, json.load(f))
            except (OSError, json.JSONDecodeError) as exc:
                return self._json(200, {"groups": [], "quality_default": QUALITY_DEFAULT,
                                        "error": f"presets unreadable: {exc}"})
        if path.startswith("/hls/"):
            return self._serve_hls(path)
        return self._json(404, {"error": "not found"})

    def _serve_hls(self, path):
        parts = path.split("/")  # ['', 'hls', 'slotN', 'file']
        if len(parts) != 4:
            return self._json(404, {"error": "not found"})
        _, _, slot_dir, fname = parts
        m = re.match(r"^slot([1-4])$", slot_dir)
        if not m or not HLS_FILE_RE.match(fname):
            return self._json(404, {"error": "not found"})
        slot = SLOTS[int(m.group(1))]
        fpath = os.path.join(slot.dir, fname)
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError:
            return self._json(404, {"error": "not found"})
        if fname.endswith(".m3u8"):
            ctype, cache = "application/vnd.apple.mpegurl", "no-store"
            with slot.lock:
                slot.last_index_fetch = time.time()
        else:
            # segments are immutable once written; a short TTL lets nginx/browser
            # re-use them across the 2s playlist polls without ever serving stale
            ctype, cache = "video/mp2t", "max-age=10"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/start", "/stop", "/keepalive"):
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return
        req = self._body()
        if req is None:
            return self._json(400, {"error": "invalid JSON body"})

        if path == "/keepalive":
            wanted = req.get("slots")
            if not isinstance(wanted, list):
                return self._json(400, {"error": "slots must be a list of integers"})
            kept = []
            for n in wanted:
                slot = SLOTS.get(n) if isinstance(n, int) else None
                if slot is None:
                    continue
                with slot.lock:
                    if slot.state in ("starting", "running"):
                        slot.last_index_fetch = time.time()
                        kept.append(n)
            return self._json(200, {"ok": True, "kept": kept})

        slot = self._slot_from(req)
        if slot is None:
            return self._json(400, {"error": f"slot must be an integer 1-{SLOT_COUNT}"})
        code, payload = slot.start(req) if path == "/start" else slot.stop()
        return self._json(code, payload)


def _shutdown(signum, frame):
    print(f"[main] signal {signum} — stopping all slots", flush=True)
    for slot in SLOTS.values():
        slot.stop()
    os._exit(0)


def main():
    os.makedirs(HLS_ROOT, exist_ok=True)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    threading.Thread(target=_reaper, daemon=True).start()
    print(f"[main] stream-station v{VERSION} on :{PORT} — slots={SLOT_COUNT}, "
          f"idle reap {IDLE_SECS}s, token {'set' if TOKEN else 'MISSING'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
