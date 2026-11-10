"""The control API on :8080 that the dashboards proxy to.

    GET  /health    {ok, enabled, post_time, timezone, <health_extra>, last_post_at,
                     last_status, next_post_at}  — homelab-db's bot check reads it too
    GET  /config    config with webhook masked and secrets blanked (+ *_configured)
    PUT  /config    merge known keys, validate, save, wake the scheduler
    GET  /preview   the bot's preview(cfg) dict; 502 {"error"} if building it fails
    POST /send      post now (forced); 200/502 {"ok", "detail"}
    GET  <route>    bot-specific extras: routes[path](cfg, query) -> (code, obj)
Anything else is 404 {"error": "not found"}.
"""
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from .log import log


def make_handler(bot):
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
            path, _, query = self.path.partition("?")
            cfg = bot.store.load()
            if path == "/health":
                with bot.lock:
                    st = dict(bot.status)
                extra = bot.health_extra(cfg) if bot.health_extra else {}
                self._send(200, {"ok": True, "enabled": cfg["enabled"],
                                 "post_time": cfg["post_time"], "timezone": cfg["timezone"],
                                 **extra, **st})
            elif path == "/config":
                self._send(200, bot.store.public(cfg))
            elif path == "/preview":
                try:
                    self._send(200, bot.preview(cfg))
                except Exception as e:
                    self._send(502, {"error": str(e)})
            elif path in bot.routes:
                code, obj = bot.routes[path](cfg, query)
                self._send(code, obj)
            else:
                self._send(404, {"error": "not found"})

        def do_PUT(self):
            if self.path.partition("?")[0] != "/config":
                return self._send(404, {"error": "not found"})
            try:
                incoming = self._body()
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            current = bot.store.load()
            merged = bot.store.merge(current, incoming)
            err = bot.store.validate(merged)
            if err:
                return self._send(400, {"error": err})
            with bot.lock:
                bot.store.save(merged)
            bot.wake.set()  # reschedule immediately
            extra = f" {bot.describe(merged)}" if bot.describe else ""
            log(f"config updated: enabled={merged['enabled']} post_time={merged['post_time']}{extra}")
            self._send(200, bot.store.public(merged))

        def do_POST(self):
            if self.path.partition("?")[0] != "/send":
                return self._send(404, {"error": "not found"})
            cfg = bot.store.load()
            ok, detail = bot.post_report(cfg, force=True)
            with bot.lock:
                bot.status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
                bot.status["last_status"] = f"manual: {detail}" if ok else f"manual failed: {detail}"
            log(f"manual send: {'ok — ' + detail if ok else 'FAILED — ' + detail}")
            self._send(200 if ok else 502, {"ok": ok, "detail": detail})

    return Handler
