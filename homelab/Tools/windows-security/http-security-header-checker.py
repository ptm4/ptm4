#!/usr/bin/env python3
"""
http-security-header-checker.py — Audit HTTP security response headers on homelab services.

Checks each configured service for: HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy. Grades each header PASS/WARN/FAIL and writes a report.

Usage:
  python http-security-header-checker.py             # check all configured homelab services
  python http-security-header-checker.py --url https://example.com   # check one URL
  python http-security-header-checker.py --json      # output JSON only (for CI)

Requires: pip install requests
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "..", "..", "security-reports")
REPORT_PATH = os.path.join(REPORTS_DIR, "http-headers-latest.json")

# Homelab services to check
HOMELAB_TARGETS = [
    {"name": "Vaultwarden",     "url": "https://rpi.lan"},
    {"name": "WG Manager",      "url": "https://rpi.lan:8443"},
    {"name": "Pi-hole Admin",   "url": "http://rpi.lan/admin/"},
    {"name": "Homelab Webapp",  "url": "https://rpi.lan:8443"},
]

# Header definitions: name → (required, description, check_fn)
def check_hsts(value):
    if not value:
        return "FAIL", "Missing — HTTPS not enforced"
    if "max-age=0" in value:
        return "FAIL", "max-age=0 disables HSTS"
    try:
        age = int([p for p in value.split(";") if "max-age" in p][0].split("=")[1].strip())
        if age < 2592000:
            return "WARN", f"max-age too short ({age}s, recommend ≥30 days)"
    except (IndexError, ValueError):
        return "WARN", "Could not parse max-age"
    return "PASS", value[:80]

def check_csp(value):
    if not value:
        return "WARN", "Missing — consider adding Content-Security-Policy"
    if "unsafe-inline" in value and "unsafe-eval" in value:
        return "WARN", "CSP has unsafe-inline + unsafe-eval (weakened)"
    if "default-src 'none'" in value or "default-src 'self'" in value:
        return "PASS", value[:80]
    return "WARN", f"CSP present but review needed: {value[:80]}"

def check_xframe(value):
    if not value:
        return "WARN", "Missing — clickjacking possible"
    if value.upper() in ("DENY", "SAMEORIGIN"):
        return "PASS", value
    return "WARN", f"Unexpected value: {value}"

def check_xcto(value):
    if not value:
        return "WARN", "Missing X-Content-Type-Options"
    if value.lower() == "nosniff":
        return "PASS", value
    return "WARN", f"Unexpected value: {value}"

def check_referrer(value):
    if not value:
        return "WARN", "Missing Referrer-Policy"
    safe = {"no-referrer", "no-referrer-when-downgrade", "strict-origin", "strict-origin-when-cross-origin"}
    if value.lower() in safe:
        return "PASS", value
    return "WARN", f"Permissive referrer policy: {value}"

def check_permissions(value):
    if not value:
        return "WARN", "Missing Permissions-Policy (optional but recommended)"
    return "PASS", value[:80]

HEADER_CHECKS = [
    ("Strict-Transport-Security", check_hsts,        "HSTS"),
    ("Content-Security-Policy",   check_csp,         "CSP"),
    ("X-Frame-Options",           check_xframe,      "X-Frame-Options"),
    ("X-Content-Type-Options",    check_xcto,        "X-Content-Type-Options"),
    ("Referrer-Policy",           check_referrer,    "Referrer-Policy"),
    ("Permissions-Policy",        check_permissions, "Permissions-Policy"),
]

GRADE_MAP = {"PASS": "A", "WARN": "C", "FAIL": "F"}


def check_url(name, url):
    result = {"name": name, "url": url, "headers": {}, "grade": "A", "error": None}
    try:
        resp = requests.get(url, timeout=8, verify=False, allow_redirects=True)
        headers = resp.headers
    except requests.exceptions.ConnectionError:
        result["error"] = "Connection refused or host unreachable"
        result["grade"] = "N/A"
        return result
    except requests.exceptions.Timeout:
        result["error"] = "Request timed out"
        result["grade"] = "N/A"
        return result

    worst = "PASS"
    for header_name, check_fn, label in HEADER_CHECKS:
        value = headers.get(header_name, "")
        grade, note = check_fn(value)
        result["headers"][label] = {"grade": grade, "value": value or "(missing)", "note": note}
        if grade == "FAIL" or (grade == "WARN" and worst == "PASS"):
            worst = grade

    result["grade"] = GRADE_MAP.get(worst, "C")
    return result


def print_results(results):
    for r in results:
        url_label = f"{r['name']} ({r['url']})"
        print(f"\n{'=' * 60}")
        print(f"  {url_label}")
        if r["error"]:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  Overall grade: {r['grade']}")
        print()
        for label, info in r["headers"].items():
            color = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}.get(info["grade"], "")
            reset = "\033[0m"
            print(f"  {color}[{info['grade']}]{reset} {label:<28} {info['note']}")


def main():
    parser = argparse.ArgumentParser(description="HTTP security header checker for homelab services")
    parser.add_argument("--url", help="Check a single URL instead of all homelab targets")
    parser.add_argument("--json", action="store_true", dest="json_only", help="Output JSON only")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    targets = [{"name": "Custom", "url": args.url}] if args.url else HOMELAB_TARGETS

    if not args.json_only:
        print(f"Checking {len(targets)} service(s)...")

    results = [check_url(t["name"], t["url"]) for t in targets]

    if not args.json_only:
        print_results(results)

    findings = []
    for r in results:
        if r.get("error"):
            findings.append({
                "severity": "warn",
                "message": f"{r['name']}: {r['error']}",
                "detail": {"url": r["url"], "error": r["error"]}
            })
            continue
        for label, info in r.get("headers", {}).items():
            if info["grade"] in ("WARN", "FAIL"):
                findings.append({
                    "severity": "warn" if info["grade"] == "WARN" else "critical",
                    "message": f"{r['name']} [{info['grade']}] {label}: {info['note']}",
                    "detail": {"url": r["url"], "header": label, "value": info["value"]}
                })

    worst_grade = "ok"
    if any(f["severity"] == "critical" for f in findings):
        worst_grade = "warn"
    elif findings:
        worst_grade = "warn"

    passes = sum(1 for r in results if r.get("grade") == "A")
    summary = f"{passes}/{len(results)} services fully pass, {len(findings)} header finding(s)"

    report = {
        "tool": "http-security-header-checker",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": worst_grade,
        "summary": summary,
        "findings": findings,
        "services": results,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nReport: {REPORT_PATH}")

    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
