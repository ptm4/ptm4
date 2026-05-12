#!/usr/bin/env python3
"""
probe-harvester.py — Capture Wi-Fi probe requests to map device SSID history.

Devices broadcast Probe Requests for networks they've previously connected to.
This sniffs those frames and builds a log: device MAC → SSIDs it's looking for.

Useful for understanding what networks your own devices are advertising,
and what nearby devices reveal about their connection history.

Run on Raspberry Pi or Linux with a monitor-mode Wi-Fi adapter.

Usage:
  sudo python3 probe-harvester.py --iface wlan1mon
  sudo python3 probe-harvester.py --iface wlan1mon --filter aa:bb:cc:dd:ee:ff

Requires: pip3 install scapy
"""

import argparse
import json
import os
import signal
import sys
from collections import defaultdict
from datetime import datetime, timezone

try:
    from scapy.all import sniff, Dot11ProbeReq, Dot11Elt, Dot11, RadioTap
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)

# device_mac -> {ssid -> {first_seen, last_seen, count}}
devices = defaultdict(lambda: defaultdict(lambda: {"first_seen": None, "last_seen": None, "count": 0}))
seen_count = 0


def handle(pkt):
    global seen_count
    if not pkt.haslayer(Dot11ProbeReq):
        return

    mac = pkt[Dot11].addr2
    if not mac:
        return

    # Extract SSID from Dot11Elt
    ssid = ""
    if pkt.haslayer(Dot11Elt):
        elt = pkt[Dot11Elt]
        while elt:
            if elt.ID == 0:  # SSID element
                try:
                    ssid = elt.info.decode("utf-8", errors="replace").strip()
                except Exception:
                    ssid = ""
                break
            elt = elt.payload if hasattr(elt, "payload") else None

    # Wildcard probes (empty SSID) — device is looking for any known network
    if not ssid:
        ssid = "<wildcard>"

    now = datetime.now(timezone.utc).isoformat()
    entry = devices[mac][ssid]
    if entry["first_seen"] is None:
        entry["first_seen"] = now
        seen_count += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] NEW: {mac} probing for '{ssid}'")
    entry["last_seen"] = now
    entry["count"] += 1


def dump_results():
    print(f"\n{'='*60}")
    print(f"PROBE HARVEST RESULTS ({len(devices)} devices)")
    print(f"{'='*60}")
    for mac in sorted(devices.keys()):
        ssids = devices[mac]
        real_ssids = [s for s in ssids if s != "<wildcard>"]
        print(f"\n  [{mac}] — {len(ssids)} network(s) probed:")
        for ssid, info in sorted(ssids.items(), key=lambda x: x[1]["count"], reverse=True):
            tag = " [wildcard]" if ssid == "<wildcard>" else ""
            print(f"    {ssid!r}{tag} ({info['count']} probes, last: {info['last_seen'][:19]})")


def save_log(path):
    data = {}
    for mac, ssids in devices.items():
        data[mac] = {}
        for ssid, info in ssids.items():
            data[mac][ssid] = info
    with open(path, "w") as f:
        json.dump({
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "device_count": len(devices),
            "probe_count": seen_count,
            "devices": data,
        }, f, indent=2)
    print(f"Log saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Wi-Fi probe request harvester")
    parser.add_argument("--iface", required=True, help="Monitor mode interface")
    parser.add_argument("--filter", metavar="MAC", help="Only show probes from this MAC")
    parser.add_argument("--out", default="probe-harvest.json", help="Output JSON file")
    args = parser.parse_args()

    orig_filter = args.filter.lower() if args.filter else None

    def filtered_handle(pkt):
        if orig_filter and pkt.haslayer(Dot11) and pkt[Dot11].addr2 != orig_filter:
            return
        handle(pkt)

    def on_exit(sig, frame):
        dump_results()
        save_log(args.out)
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    print(f"Harvesting probe requests on {args.iface}. Ctrl-C to stop and save.\n")
    try:
        sniff(iface=args.iface, prn=filtered_handle, store=False,
              lfilter=lambda p: p.haslayer(Dot11ProbeReq))
    except OSError as e:
        print(f"ERROR: {e}\nIs {args.iface} in monitor mode?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
