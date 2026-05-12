#!/usr/bin/env python3
"""
arp-watch.py — Passive ARP table monitor with spoof detection.

Modes:
  python arp-watch.py --watch          continuous polling (default interval: 60s)
  python arp-watch.py --report         write latest snapshot to reports dir and exit
  python arp-watch.py --history <ip>   show IP->MAC timeline for a specific IP
  python arp-watch.py --show           print current ARP table from DB
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
REPORTS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
DB_PATH = os.path.join(DATA_DIR, "arp-watch.db")
REPORT_PATH = os.path.join(REPORTS_DIR, "arp-watch-latest.json")

PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
                    "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", "192.168.")


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arp_entries (
            ip TEXT NOT NULL,
            mac TEXT NOT NULL,
            hostname TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (ip, mac)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spoof_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            old_mac TEXT NOT NULL,
            new_mac TEXT NOT NULL,
            detected_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def parse_arp_table():
    """Returns list of {ip, mac, hostname} from system ARP table."""
    entries = []
    try:
        out = subprocess.check_output(["arp", "-a"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return entries

    for line in out.splitlines():
        # Windows: "  192.168.1.1          aa-bb-cc-dd-ee-ff     dynamic"
        # Linux:   "hostname (192.168.1.1) at aa:bb:cc:dd:ee:ff [ether] on eth0"
        mac_match = re.search(r"([0-9a-f]{2}[:\-][0-9a-f]{2}[:\-][0-9a-f]{2}[:\-][0-9a-f]{2}[:\-][0-9a-f]{2}[:\-][0-9a-f]{2})", line, re.IGNORECASE)
        ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", line)
        if not mac_match or not ip_match:
            continue
        ip = ip_match.group(1)
        mac = mac_match.group(1).lower().replace("-", ":")
        # Skip broadcast/incomplete
        if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
            continue
        hostname_match = re.match(r"^(\S+)\s+\(", line)
        hostname = hostname_match.group(1) if hostname_match else None
        entries.append({"ip": ip, "mac": mac, "hostname": hostname})
    return entries


def update_db(conn, entries):
    """Update DB with current ARP entries. Return list of spoof alerts."""
    now = datetime.now(timezone.utc).isoformat()
    alerts = []

    for entry in entries:
        ip, mac, hostname = entry["ip"], entry["mac"], entry["hostname"]
        cur = conn.execute("SELECT mac FROM arp_entries WHERE ip = ? ORDER BY last_seen DESC LIMIT 1", (ip,))
        row = cur.fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO arp_entries (ip, mac, hostname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                (ip, mac, hostname, now, now)
            )
        elif row[0] != mac:
            # MAC changed — potential ARP spoof
            conn.execute(
                "INSERT OR IGNORE INTO arp_entries (ip, mac, hostname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                (ip, mac, hostname, now, now)
            )
            conn.execute(
                "INSERT INTO spoof_alerts (ip, old_mac, new_mac, detected_at) VALUES (?, ?, ?, ?)",
                (ip, row[0], mac, now)
            )
            alerts.append({"ip": ip, "old_mac": row[0], "new_mac": mac, "detected_at": now})
            print(f"[ALERT] ARP spoof detected: {ip} changed from {row[0]} to {mac}", flush=True)
        else:
            conn.execute("UPDATE arp_entries SET last_seen = ? WHERE ip = ? AND mac = ?", (now, ip, mac))

    conn.commit()
    return alerts


def write_report(conn, alerts):
    """Write latest JSON report to the shared reports directory."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    cur = conn.execute("SELECT ip, mac, hostname, first_seen, last_seen FROM arp_entries ORDER BY ip")
    table = [{"ip": r[0], "mac": r[1], "hostname": r[2], "first_seen": r[3], "last_seen": r[4]} for r in cur]

    recent_alerts = []
    cur = conn.execute("SELECT ip, old_mac, new_mac, detected_at FROM spoof_alerts ORDER BY detected_at DESC LIMIT 20")
    recent_alerts = [{"ip": r[0], "old_mac": r[1], "new_mac": r[2], "detected_at": r[3]} for r in cur]

    status = "critical" if alerts else ("warn" if recent_alerts else "ok")
    summary = (
        f"{len(alerts)} active spoof alert(s)" if alerts
        else f"{len(table)} hosts tracked, no spoofing detected"
    )

    report = {
        "tool": "arp-watch",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": [
            {"severity": "critical", "message": f"ARP spoof: {a['ip']} {a['old_mac']} → {a['new_mac']}", "detail": a}
            for a in alerts
        ],
        "arp_table": table,
        "recent_alerts": recent_alerts,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH}")


def show_history(conn, ip):
    cur = conn.execute(
        "SELECT mac, hostname, first_seen, last_seen FROM arp_entries WHERE ip = ? ORDER BY first_seen",
        (ip,)
    )
    rows = cur.fetchall()
    if not rows:
        print(f"No history for {ip}")
        return
    print(f"\nARP history for {ip}:")
    print(f"{'MAC':<20} {'Hostname':<20} {'First Seen':<30} {'Last Seen'}")
    print("-" * 90)
    for r in rows:
        print(f"{r[0]:<20} {(r[1] or '-'):<20} {r[2]:<30} {r[3]}")


def show_table(conn):
    cur = conn.execute("SELECT ip, mac, hostname, last_seen FROM arp_entries ORDER BY ip")
    rows = cur.fetchall()
    print(f"\n{'IP':<18} {'MAC':<20} {'Hostname':<20} {'Last Seen'}")
    print("-" * 80)
    for r in rows:
        print(f"{r[0]:<18} {r[1]:<20} {(r[2] or '-'):<20} {r[3]}")


def main():
    parser = argparse.ArgumentParser(description="ARP table monitor with spoof detection")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--watch", action="store_true", help="Continuous watch mode")
    group.add_argument("--report", action="store_true", help="Run once, write report, exit")
    group.add_argument("--history", metavar="IP", help="Show MAC history for an IP")
    group.add_argument("--show", action="store_true", help="Print current ARP table from DB")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (watch mode)")
    args = parser.parse_args()

    ensure_dirs()
    conn = get_db()

    if args.history:
        show_history(conn, args.history)
        return

    if args.show:
        show_table(conn)
        return

    if args.report:
        entries = parse_arp_table()
        alerts = update_db(conn, entries)
        write_report(conn, alerts)
        return

    # Default: --watch
    print(f"ARP watcher started (interval: {args.interval}s). Ctrl-C to stop.")
    try:
        while True:
            entries = parse_arp_table()
            alerts = update_db(conn, entries)
            if alerts:
                write_report(conn, alerts)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(entries)} ARP entries checked", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        write_report(conn, [])
        print("\nStopped. Final report written.")


if __name__ == "__main__":
    main()
