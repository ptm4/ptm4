#!/usr/bin/env python3
"""
geoip-log-mapper.py — Parse Nginx access logs, geo-locate external IPs, generate a world map.

Reads from the Nginx stack log on the Samba share (or --log path), extracts external IPs,
batch-queries ip-api.com for GeoIP data, and outputs:
  - Terminal table of top IPs by hit count
  - reports/geoip-latest.json  (structured report)
  - reports/geoip-latest.html  (interactive folium map)

Usage:
  python geoip-log-mapper.py
  python geoip-log-mapper.py --log "\\\\rpi.lan\\ptm\\logging\\stack.log"
  python geoip-log-mapper.py --top 30 --no-map

Requires: pip install requests folium
"""

import argparse
import ipaddress
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "..", "..", "security-reports")
REPORT_JSON = os.path.join(REPORTS_DIR, "geoip-latest.json")
REPORT_HTML = os.path.join(REPORTS_DIR, "geoip-latest.html")

DEFAULT_LOG = r"\\rpi.lan\ptm\logging\stack.log"

# Nginx combined log format IP extraction
LOG_IP_RE = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')

RFC1918_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]

# Known threat/watchlist IPs (extend as needed)
WATCHLIST_ASNS = {"AS209100", "AS60781"}  # example: common abuse ASNs


def is_private(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in RFC1918_NETWORKS)
    except ValueError:
        return True


def extract_ips(log_path):
    ip_counter = Counter()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = LOG_IP_RE.match(line.strip())
                if m:
                    ip = m.group(1)
                    if not is_private(ip):
                        ip_counter[ip] += 1
    except FileNotFoundError:
        print(f"ERROR: Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"ERROR: Cannot read {log_path} — check Samba mount.", file=sys.stderr)
        sys.exit(1)
    return ip_counter


def geoip_batch(ips):
    """Query ip-api.com/batch — 100 IPs per request, free, no key needed."""
    results = {}
    chunk_size = 100
    ip_list = list(ips)

    for i in range(0, len(ip_list), chunk_size):
        chunk = ip_list[i:i + chunk_size]
        try:
            resp = requests.post(
                "http://ip-api.com/batch",
                json=[{"query": ip, "fields": "query,status,country,countryCode,city,isp,org,as,lat,lon"} for ip in chunk],
                timeout=15,
            )
            resp.raise_for_status()
            for entry in resp.json():
                if entry.get("status") == "success":
                    results[entry["query"]] = entry
        except requests.RequestException as e:
            print(f"GeoIP batch query failed: {e}", file=sys.stderr)
        if len(ip_list) > chunk_size:
            time.sleep(1)  # ip-api.com rate limit: 45 req/min on free tier

    return results


def build_html_map(geo_data, ip_counter):
    try:
        import folium
    except ImportError:
        print("folium not installed — skipping HTML map. Run: pip install folium", file=sys.stderr)
        return None

    m = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB dark_matter")
    for ip, geo in geo_data.items():
        lat, lon = geo.get("lat"), geo.get("lon")
        if not lat or not lon:
            continue
        count = ip_counter.get(ip, 1)
        radius = max(5, min(20, count))
        on_watchlist = geo.get("as", "") in WATCHLIST_ASNS

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color="#ff4444" if on_watchlist else "#ff9900",
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(
                f"<b>{ip}</b><br>"
                f"{geo.get('city','')}, {geo.get('country','')}<br>"
                f"ISP: {geo.get('isp','')}<br>"
                f"ASN: {geo.get('as','')}<br>"
                f"Hits: {count}",
                max_width=250,
            ),
            tooltip=f"{ip} ({count} hits)"
        ).add_to(m)

    return m._repr_html_()


def print_table(ip_counter, geo_data, top_n):
    print(f"\n{'IP':<18} {'Hits':<6} {'Country':<15} {'City':<20} {'ISP':<35} {'ASN'}")
    print("-" * 105)
    for ip, count in ip_counter.most_common(top_n):
        geo = geo_data.get(ip, {})
        print(f"{ip:<18} {count:<6} {geo.get('country','?'):<15} {geo.get('city','?'):<20} "
              f"{geo.get('isp','?')[:33]:<35} {geo.get('as','?')}")


def main():
    parser = argparse.ArgumentParser(description="GeoIP log mapper for Nginx access logs")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Path to Nginx access log")
    parser.add_argument("--top", type=int, default=20, help="Number of top IPs to show")
    parser.add_argument("--no-map", action="store_true", help="Skip HTML map generation")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print(f"Parsing log: {args.log}")
    ip_counter = extract_ips(args.log)
    unique_ips = len(ip_counter)
    total_hits = sum(ip_counter.values())
    print(f"Found {unique_ips} unique external IPs ({total_hits} total hits)")

    if not ip_counter:
        print("No external IPs found — is the log path correct?")
        return

    print(f"GeoIP lookup for {min(unique_ips, 500)} IPs...")
    top_ips = [ip for ip, _ in ip_counter.most_common(500)]
    geo_data = geoip_batch(top_ips)

    print_table(ip_counter, geo_data, args.top)

    map_html = None
    if not args.no_map:
        print("\nGenerating map...")
        map_html = build_html_map(geo_data, ip_counter)
        if map_html:
            with open(REPORT_HTML, "w", encoding="utf-8") as f:
                f.write(map_html)
            print(f"Map: {REPORT_HTML}")

    # Top countries stat
    countries = Counter(geo_data[ip].get("country", "Unknown") for ip in geo_data)

    findings = []
    for ip, geo in geo_data.items():
        if geo.get("as", "") in WATCHLIST_ASNS:
            findings.append({
                "severity": "warn",
                "message": f"Watchlist ASN: {ip} ({geo.get('country')}) — {geo.get('as')}",
                "detail": {**geo, "hits": ip_counter.get(ip, 0)}
            })

    report = {
        "tool": "geoip-log-mapper",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": "warn" if findings else "ok",
        "summary": f"{unique_ips} unique external IPs, {total_hits} hits, top country: {countries.most_common(1)[0][0] if countries else 'N/A'}",
        "findings": findings,
        "top_ips": [
            {**geo_data.get(ip, {}), "ip": ip, "hits": count}
            for ip, count in ip_counter.most_common(50)
        ],
        "top_countries": [{"country": c, "count": n} for c, n in countries.most_common(15)],
        "has_map": map_html is not None,
    }

    with open(REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {REPORT_JSON}")


if __name__ == "__main__":
    main()
