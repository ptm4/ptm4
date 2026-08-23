#!/usr/bin/env python3
"""
vitals_logger.py — durable per-minute host vitals into homelab.db.

The webapp already polls each host's `hl-arch-agent` for vitals, but it keeps them in
memory: a 6h ring at 30s plus 48h of 5-minute buckets, snapshotted to a file on the rpi's
SD card. That is the right trade for a live dashboard on fragile storage, and the wrong
one for "was the CPU pegged last Tuesday" — after 48 hours the answer is simply gone.

This runs on opti, writes to the pool, and keeps 30 days at 60-second resolution plus
hourly rollups forever. The two are complementary, not redundant: the webapp's rings stay
canonical for the live board, so the dashboard keeps working when opti is down.

Counter semantics are copied deliberately from the webapp's poller
(backend/plugins/vitals-poller.js), because disagreeing about them would be worse than
either choice: the agent exposes RAW CUMULATIVE counters and stays stateless, so a
counter that moved backwards (agent restart, reboot, wrap) records **null** — a real gap
— rather than an enormous fake spike.

Env: HL_DB_PATH, HL_VITALS_HOSTS (name=url,…), HL_VITALS_INTERVAL (default 60),
     HL_ARCH_INGEST_TOKEN (sent if set; /vitals is an unauthenticated GET today).
"""

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

# Same three the webapp polls: android has no agent (Termux, and intermittent by design).
DEFAULT_HOSTS = {
    "opti": "http://192.168.1.11:8787",
    "rpi": "http://192.168.1.10:8787",
    "noblenumbat": "http://192.168.1.6:8787",
}

INTERVAL = int(os.environ.get("HL_VITALS_INTERVAL", "60"))
TOKEN = os.environ.get("HL_ARCH_INGEST_TOKEN", "")
RAW_KEEP_DAYS = 30

METRICS = ("cpu_pct", "mem_pct", "load1", "temp_c", "rx_bps", "tx_bps")

_running = True


def hosts():
    raw = os.environ.get("HL_VITALS_HOSTS", "")
    if not raw:
        return dict(DEFAULT_HOSTS)
    out = {}
    for part in raw.split(","):
        if "=" in part:
            name, url = part.split("=", 1)
            out[name.strip()] = url.strip()
    return out or dict(DEFAULT_HOSTS)


def fetch_vitals(url, timeout=8):
    request = urllib.request.Request(f"{url}/vitals")
    if TOKEN:
        request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.load(resp)


def derive(prev, cur):
    """Two raw readings -> one sample. Backwards counter => null, never a spike."""
    sample = {
        "at": int(cur.get("t") or time.time()),
        "load1": (cur.get("loadavg") or [None])[0],
        "cpu_pct": None,
        "mem_pct": None,
        "temp_c": cur.get("temp_c"),
        "rx_bps": None,
        "tx_bps": None,
        "uptime_s": int(cur["uptime_s"]) if cur.get("uptime_s") is not None else None,
    }
    if prev is None:
        return sample

    dt = (cur.get("t") or 0) - (prev.get("t") or 0)
    if dt <= 0:
        return sample

    prev_cpu, cur_cpu = prev.get("cpu"), cur.get("cpu")
    if prev_cpu and cur_cpu:
        d_total = cur_cpu.get("total", 0) - prev_cpu.get("total", 0)
        d_idle = cur_cpu.get("idle", 0) - prev_cpu.get("idle", 0)
        if d_total > 0 and d_idle >= 0:
            sample["cpu_pct"] = round(max(0.0, min(100.0, (1 - d_idle / d_total) * 100)), 1)

    mem = cur.get("mem") or {}
    total, used = mem.get("total_bytes"), mem.get("used_bytes")
    if total:
        sample["mem_pct"] = round(used / total * 100, 1)

    # Sum every interface: which NIC carried the traffic is not what this answers.
    prev_net, cur_net = prev.get("net") or {}, cur.get("net") or {}
    rx = tx = 0
    ok = False
    for iface, counters in cur_net.items():
        before = prev_net.get(iface)
        if not before:
            continue
        d_rx = counters.get("rx_bytes", 0) - before.get("rx_bytes", 0)
        d_tx = counters.get("tx_bytes", 0) - before.get("tx_bytes", 0)
        if d_rx < 0 or d_tx < 0:
            return sample  # a reset anywhere: report the gap rather than guess
        rx += d_rx
        tx += d_tx
        ok = True
    if ok:
        sample["rx_bps"] = round(rx / dt, 1)
        sample["tx_bps"] = round(tx / dt, 1)
    return sample


