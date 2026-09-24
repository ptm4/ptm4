#!/usr/bin/env python3
"""
notify.py — push a notification to the homelab's ntfy server (phone app over LAN/VPN).

Stdlib only, and it NEVER raises: a notification failing must not fail the thing that
was trying to report a failure. Import it or call it from a shell / systemd unit.

    from notify import notify
    notify("opti pool at 91%", "red is filling — check hl_metrics", priority="high",
           tags=["warning"], dedup_key="pool-opti")

    notify.py --title "..." [--priority high] [--tags a,b] [--dedup KEY] message...
    notify.py --unit-failed hl-collector@homelab-doctor.service   # used by OnFailure=

Server: ntfy on noblenumbat (http://192.168.1.6:2586) — off opti on purpose, so "opti is
down" and "DNS is down" are both still deliverable. See
homelab/hosts/noblenumbat/docker-compose.custom.yaml.

Env: HL_NTFY_URL (default http://192.168.1.6:2586), HL_NTFY_TOPIC (default homelab),
     HL_DATA_DIR (where the dedup state lives; default /tmp).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

NTFY_URL = os.environ.get("HL_NTFY_URL", "http://192.168.1.6:2586").rstrip("/")
TOPIC = os.environ.get("HL_NTFY_TOPIC", "homelab")
STATE_PATH = os.path.join(os.environ.get("HL_DATA_DIR") or "/tmp", "notify-dedup.json")

PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}


def _load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def notify(title, message, priority="default", tags=None, topic=None, click=None,
           dedup_key=None, dedup_hours=6):
    """Send one notification. Returns True if ntfy accepted it (or it was deduplicated
    away), False on any failure. With dedup_key, the same key is sent at most once per
    dedup_hours — a collector failing every 30 min pages once, not 12 times."""
    try:
        now = time.time()
        if dedup_key:
            state = _load_state()
            last = state.get(dedup_key, 0)
            if now - last < dedup_hours * 3600:
                return True
        body = {
            "topic": topic or TOPIC,
            "title": str(title)[:250],
            "message": str(message)[:4000] or "(no detail)",
            "priority": PRIORITIES.get(str(priority), 3),
        }
        if tags:
            body["tags"] = list(tags)
        if click:
            body["click"] = click
        req = urllib.request.Request(
            NTFY_URL, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.status < 300
        if ok and dedup_key:
            state = _load_state()
            # prune entries older than a week so the file can't grow forever
            state = {k: v for k, v in state.items() if now - v < 7 * 86400}
            state[dedup_key] = now
            _save_state(state)
        return ok
    except Exception as exc:  # noqa: BLE001 — never propagate
        print(f"[notify] failed: {exc}", file=sys.stderr)
        return False


def clear(dedup_key):
    """Forget a dedup key — call when the condition recovers, so the next failure pages."""
    state = _load_state()
    if state.pop(dedup_key, None) is not None:
        _save_state(state)


def _unit_failed(unit):
    tail = ""
    try:
        out = subprocess.run(
            ["journalctl", "-u", unit, "-n", "12", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=15,
        )
        tail = out.stdout.strip()[-1500:]
    except (OSError, subprocess.SubprocessError):
        pass
    name = unit.replace(".service", "")
    return notify(
        f"opti: {name} failed",
        tail or f"systemctl status {unit} on opti for details.",
        priority="high", tags=["rotating_light"], dedup_key=f"unit:{unit}",
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit-failed", metavar="UNIT")
    ap.add_argument("--title", default="homelab")
    ap.add_argument("--priority", default="default", choices=sorted(PRIORITIES))
    ap.add_argument("--tags", default="")
    ap.add_argument("--topic")
    ap.add_argument("--dedup")
    ap.add_argument("message", nargs="*")
    a = ap.parse_args()
    if a.unit_failed:
        ok = _unit_failed(a.unit_failed)
    else:
        ok = notify(a.title, " ".join(a.message), priority=a.priority,
                    tags=[t for t in a.tags.split(",") if t], topic=a.topic,
                    dedup_key=a.dedup)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
