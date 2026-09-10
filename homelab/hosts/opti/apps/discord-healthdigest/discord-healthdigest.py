#!/usr/bin/env python3
"""
discord-healthdigest — daily homelab health report posted to a Discord channel
webhook as an embed, with an HTTP control API for the rpi webapp's
"Health Bot" tab. Clone of discord-weather's scaffolding; only the domain
logic differs.

Data sources:
  • homelab-doctor-latest.json from the agent-logs mount (hosts, services,
    VPN watchdog, autoupdate results — the doctor gathers these over SSH
    from opti every 30 min; this bot never SSHes anywhere)
  • Pi-hole v6 API, queried live (it runs on this same rpi)

Config lives in /data/config.json (named volume, seeded from env on first
boot); the webapp edits it via the API — the scheduler picks changes up
immediately, no restart needed.

Modes:
  (default)   daemon: scheduler loop + control API on :8080
  --once      build + post the report now, then exit
  --dry-run   build + print the payload, no post, then exit
"""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LAST_POST_PATH = os.path.join(DATA_DIR, "last_post")
API_PORT = 8080

AGENT_LOGS_DIR = os.environ.get("AGENT_LOGS_DIR", "/agent-logs")
DOCTOR_REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "homelab-doctor-latest.json")
DISPATCHER_URL = os.environ.get("DISPATCHER_URL", "")
HL_DISPATCH_TOKEN = os.environ.get("HL_DISPATCH_TOKEN", "")
FRESH_REPORT_WAIT = 90  # max seconds to wait for a dispatcher-kicked doctor run

COLOR_OK = 0x3BA55D
COLOR_WARN = 0xF0B232
COLOR_CRITICAL = 0xED4245

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "08:00",
    "timezone": "America/New_York",
    "message": "",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL_HEALTHDIGEST env on first boot
    "post_mode": "always",  # "always" | "alerts_only"
    "doctor_max_age_hours": 2,
    "pihole_url": f"http://{os.environ.get('RPI_IP') or '192.168.1.10'}",
    "pihole_password": "",  # seeded from PIHOLE_WEB_PASSWORD env on first boot
    "top_blocked_count": 3,
    "request_fresh_report": False,  # kick the doctor via the opti dispatcher before posting
}


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


# ── config store ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_wake = threading.Event()   # poked on config change so the scheduler recomputes
_status = {"last_post_at": None, "last_status": None, "next_post_at": None}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = dict(DEFAULT_CONFIG)
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_HEALTHDIGEST", "")
        cfg["pihole_password"] = os.environ.get("PIHOLE_WEB_PASSWORD", "")
        save_config(cfg)
        log(f"seeded default config at {CONFIG_PATH}")
    # env secrets as fallback if config never got them
    if not cfg.get("webhook_url"):
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_HEALTHDIGEST", "")
    if not cfg.get("pihole_password"):
        cfg["pihole_password"] = os.environ.get("PIHOLE_WEB_PASSWORD", "")
    # configs written before a key existed pick up its default
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def validate_config(cfg):
    """Returns an error string, or None if cfg is a valid full config."""
    if not isinstance(cfg, dict):
        return "config must be an object"
    if not isinstance(cfg.get("enabled"), bool):
        return "enabled must be true/false"
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg.get("post_time", ""))):
        return "post_time must be HH:MM (24h)"
    msg = cfg.get("message", "")
    if not isinstance(msg, str) or len(msg) > 2000:
        return "message must be text, max 2000 characters"
    try:
        ZoneInfo(str(cfg.get("timezone")))
    except Exception:
        return f"unknown timezone {cfg.get('timezone')!r}"
    if cfg.get("post_mode") not in ("always", "alerts_only"):
        return "post_mode must be 'always' or 'alerts_only'"
    if not isinstance(cfg.get("doctor_max_age_hours"), (int, float)) or cfg["doctor_max_age_hours"] <= 0:
        return "doctor_max_age_hours must be a positive number"
    if not str(cfg.get("pihole_url", "")).startswith(("http://", "https://")):
        return "pihole_url must be an http(s) URL"
    n = cfg.get("top_blocked_count")
    if not isinstance(n, int) or not 1 <= n <= 10:
        return "top_blocked_count must be 1–10"
    if not isinstance(cfg.get("request_fresh_report"), bool):
        return "request_fresh_report must be true/false"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    return None


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP helper ───────────────────────────────────────────────────────────────
def http_json(url, body=None, tries=3, method=None, headers=None, timeout=30):
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "discord-healthdigest (rpi homelab)",
                     **(headers or {})},
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(5)