def write_samples(conn, rows):
    if not rows:
        return
    with db.writing(conn):
        for host, sample in rows:
            conn.execute(
                """INSERT INTO vitals_samples
                       (host, at, cpu_pct, mem_pct, load1, temp_c, rx_bps, tx_bps, uptime_s)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (host, at) DO UPDATE SET
                     cpu_pct = excluded.cpu_pct, mem_pct = excluded.mem_pct,
                     load1 = excluded.load1, temp_c = excluded.temp_c,
                     rx_bps = excluded.rx_bps, tx_bps = excluded.tx_bps,
                     uptime_s = excluded.uptime_s""",
                (host, sample["at"], sample["cpu_pct"], sample["mem_pct"], sample["load1"],
                 sample["temp_c"], sample["rx_bps"], sample["tx_bps"], sample["uptime_s"]),
            )


def rollup(conn, hour_start):
    """Aggregate one finished hour into vitals_hourly, then forget nothing yet.

    Rollups are what make the series affordable forever; the raw rows are pruned on a
    much longer horizon so short-window questions stay exact.
    """
    hour_end = hour_start + 3600
    with db.writing(conn):
        for metric in METRICS:
            conn.execute(
                f"""INSERT INTO vitals_hourly (host, hour, metric, min_v, max_v, avg_v, samples)
                    SELECT host, ?, ?, MIN({metric}), MAX({metric}),
                           ROUND(AVG({metric}), 2), COUNT({metric})
                    FROM vitals_samples
                    WHERE at >= ? AND at < ? AND {metric} IS NOT NULL
                    GROUP BY host
                    ON CONFLICT (host, hour, metric) DO UPDATE SET
                      min_v = excluded.min_v, max_v = excluded.max_v,
                      avg_v = excluded.avg_v, samples = excluded.samples""",
                (hour_start, metric, hour_start, hour_end),
            )


def prune(conn):
    cutoff = int(time.time()) - RAW_KEEP_DAYS * 86400
    with db.writing(conn):
        cursor = conn.execute("DELETE FROM vitals_samples WHERE at < ?", (cutoff,))
        return cursor.rowcount


def _stop(_signum, _frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    targets = hosts()
    conn = db.connect_rw(create=False)
    db.migrate(conn)
    print(f"[vitals] polling {', '.join(targets)} every {INTERVAL}s -> {db.db_path()}",
          flush=True)

    previous = {}
    last_hour = int(time.time()) // 3600
    last_prune = 0.0

    while _running:
        started = time.time()
        rows = []
        for host, url in targets.items():
            try:
                current = fetch_vitals(url)
            except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
                # A host being unreachable is normal (reboots, agent restarts). Drop its
                # baseline so the next reading is treated as a fresh start, not a diff
                # across the gap — that is exactly where a fake spike would come from.
                previous.pop(host, None)
                continue
            sample = derive(previous.get(host), current)
            previous[host] = current
            rows.append((host, sample))

        try:
            write_samples(conn, rows)
        except Exception as exc:  # noqa: BLE001 — a write failure must not kill the loop
            print(f"[vitals] write failed: {exc}", flush=True)

        now_hour = int(time.time()) // 3600
        if now_hour != last_hour:
            try:
                rollup(conn, last_hour * 3600)
                print(f"[vitals] rolled up hour {datetime.fromtimestamp(last_hour * 3600, timezone.utc):%Y-%m-%d %H:00}",
                      flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[vitals] rollup failed: {exc}", flush=True)
            last_hour = now_hour

        if time.time() - last_prune > 6 * 3600:
            try:
                removed = prune(conn)
                if removed:
                    print(f"[vitals] pruned {removed} raw samples older than {RAW_KEEP_DAYS}d",
                          flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[vitals] prune failed: {exc}", flush=True)
            last_prune = time.time()

        # Sleep in short slices so SIGTERM stops the service promptly instead of after
        # a full interval.
        elapsed = time.time() - started
        remaining = max(0.0, INTERVAL - elapsed)
        while remaining > 0 and _running:
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

    conn.close()
    print("[vitals] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
