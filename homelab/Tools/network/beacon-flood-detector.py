#!/usr/bin/env python3
"""
beacon-flood-detector.py — Detect Wi-Fi Pineapple-style beacon floods.

A Wi-Fi Pineapple (or similar deception device) broadcasts Beacon frames for many
different SSIDs simultaneously from a single radio. This tool detects that pattern:
one MAC broadcasting 10+ distinct SSIDs within a short window.

Run on Raspberry Pi or Linux with a monitor-mode Wi-Fi adapter.

Usage:
  sudo python3 beacon-flood-detector.py --iface wlan1mon
  sudo python3 beacon-flood-detector.py --iface wlan1mon --threshold 5 --window 10

Requires: pip3 install scapy
"""

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

try:
    from scapy.all import sniff, Dot11, Dot11Beacon, Dot11Elt
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Wi-Fi Pineapple / beacon flood detector")
    parser.add_argument("--iface", required=True, help="Monitor mode interface")
    parser.add_argument("--threshold", type=int, default=8,
                        help="Distinct SSIDs from one MAC to trigger alert (default: 8)")
    parser.add_argument("--window", type=int, default=30,
                        help="Time window in seconds (default: 30)")
    args = parser.parse_args()

    # bssid -> {ssid: last_seen_timestamp}
    bssid_ssids = defaultdict(dict)
    alerted = set()

    def handle(pkt):
        if not pkt.haslayer(Dot11Beacon) or not pkt.haslayer(Dot11):
            return

        bssid = pkt[Dot11].addr3 or pkt[Dot11].addr2
        if not bssid:
            return

        # Extract SSID
        ssid = ""
        if pkt.haslayer(Dot11Elt):
            elt = pkt[Dot11Elt]
            while elt:
                if elt.ID == 0:
                    try:
                        ssid = elt.info.decode("utf-8", errors="replace").strip()
                    except Exception:
                        ssid = "<binary>"
                    break
                if hasattr(elt, "payload"):
                    elt = elt.payload
                else:
                    break

        if not ssid:
            return

        now = time.time()
        bssid_ssids[bssid][ssid] = now

        # Prune old entries outside the window
        bssid_ssids[bssid] = {s: t for s, t in bssid_ssids[bssid].items() if t > now - args.window}

        ssid_count = len(bssid_ssids[bssid])

        if ssid_count >= args.threshold:
            if bssid not in alerted:
                alerted.add(bssid)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] *** BEACON FLOOD / PINEAPPLE DETECTED ***")
                print(f"  BSSID: {bssid}")
                print(f"  Broadcasting {ssid_count} distinct SSIDs in {args.window}s window:")
                for s in sorted(bssid_ssids[bssid].keys())[:20]:
                    print(f"    - {s!r}")
                if ssid_count > 20:
                    print(f"    ... and {ssid_count - 20} more")
                print()
        else:
            # Reset alert once count drops (BSSID may have stopped flooding)
            if bssid in alerted and ssid_count < args.threshold // 2:
                alerted.discard(bssid)

    print(f"Monitoring beacons on {args.iface} — alert at {args.threshold} SSIDs/{args.window}s per BSSID")
    print("Press Ctrl-C to stop.\n")

    try:
        sniff(iface=args.iface, prn=handle, store=False,
              lfilter=lambda p: p.haslayer(Dot11Beacon))
    except KeyboardInterrupt:
        print("\nStopped.")
        # Summary
        if bssid_ssids:
            print("\nTop broadcasters seen:")
            for bssid in sorted(bssid_ssids, key=lambda b: len(bssid_ssids[b]), reverse=True)[:5]:
                print(f"  {bssid}: {len(bssid_ssids[bssid])} SSIDs")
    except OSError as e:
        print(f"ERROR: {e}\nIs {args.iface} in monitor mode?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
