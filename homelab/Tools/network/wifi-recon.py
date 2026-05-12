#!/usr/bin/env python3
"""
wifi-recon.py — Passive channel-hopping WiFi scanner.

Hops across 2.4GHz + 5GHz channels, sniffs Beacon and Probe Response frames,
and builds a live database of visible APs and their associated clients.

Detects hidden SSIDs via Probe Responses.

Usage:
  sudo python3 wifi-recon.py --iface wlan1mon
  sudo python3 wifi-recon.py --iface wlan1mon --channels 1,6,11  # 2.4GHz only
  sudo python3 wifi-recon.py --iface wlan1mon --out scan.json --duration 60

Requires: pip3 install scapy
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

try:
    from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeResp, Dot11Elt, RadioTap
except ImportError:
    print("ERROR: scapy not installed. Run: pip3 install scapy", file=sys.stderr)
    sys.exit(1)

if os.geteuid() != 0:
    print("ERROR: Must run as root (sudo)", file=sys.stderr)
    sys.exit(1)

CHANNELS_24 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
CHANNELS_50 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 149, 153, 157, 161, 165]

# bssid -> AP info dict
aps = {}
# bssid -> set of client MACs
clients = defaultdict(set)
stop_event = threading.Event()


def extract_ssid(pkt):
    if pkt.haslayer(Dot11Elt):
        elt = pkt[Dot11Elt]
        while elt:
            if elt.ID == 0:
                try:
                    return elt.info.decode("utf-8", errors="replace").strip()
                except Exception:
                    return ""
            elt = elt.payload if hasattr(elt, "payload") else None
    return ""


def extract_channel(pkt):
    if pkt.haslayer(Dot11Elt):
        elt = pkt[Dot11Elt]
        while elt:
            if elt.ID == 3 and elt.info:  # DS Parameter Set
                return int.from_bytes(elt.info[:1], "big")
            elt = elt.payload if hasattr(elt, "payload") else None
    return None


def extract_encryption(pkt):
    tags = []
    if pkt.haslayer(Dot11Elt):
        elt = pkt[Dot11Elt]
        while elt:
            if elt.ID == 48:   # RSN (WPA2/3)
                tags.append("WPA2")
            elif elt.ID == 221 and elt.info[:4] == b"\x00\x50\xf2\x01":  # WPA1
                tags.append("WPA")
            elt = elt.payload if hasattr(elt, "payload") else None

    # Check capability field for WEP (bit 4 in beacon)
    cap = getattr(pkt[Dot11Beacon] if pkt.haslayer(Dot11Beacon) else None, "cap", 0)
    if cap and (cap & 0x10) and not tags:
        tags.append("WEP")

    return "/".join(tags) if tags else "Open"


def get_signal(pkt):
    if pkt.haslayer(RadioTap):
        try:
            return pkt[RadioTap].dBm_AntSignal
        except AttributeError:
            pass
    return None


def handle(pkt):
    if not pkt.haslayer(Dot11):
        return

    is_beacon = pkt.haslayer(Dot11Beacon)
    is_probe_resp = pkt.haslayer(Dot11ProbeResp)

    if is_beacon or is_probe_resp:
        bssid = pkt[Dot11].addr3 or pkt[Dot11].addr2
        if not bssid:
            return
        ssid = extract_ssid(pkt)
        channel = extract_channel(pkt)
        enc = extract_encryption(pkt) if is_beacon else None
        signal = get_signal(pkt)
        now = datetime.now(timezone.utc).isoformat()

        if bssid not in aps:
            aps[bssid] = {
                "bssid": bssid, "ssid": ssid, "channel": channel,
                "encryption": enc or "?", "signal": signal,
                "first_seen": now, "last_seen": now, "hidden": not bool(ssid),
            }
            tag = "[HIDDEN]" if not ssid else f"'{ssid}'"
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] AP  {bssid}  {tag:<30} ch={channel or '?':<4} {enc or '?'}", flush=True)
        else:
            ap = aps[bssid]
            ap["last_seen"] = now
            if ssid and ap["hidden"]:
                ap["ssid"] = ssid
                ap["hidden"] = False
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] HIDDEN SSID REVEALED: {bssid} → '{ssid}'", flush=True)
            if signal:
                ap["signal"] = signal
            if channel:
                ap["channel"] = channel

    # Track client associations (data frames)
    frame_type = pkt[Dot11].type
    frame_subtype = pkt[Dot11].subtype
    if frame_type == 2:  # Data frame
        ds = pkt[Dot11].FCfield & 0x3
        addr1, addr2, addr3 = pkt[Dot11].addr1, pkt[Dot11].addr2, pkt[Dot11].addr3
        if ds == 1:  # To DS: client → AP
            client, bssid = addr2, addr1
        elif ds == 2:  # From DS: AP → client
            bssid, client = addr2, addr1
        else:
            return
        if bssid and client and client not in ("ff:ff:ff:ff:ff:ff",):
            if bssid in aps:
                clients[bssid].add(client)


def hop_channels(iface, channels, interval=0.3):
    while not stop_event.is_set():
        for ch in channels:
            if stop_event.is_set():
                break
            try:
                subprocess.run(["iwconfig", iface, "channel", str(ch)],
                               capture_output=True, timeout=1)
            except Exception:
                pass
            time.sleep(interval)


def print_summary():
    print(f"\n{'='*80}")
    print(f"WiFi RECON SUMMARY — {len(aps)} APs, {sum(len(v) for v in clients.values())} clients")
    print(f"{'='*80}")
    print(f"{'BSSID':<20} {'SSID':<30} {'CH':<5} {'ENC':<10} {'Clients':<8} Signal")
    print("-" * 80)
    for bssid, ap in sorted(aps.items(), key=lambda x: x[1].get("signal") or -100, reverse=True):
        ssid_disp = f"[hidden]" if ap["hidden"] else f"'{ap['ssid']}'"
        client_count = len(clients.get(bssid, set()))
        sig = f"{ap['signal']} dBm" if ap['signal'] else "?"
        print(f"{bssid:<20} {ssid_disp:<30} {str(ap['channel']):<5} {ap['encryption']:<10} {client_count:<8} {sig}")


def save_json(path):
    data = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "ap_count": len(aps),
        "aps": [
            {**ap, "clients": list(clients.get(ap["bssid"], set()))}
            for ap in aps.values()
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Passive channel-hopping WiFi scanner")
    parser.add_argument("--iface", required=True, help="Monitor mode interface")
    parser.add_argument("--channels", help="Comma-separated channel list (default: all 2.4+5GHz)")
    parser.add_argument("--out", default="wifi-scan.json", help="Output JSON file")
    parser.add_argument("--duration", type=int, default=0,
                        help="Stop after N seconds (0 = run until Ctrl-C)")
    args = parser.parse_args()

    if args.channels:
        channels = [int(c.strip()) for c in args.channels.split(",")]
    else:
        channels = CHANNELS_24 + CHANNELS_50

    def on_exit(sig, frame):
        stop_event.set()
        print_summary()
        save_json(args.out)
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    hopper = threading.Thread(target=hop_channels, args=(args.iface, channels), daemon=True)
    hopper.start()

    print(f"Passive WiFi recon on {args.iface} — {len(channels)} channels. Ctrl-C to stop.\n")

    try:
        sniff(iface=args.iface, prn=handle, store=False,
              timeout=args.duration if args.duration else None)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        stop_event.set()
        print_summary()
        save_json(args.out)


if __name__ == "__main__":
    main()
