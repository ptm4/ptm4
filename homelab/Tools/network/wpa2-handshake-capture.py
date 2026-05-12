#!/usr/bin/env python3
"""
wpa2-handshake-capture.py — Capture WPA2 4-way EAPOL handshakes from your own AP.

Sniffs for WPA2 authentication handshake frames and saves them to a .cap file
compatible with hashcat (-m 22000) and aircrack-ng.

Use case: Test your own Wi-Fi password strength by capturing the handshake when
a device connects to your AP, then running hashcat against the capture.

Run on Raspberry Pi or Linux with a monitor-mode adapter tuned to your AP's channel.

Usage:
  sudo python3 wpa2-handshake-capture.py --iface wlan1mon --bssid aa:bb:cc:dd:ee:ff
  sudo python3 wpa2-handshake-capture.py --iface wlan1mon --bssid aa:bb:cc:dd:ee:ff --out capture.cap

To use with hashcat after capturing:
  hashcat -m 22000 capture.cap wordlist.txt

Requires: pip3 install scapy
"""

import argparse
import os
import sys
import time
from datetime import datetime

try:
    from scapy.all import sniff, EAPOL, Dot11, Dot11Beacon, wrpcap, RadioTap
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="WPA2 4-way handshake capture")
    parser.add_argument("--iface", required=True, help="Monitor mode interface")
    parser.add_argument("--bssid", help="Target AP BSSID (optional — captures all if omitted)")
    parser.add_argument("--out", default="handshake.cap", help="Output capture file (.cap)")
    parser.add_argument("--timeout", type=int, default=0,
                        help="Stop after N seconds (0 = run until Ctrl-C)")
    args = parser.parse_args()

    target_bssid = args.bssid.lower() if args.bssid else None
    captured_frames = []
    handshake_keys = {}  # bssid -> set of EAPOL message numbers seen

    def is_target(pkt):
        if not target_bssid:
            return True
        bssid = (pkt[Dot11].addr1 or "").lower()
        bssid2 = (pkt[Dot11].addr2 or "").lower()
        return target_bssid in (bssid, bssid2)

    def handle(pkt):
        if not pkt.haslayer(EAPOL) or not pkt.haslayer(Dot11):
            return
        if not is_target(pkt):
            return

        captured_frames.append(pkt)
        src = pkt[Dot11].addr2 or "?"
        dst = pkt[Dot11].addr1 or "?"

        # EAPOL-Key frame — WPA2 handshake frame detection
        # Message type is determined by key_info flags in the raw EAPOL payload
        raw = bytes(pkt[EAPOL])
        if len(raw) < 4:
            return

        key_info = int.from_bytes(raw[5:7], "big") if len(raw) > 6 else 0
        mic_set = bool(key_info & 0x100)
        ack_set = bool(key_info & 0x080)
        install = bool(key_info & 0x040)
        secure  = bool(key_info & 0x200)

        if not mic_set and ack_set:
            msg = 1
        elif mic_set and not ack_set and not secure:
            msg = 2
        elif mic_set and ack_set and install:
            msg = 3
        elif mic_set and not ack_set and secure:
            msg = 4
        else:
            msg = 0

        bssid_key = pkt[Dot11].addr3 or src
        if bssid_key not in handshake_keys:
            handshake_keys[bssid_key] = set()
        if msg > 0:
            handshake_keys[bssid_key].add(msg)

        ts = datetime.now().strftime("%H:%M:%S")
        msgs = sorted(handshake_keys[bssid_key])
        complete = {1, 2, 3, 4}.issubset(handshake_keys[bssid_key])
        status = " *** COMPLETE HANDSHAKE! ***" if complete else f" (have: {msgs})"
        print(f"[{ts}] EAPOL msg={msg} {src} → {dst}{status}")

        if complete:
            wrpcap(args.out, captured_frames)
            print(f"\nHandshake saved: {args.out}")
            print(f"Crack with: hashcat -m 22000 {args.out} <wordlist>")

    tgt = f" for BSSID {target_bssid}" if target_bssid else " (all BSSIDs)"
    timeout_str = f" (timeout: {args.timeout}s)" if args.timeout else ""
    print(f"Capturing WPA2 handshakes on {args.iface}{tgt}{timeout_str}")
    print("Have a device connect/reconnect to the target AP to trigger a handshake.")
    print("Ctrl-C to stop and save.\n")

    try:
        sniff(iface=args.iface, prn=handle, store=False,
              lfilter=lambda p: p.haslayer(EAPOL),
              timeout=args.timeout if args.timeout else None)
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if captured_frames:
            wrpcap(args.out, captured_frames)
            print(f"\n{len(captured_frames)} EAPOL frame(s) saved to {args.out}")
        else:
            print("\nNo EAPOL frames captured.")


if __name__ == "__main__":
    main()
