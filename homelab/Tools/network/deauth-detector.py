#!/usr/bin/env python3
"""
deauth-detector.py — Detect 802.11 deauthentication attacks.

Sniffs 802.11 management frames in monitor mode and alerts when deauth frames
are sent at flood rates (>5 per second to the same target), which is the classic
indicator of a WiFi deauth/disassociation attack or evil-twin setup attempt.

Run on the Raspberry Pi or any Linux host with a monitor-mode capable Wi-Fi adapter.

Usage:
  sudo python3 deauth-detector.py --iface wlan1
  sudo python3 deauth-detector.py --iface wlan1 --threshold 3 --window 5

Requires: pip3 install scapy
          Wi-Fi adapter in monitor mode: sudo airmon-ng start wlan1
"""

import argparse
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime

try:
    from scapy.all import sniff, Dot11, Dot11Deauth, Dot11Disas, RadioTap
    from scapy.layers.dot11 import Dot11
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)

# Deauth reason codes
REASON_CODES = {
    1: "Unspecified",
    2: "Prev auth no longer valid",
    3: "Deauthenticated — station leaving",
    4: "Inactivity",
    5: "AP capacity",
    6: "Class 2 frame from non-authed station",
    7: "Class 3 frame from non-assoc station",
    8: "Disassociated — station leaving BSS",
    9: "Station not authenticated",
}


def main():
    parser = argparse.ArgumentParser(description="802.11 deauth attack detector")
    parser.add_argument("--iface", required=True, help="Monitor mode interface (e.g. wlan1mon)")
    parser.add_argument("--threshold", type=int, default=5,
                        help="Deauth frames per window to trigger alert (default: 5)")
    parser.add_argument("--window", type=int, default=3,
                        help="Time window in seconds for threshold (default: 3)")
    args = parser.parse_args()

    # Sliding window: target_mac → deque of timestamps
    seen = defaultdict(deque)
    alerted = set()

    print(f"Listening on {args.iface} — threshold: {args.threshold} deauths/{args.window}s")
    print("Press Ctrl-C to stop.\n")

    def handle(pkt):
        if not pkt.haslayer(Dot11Deauth) and not pkt.haslayer(Dot11Disas):
            return

        now = time.time()
        src = pkt[Dot11].addr2 or "ff:ff:ff:ff:ff:ff"
        dst = pkt[Dot11].addr1 or "ff:ff:ff:ff:ff:ff"
        is_deauth = pkt.haslayer(Dot11Deauth)
        frame_type = "DEAUTH" if is_deauth else "DISASSOC"

        layer = pkt[Dot11Deauth] if is_deauth else pkt[Dot11Disas]
        reason_code = getattr(layer, "reason", 0)
        reason = REASON_CODES.get(reason_code, f"Code {reason_code}")

        key = (src, dst)
        seen[key].append(now)
        # Trim entries outside the window
        while seen[key] and seen[key][0] < now - args.window:
            seen[key].popleft()

        count = len(seen[key])

        if count >= args.threshold:
            if key not in alerted:
                alerted.add(key)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] *** {frame_type} FLOOD DETECTED ***")
                print(f"         Source (attacker/AP): {src}")
                print(f"         Target:               {dst}")
                print(f"         {count} frames in {args.window}s | Reason: {reason}")
                if dst == "ff:ff:ff:ff:ff:ff":
                    print(f"         BROADCAST deauth — all clients being kicked!")
                print()
        else:
            if key in alerted and count < 2:
                alerted.discard(key)
            if count == 1:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] {frame_type} src={src} dst={dst} reason={reason}")

    try:
        sniff(iface=args.iface, prn=handle, store=False,
              lfilter=lambda p: p.haslayer(Dot11Deauth) or p.haslayer(Dot11Disas))
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as e:
        print(f"ERROR: {e}\nIs {args.iface} in monitor mode?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
