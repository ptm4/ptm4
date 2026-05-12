#!/usr/bin/env python3
"""
rogue-ap-hunter.py — Detect rogue / evil-twin access points on your wireless network.

Scans visible WiFi networks and compares them against a known-good whitelist.
Alerts if your home SSID is being broadcast by an unrecognized BSSID (MAC address).

Usage:
  python rogue-ap-hunter.py               # single scan, print results
  python rogue-ap-hunter.py --watch       # continuous scan every 60s
  python rogue-ap-hunter.py --add-trusted # interactive: add current APs to whitelist

Requires: Windows (netsh) or Linux (iwlist/nmcli). No external Python deps.
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "..", "config")
REPORTS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
CONFIG_PATH = os.path.join(CONFIG_DIR, "known-aps.json")
REPORT_PATH = os.path.join(REPORTS_DIR, "rogue-ap-latest.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def load_whitelist():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_whitelist(wl):
    with open(CONFIG_PATH, "w") as f:
        json.dump(wl, f, indent=2)
    print(f"Whitelist saved to {CONFIG_PATH}")


def scan_windows():
    """Returns list of {ssid, bssid, signal, channel, auth} using netsh on Windows."""
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            text=True, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace"
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: netsh failed. Are you on Windows with a WiFi adapter?", file=sys.stderr)
        return []

    networks = []
    current = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("SSID") and "BSSID" not in line:
            if current.get("bssid"):
                networks.append(current)
            current = {"ssid": line.split(":", 1)[1].strip() if ":" in line else ""}
        elif line.startswith("BSSID"):
            current["bssid"] = line.split(":", 1)[1].strip().lower() if ":" in line else ""
        elif line.startswith("Signal"):
            current["signal"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("Channel"):
            current["channel"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("Authentication"):
            current["auth"] = line.split(":", 1)[1].strip() if ":" in line else ""

    if current.get("bssid"):
        networks.append(current)
    return networks


def scan_linux():
    """Returns list of {ssid, bssid, signal, channel, auth} using nmcli on Linux."""
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,CHAN,SECURITY", "dev", "wifi", "list"],
            text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    else:
        networks = []
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 5:
                networks.append({
                    "ssid": parts[0],
                    "bssid": parts[1].lower(),
                    "signal": parts[2],
                    "channel": parts[3],
                    "auth": parts[4],
                })
        return networks

    # Fallback: iwlist
    try:
        iface = subprocess.check_output(["iwconfig"], text=True, stderr=subprocess.STDOUT)
        iface_match = re.search(r"^(\w+)\s+IEEE", iface, re.MULTILINE)
        iface_name = iface_match.group(1) if iface_match else "wlan0"
        out = subprocess.check_output(["iwlist", iface_name, "scan"], text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: nmcli and iwlist both failed.", file=sys.stderr)
        return []

    networks = []
    current = {}
    for line in out.splitlines():
        line = line.strip()
        if "Cell" in line and "Address:" in line:
            if current.get("bssid"):
                networks.append(current)
            current = {"bssid": line.split("Address:")[-1].strip().lower()}
        elif line.startswith("ESSID:"):
            current["ssid"] = line.split('"')[1] if '"' in line else ""
        elif "Signal level" in line:
            m = re.search(r"Signal level[=:](-?\d+)", line)
            current["signal"] = m.group(1) if m else ""
        elif line.startswith("Channel:"):
            current["channel"] = line.split(":")[1].strip()
    if current.get("bssid"):
        networks.append(current)
    return networks


def scan():
    if platform.system() == "Windows":
        return scan_windows()
    return scan_linux()


def check_for_rogues(networks, whitelist):
    """
    Returns list of rogue AP dicts.
    A rogue is: an SSID in the whitelist whose broadcast BSSID is NOT in the trusted list.
    Also flags: open networks named like known SSIDs.
    """
    rogues = []
    for ap in networks:
        ssid = ap.get("ssid", "")
        bssid = ap.get("bssid", "")
        if ssid in whitelist:
            trusted_bssids = [b.lower() for b in whitelist[ssid]]
            if bssid not in trusted_bssids:
                rogues.append({
                    "ssid": ssid,
                    "rogue_bssid": bssid,
                    "trusted_bssids": trusted_bssids,
                    "signal": ap.get("signal", ""),
                    "auth": ap.get("auth", ""),
                    "channel": ap.get("channel", ""),
                })
    return rogues


def write_report(networks, rogues):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    status = "critical" if rogues else "ok"
    summary = (
        f"{len(rogues)} rogue AP(s) detected!" if rogues
        else f"{len(networks)} APs scanned, no rogues found"
    )
    report = {
        "tool": "rogue-ap-hunter",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": [
            {
                "severity": "critical",
                "message": f"Evil twin: '{r['ssid']}' broadcast by unknown BSSID {r['rogue_bssid']}",
                "detail": r,
            }
            for r in rogues
        ],
        "all_aps_seen": networks,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)


def print_scan_results(networks, rogues, whitelist):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Visible APs: {len(networks)}")
    if not networks:
        print("  No networks found.")
        return

    print(f"\n  {'SSID':<32} {'BSSID':<20} {'Signal':<8} {'Ch':<5} {'Auth':<20} Status")
    print("  " + "-" * 95)
    for ap in sorted(networks, key=lambda x: x.get("ssid", "")):
        ssid = ap.get("ssid", "")
        bssid = ap.get("bssid", "")
        is_rogue = any(r["rogue_bssid"] == bssid and r["ssid"] == ssid for r in rogues)
        is_trusted = ssid in whitelist and bssid in [b.lower() for b in whitelist[ssid]]
        status = "[ROGUE!]" if is_rogue else ("[trusted]" if is_trusted else "")
        print(f"  {ssid:<32} {bssid:<20} {ap.get('signal',''):<8} {ap.get('channel',''):<5} {ap.get('auth',''):<20} {status}")

    if rogues:
        print(f"\n  *** {len(rogues)} ROGUE AP(S) DETECTED ***")
        for r in rogues:
            print(f"  SSID '{r['ssid']}' broadcast by UNTRUSTED BSSID: {r['rogue_bssid']}")


def interactive_add(networks, whitelist):
    print("\nCurrently visible networks:")
    for i, ap in enumerate(networks):
        print(f"  [{i}] SSID: {ap.get('ssid',''):<30} BSSID: {ap.get('bssid','')}")
    print("\nEnter indices to trust (comma-separated), or 'all', or 'q' to quit:")
    choice = input("> ").strip()
    if choice.lower() == "q":
        return
    indices = range(len(networks)) if choice.lower() == "all" else [int(x.strip()) for x in choice.split(",")]
    for i in indices:
        ap = networks[i]
        ssid, bssid = ap.get("ssid", ""), ap.get("bssid", "")
        if ssid not in whitelist:
            whitelist[ssid] = []
        if bssid not in whitelist[ssid]:
            whitelist[ssid].append(bssid)
            print(f"  Trusted: {ssid} @ {bssid}")
    save_whitelist(whitelist)


def main():
    parser = argparse.ArgumentParser(description="Rogue / evil-twin AP detector")
    parser.add_argument("--watch", action="store_true", help="Continuous scan mode")
    parser.add_argument("--add-trusted", action="store_true", help="Interactively add current APs to whitelist")
    parser.add_argument("--interval", type=int, default=60, help="Scan interval in seconds (watch mode)")
    args = parser.parse_args()

    whitelist = load_whitelist()
    if not whitelist:
        print(f"No whitelist found at {CONFIG_PATH}.")
        print("Run with --add-trusted first to build your whitelist, then scanning will detect rogues.")

    if args.add_trusted:
        networks = scan()
        interactive_add(networks, whitelist)
        return

    if args.watch:
        print(f"Rogue AP hunter watching (interval: {args.interval}s). Ctrl-C to stop.")
        try:
            while True:
                networks = scan()
                rogues = check_for_rogues(networks, whitelist)
                print_scan_results(networks, rogues, whitelist)
                write_report(networks, rogues)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    # Single scan
    networks = scan()
    rogues = check_for_rogues(networks, whitelist)
    print_scan_results(networks, rogues, whitelist)
    write_report(networks, rogues)
    if rogues:
        sys.exit(1)


if __name__ == "__main__":
    main()