# ── data sources ──────────────────────────────────────────────────────────────
def load_doctor():
    """The latest homelab-doctor report from the agent-logs mount."""
    with open(DOCTOR_REPORT_PATH) as f:
        return json.load(f)


def doctor_age_minutes(doctor):
    try:
        run_at = datetime.fromisoformat(doctor["run_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - run_at).total_seconds() / 60
    except (KeyError, ValueError, TypeError):
        return None


def request_fresh_doctor():
    """Kick a doctor run via the opti dispatcher and wait for the report to update.
    Best-effort: any failure just means we post from the existing report."""
    if not DISPATCHER_URL:
        raise RuntimeError("DISPATCHER_URL not set")
    before = load_doctor().get("run_at")
    http_json(f"{DISPATCHER_URL}/agents/homelab-doctor/run", body={},
              headers={"Authorization": f"Bearer {HL_DISPATCH_TOKEN}"}, tries=1, timeout=15)
    deadline = time.monotonic() + FRESH_REPORT_WAIT
    while time.monotonic() < deadline:
        time.sleep(5)
        if load_doctor().get("run_at") != before:
            return
    raise RuntimeError(f"report did not refresh within {FRESH_REPORT_WAIT}s")


def fetch_pihole(cfg):
    """Live Pi-hole v6 stats: summary + top blocked domains. Auths a session
    and always releases it (v6 caps concurrent sessions)."""
    base = cfg["pihole_url"].rstrip("/")
    pw = cfg.get("pihole_password", "")
    if not pw:
        raise RuntimeError("pihole_password not set")
    _, auth = http_json(f"{base}/api/auth", body={"password": pw}, tries=1, timeout=10)
    sid = auth["session"]["sid"]
    hdr = {"X-FTL-SID": sid}
    try:
        _, summary = http_json(f"{base}/api/stats/summary", headers=hdr, tries=1, timeout=10)
        _, top = http_json(
            f"{base}/api/stats/top_domains?blocked=true&count={cfg['top_blocked_count']}",
            headers=hdr, tries=1, timeout=10)
    finally:
        try:
            http_json(f"{base}/api/auth", method="DELETE", headers=hdr, tries=1, timeout=10)
        except RuntimeError:
            pass  # session expires on its own; don't mask the real error
    q = summary["queries"]
    return {"total": q["total"], "blocked": q["blocked"],
            "percent": q["percent_blocked"],
            "top": [(d["domain"], d["count"]) for d in (top or {}).get("domains", [])]}


# ── embed sections ────────────────────────────────────────────────────────────
# Each section returns (value_text, alert_bool); build_payload wraps every call
# in try/except so one dead source degrades to a placeholder, not a dead digest.
def fmt_int(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "?"


def section_hosts(doctor):
    lines, alert = [], False
    for h in doctor.get("hosts", []):
        m = h.get("metrics", {})
        if h.get("status") == "unknown":
            lines.append(f"❌ **{h['host']}** — unreachable")
            alert = True
            continue
        icon = "✅" if h.get("status") == "ok" else "⚠️"
        alert = alert or h.get("status") != "ok"
        parts = []
        if m.get("disk_used_pct") is not None:
            parts.append(f"disk {round(m['disk_used_pct'])}%")
        if m.get("pool"):
            parts.append(f"pool {round(m['pool']['used_pct'])}% "
                         f"({m['pool']['avail_gb']} GB free)")
        if m.get("containers") is not None:
            parts.append(f"{len(m['containers'])} containers")
        lines.append(f"{icon} **{h['host']}** — {' · '.join(parts) or 'no data'}")
    return "\n".join(lines) or "no host data", alert


def section_services(doctor):
    lines, alert = [], False
    for s in doctor.get("services", []):
        icon = "✅" if s.get("up") else "❌"
        alert = alert or not s.get("up")
        cert = f" · cert {s['cert_days_left']}d" if s.get("cert_days_left") is not None else ""
        lines.append(f"{icon} {s['name']}{cert}")
    return "\n".join(lines) or "no service data", alert


def section_pihole(cfg):
    p = fetch_pihole(cfg)
    lines = [f"{fmt_int(p['total'])} queries · {fmt_int(p['blocked'])} blocked "
             f"({p['percent']:.1f}%)"]
    lines += [f"• {dom} — {fmt_int(n)}" for dom, n in p["top"]]
    return "\n".join(lines), False


def section_vpn(doctor):
    vpn = None
    for h in doctor.get("hosts", []):
        vpn = (h.get("metrics") or {}).get("vpn")
        if vpn is not None:
            break
    if vpn is None:
        return "watchdog not reporting", False  # not deployed yet — neutral, not red
    st = vpn.get("status", "?")
    icon = "✅" if st == "ok" else "⚠️"
    fwd, qbt = vpn.get("forwarded_port", "?"), vpn.get("qbt_listen_port", "?")
    ports = f"port {fwd}" if fwd == qbt else f"port {fwd} / qBt {qbt} ⚠️ mismatch"
    lines = [f"{icon} {st} — {ports}",
             f"exit IP {vpn.get('public_ip') or '?'} · as of {vpn.get('ts', '?')}"]
    if vpn.get("actions"):
        lines.append("healed: " + "; ".join(vpn["actions"]))
    return "\n".join(lines), st != "ok"


def section_containers(doctor):
    total, bad = 0, []
    for h in doctor.get("hosts", []):
        for c in (h.get("metrics") or {}).get("containers") or []:
            total += 1
            if not (c.get("status") or "").startswith("Up"):
                bad.append(f"⚠️ {h['host']}/{c['name']}: {c['status']}")
    if bad:
        return "\n".join(bad), True
    return f"all {total} healthy", False


def section_updates(doctor):
    lines, alert = [], False
    for h in doctor.get("hosts", []):
        au = (h.get("metrics") or {}).get("autoupdate")
        if au is None:
            continue
        icon = {"ok": "✅", "error": "❌"}.get(au.get("result"), "⚠️")
        alert = alert or au.get("result") == "error"
        detail = au.get("last_run") or au.get("detail") or "?"
        reboot = " · reboot pending" if au.get("reboot_required") else ""
        lines.append(f"{icon} **{h['host']}** — {au.get('result', '?')} ({detail}){reboot}")
    return "\n".join(lines) or "no autoupdate data yet", False if not lines else alert


def section_stale(doctor):
    stale = doctor.get("stale_reports", [])
    if not stale:
        return None, False
    return "\n".join(f"⚠️ {s['file']} — {s['age_hours']}h old" for s in stale), True


def build_payload(cfg):
    """Build the webhook payload from the doctor report + live Pi-hole.
    Returns (payload, failed_sections, has_alerts)."""
    tz = cfg["timezone"]
    failed, has_alerts = [], False

    doctor, doctor_err = {}, None
    try:
        if cfg.get("request_fresh_report"):
            try:
                request_fresh_doctor()
            except Exception as e:
                log(f"fresh-report kick failed (posting from existing report): {e}")
        doctor = load_doctor()
    except Exception as e:
        doctor_err = str(e)
        log(f"doctor report unavailable: {e}")

    sections = [
        ("🖥️ Hosts", lambda: section_hosts(doctor)),
        ("🌐 Services", lambda: section_services(doctor)),
        ("🛡️ Pi-hole", lambda: section_pihole(cfg)),
        ("🔒 VPN (noblenumbat)", lambda: section_vpn(doctor)),
        ("📦 Containers", lambda: section_containers(doctor)),
        ("⬆️ Updates", lambda: section_updates(doctor)),
        ("🗂️ Stale reports", lambda: section_stale(doctor)),
    ]
    fields = []
    for name, fn in sections:
        try:
            value, alert = fn()
        except Exception as e:
            log(f"section {name!r} failed: {e}")
            value, alert = f"⚠️ unavailable ({type(e).__name__})", True
            failed.append(name)
        if value is None:
            continue  # section opted out (e.g. no stale reports)
        has_alerts = has_alerts or alert
        fields.append({"name": name, "value": value[:1024], "inline": False})

    doctor_status = doctor.get("status", "unknown")
    if doctor_err:
        has_alerts = True
    has_alerts = has_alerts or doctor_status not in ("ok", "unknown")

    now = datetime.now(ZoneInfo(tz))
    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc_lines = [f"**{date_str}**"]
    if doctor_err:
        desc_lines.append(f"⚠️ doctor report unavailable: {doctor_err}")
    else:
        desc_lines.append(doctor.get("summary", ""))
        age = doctor_age_minutes(doctor)
        if age is not None:
            if age > cfg["doctor_max_age_hours"] * 60:
                desc_lines.append(f"⚠️ doctor report is {age / 60:.1f}h old")
                has_alerts = True
            else:
                desc_lines.append(f"report {round(age)} min old")

    if doctor_status == "critical" or doctor_err:
        color = COLOR_CRITICAL
    elif has_alerts:
        color = COLOR_WARN
    else:
        color = COLOR_OK

    payload = {
        "username": "Homelab Health Digest",
        # explicit allow-list so @everyone/@here in the message actually ping
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": "🩺 Homelab Health Digest",
            "description": "\n".join(l for l in desc_lines if l),
            "color": color,
            "fields": fields,
            "footer": {"text": "homelab-doctor · Pi-hole"},
        }],
    }
    if cfg.get("message"):
        payload["content"] = cfg["message"]
    return payload, failed, has_alerts


def post_webhook(url, payload):
    status, _ = http_json(url, body=payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_report(cfg, force=False):
    """Build and post the report. Returns (ok, detail).
    Scheduled runs (force=False) respect post_mode=alerts_only; the webapp's
    Send-now button always posts."""
    payload, failed, has_alerts = build_payload(cfg)
    if not force and cfg.get("post_mode") == "alerts_only" and not has_alerts:
        return True, "skipped — all green (post_mode=alerts_only)"
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_HEALTHDIGEST / webhook_url not set"
    try:
        post_webhook(url, payload)
    except RuntimeError as e:
        return False, str(e)
    detail = "posted" + (f" (sections unavailable: {', '.join(failed)})" if failed else "")
    return True, detail


# ── scheduler ─────────────────────────────────────────────────────────────────
def read_last_post():
    try:
        with open(LAST_POST_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


def write_last_post(date_str):
    tmp = LAST_POST_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(date_str)
    os.replace(tmp, LAST_POST_PATH)


def next_post_dt(cfg, now):
    """Next scheduled datetime strictly after `now` (tz-aware)."""
    hh, mm = map(int, cfg["post_time"].split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def scheduled_post(cfg, today_str):
    _retry.update(date=today_str, at=datetime.now(ZoneInfo(cfg["timezone"])))
    ok, detail = post_report(cfg)
    with _lock:
        _status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
        _status["last_status"] = detail if ok else f"failed: {detail}"
    if ok:
        write_last_post(today_str)
    log(f"daily post: {'ok — ' + detail if ok else 'FAILED — ' + detail}")


RETRY_INTERVAL = 900  # a failed daily post is re-attempted every 15 min until it lands
_retry = {"date": None, "at": None}


def scheduler_loop():
    while True:
        cfg = load_config()
        tz = ZoneInfo(cfg["timezone"])
        now = datetime.now(tz)
        today = now.date().isoformat()

        if not cfg["enabled"]:
            with _lock:
                _status["next_post_at"] = None
            _wake.wait(timeout=3600)
            _wake.clear()
            continue

        # catch-up / retry: today's post is due but hasn't landed yet
        hh, mm = map(int, cfg["post_time"].split(":"))
        todays_slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= todays_slot and read_last_post() != today:
            if _retry["date"] == today:
                since = (now - _retry["at"]).total_seconds()
                if since < RETRY_INTERVAL:  # pace re-attempts after a failure
                    next_try = _retry["at"] + timedelta(seconds=RETRY_INTERVAL)
                    with _lock:
                        _status["next_post_at"] = next_try.isoformat(timespec="seconds")
                    if _wake.wait(timeout=RETRY_INTERVAL - since):
                        _wake.clear()
                    continue
                log(f"retrying today's post (last attempt {round(since / 60)} min ago)")
            else:
                log(f"catch-up: {today} {cfg['post_time']} is due, posting now")
            scheduled_post(cfg, today)
            continue

        nxt = next_post_dt(cfg, now)
        with _lock:
            _status["next_post_at"] = nxt.isoformat(timespec="seconds")
        wait = (nxt - now).total_seconds()
        if _wake.wait(timeout=min(wait, 3600)):
            _wake.clear()
            continue  # config changed — recompute
        if datetime.now(tz) >= nxt:
            scheduled_post(load_config(), nxt.date().isoformat())


# ── control API ───────────────────────────────────────────────────────────────
CONFIG_KEYS = ("enabled", "post_time", "timezone", "message", "webhook_url",
               "post_mode", "doctor_max_age_hours", "pihole_url",
               "pihole_password", "top_blocked_count", "request_fresh_report")


def public_config(cfg):
    pub = dict(cfg)
    pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
    pub["webhook_configured"] = bool(cfg.get("webhook_url"))
    pub["pihole_password"] = ""
    pub["pihole_password_configured"] = bool(cfg.get("pihole_password"))
    return pub


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # route access logs through our logger
        log(f"api {self.command} {self.path} — {args[0] if args else ''}")

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        path, _, _query = self.path.partition("?")
        cfg = load_config()
        if path == "/health":
            with _lock:
                st = dict(_status)
            self._send(200, {"ok": True, "enabled": cfg["enabled"],
                             "post_time": cfg["post_time"], "timezone": cfg["timezone"], **st})
        elif path == "/config":
            self._send(200, public_config(cfg))
        elif path == "/preview":
            try:
                payload, failed, has_alerts = build_payload(cfg)
                self._send(200, {"payload": payload, "failed": failed, "has_alerts": has_alerts})
            except Exception as e:
                self._send(502, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_PUT(self):
        if self.path.partition("?")[0] != "/config":
            return self._send(404, {"error": "not found"})
        try:
            incoming = self._body()
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        current = load_config()
        merged = {**current, **{k: v for k, v in incoming.items() if k in CONFIG_KEYS}}
        # masked/blank secrets in the payload mean "keep the current one"
        wh = incoming.get("webhook_url", "")
        if not wh or "…" in wh:
            merged["webhook_url"] = current.get("webhook_url", "")
        if not incoming.get("pihole_password"):
            merged["pihole_password"] = current.get("pihole_password", "")
        err = validate_config(merged)
        if err:
            return self._send(400, {"error": err})
        with _lock:
            save_config(merged)
        _wake.set()  # reschedule immediately
        log(f"config updated: enabled={merged['enabled']} post_time={merged['post_time']} "
            f"post_mode={merged['post_mode']}")
        self._send(200, public_config(merged))

    def do_POST(self):
        if self.path.partition("?")[0] != "/send":
            return self._send(404, {"error": "not found"})
        cfg = load_config()
        ok, detail = post_report(cfg, force=True)
        with _lock:
            _status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
            _status["last_status"] = f"manual: {detail}" if ok else f"manual failed: {detail}"
        log(f"manual send: {'ok — ' + detail if ok else 'FAILED — ' + detail}")
        self._send(200 if ok else 502, {"ok": ok, "detail": detail})


def main(argv):
    if "--dry-run" in argv or "--once" in argv:
        try:
            cfg = load_config()
        except OSError:  # DATA_DIR not writable (e.g. running outside the container)
            cfg = {**DEFAULT_CONFIG,
                   "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL_HEALTHDIGEST", ""),
                   "pihole_password": os.environ.get("PIHOLE_WEB_PASSWORD", "")}
        if "--dry-run" in argv:
            payload, failed, has_alerts = build_payload(cfg)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print(f"has_alerts: {has_alerts}", file=sys.stderr)
            if failed:
                print(f"WARNING: sections unavailable: {failed}", file=sys.stderr)
                return 1
            return 0
        ok, detail = post_report(cfg, force=True)
        print(detail)
        return 0 if ok else 1

    # daemon: control API thread + scheduler in main thread
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"control API listening on :{API_PORT}")
    load_config()  # seed on first boot
    scheduler_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
