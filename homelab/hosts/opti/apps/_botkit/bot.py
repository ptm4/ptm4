"""Bot: wires a bot's domain logic to the shared config store, scheduler and API.

A bot supplies:
  post_report(cfg, force=False) -> (ok, detail)   build + deliver; force = Send now
  preview(cfg) -> dict                            {"payload", "failed", ...} for /preview
and optionally validate (its own fields), routes (extra GETs), health_extra, describe
(extra text for the "config updated" log line) and dry_run (custom --dry-run).

Modes (Bot.main):
  (default)   daemon: control API thread + scheduler loop in the main thread
  --once      build + post now, then exit
  --dry-run   build + print the payload, no post, then exit
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

from .api import make_handler
from .config import ConfigStore
from .log import log
from .scheduler import DailyScheduler

API_PORT = 8080


class Bot:
    def __init__(self, name, defaults, post_report, preview, env=None, secret_fields=(),
                 extra_keys=(), validate=None, routes=None, health_extra=None,
                 describe=None, dry_run=None, data_dir=None, port=API_PORT):
        self.name = name
        self.data_dir = data_dir or os.environ.get("DATA_DIR", "/data")
        self.store = ConfigStore(self.data_dir, defaults, env=env, secret_fields=secret_fields,
                                 extra_keys=extra_keys, validate_extra=validate)
        self.post_report = post_report
        self.preview = preview
        self.routes = dict(routes or {})
        self.health_extra = health_extra
        self.describe = describe
        self.dry_run = dry_run
        self.port = port
        self.lock = threading.Lock()
        self.wake = threading.Event()   # poked on config change so the scheduler recomputes
        self.status = {"last_post_at": None, "last_status": None, "next_post_at": None}
        self.scheduler = DailyScheduler(
            self.store, lambda cfg: self.post_report(cfg), self.status, self.lock, self.wake,
            os.path.join(self.data_dir, "last_post"))
        self.Handler = make_handler(self)

    def load_config(self):
        return self.store.load()

    def _default_dry_run(self, cfg):
        out = self.preview(cfg)
        print(json.dumps(out["payload"], indent=2, ensure_ascii=False))
        for k, v in out.items():
            if k not in ("payload", "failed"):
                print(f"{k}: {v}", file=sys.stderr)
        if out.get("failed"):
            print(f"WARNING: no data for {out['failed']}", file=sys.stderr)
            return 1
        return 0

    def main(self, argv):
        if "--dry-run" in argv or "--once" in argv:
            try:
                cfg = self.store.load()
            except OSError:  # DATA_DIR not writable (e.g. running outside the container)
                cfg = self.store.fallback()
            if "--dry-run" in argv:
                return (self.dry_run or self._default_dry_run)(cfg)
            ok, detail = self.post_report(cfg, force=True)
            print(detail)
            return 0 if ok else 1

        server = ThreadingHTTPServer(("0.0.0.0", self.port), self.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        log(f"control API listening on :{self.port}")
        self.store.load()  # seed on first boot
        self.scheduler.run()
        return 0
