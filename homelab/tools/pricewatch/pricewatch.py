#!/usr/bin/env python3
"""
pricewatch.py — track PC-part prices at Newegg / eBay / Amazon for the opti rebuild.

Reads items.json (same dir), fetches each item's product page, extracts the price with a
retailer-specific parser, and writes a standard collector report via _report.py:

    <agent-logs>/pricewatch-latest.json          current prices + embedded history
    <agent-logs>/pricewatch-latest/<date>.json   dated copy (history source)

The embedded `history` block is rebuilt each run from the dated copies, so the webapp
widget gets sparkline-ready series from the single latest file. homelab-db ingests the
same report into the price_history table (see ingest.py) and raises findings when an
item drops below its target price.

Retailer notes (hard-won):
  - eBay multi-variation listings show the CHEAPEST config as the headline price. For
    those, items.json must carry "variation_id" — the price is then taken from the
    page's embedded variationsMap next to that id. Prefer single-config listings.
  - Amazon blocks bots often; a block is recorded as an error, not a price of null
    silently. The trend still works from the days that succeed.

Stdlib only, like every other collector. Manual run:  python3 pricewatch.py [-v]
"""

import gzip
import io
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collectors"))
from _report import write_report, agent_logs_dir  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_BASE = "pricewatch-latest"
HISTORY_DAYS = 180

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return raw.decode("utf-8", "replace")


def _money(text):
    return float(text.replace(",", ""))


def parse_newegg(html, item):
    if "are you a human" in html.lower():
        return None, None, "bot check"
    in_stock = 0 if re.search(r"OUT OF STOCK|Sold Out", html, re.I) else 1
    # The buy box is JS-rendered, but the main product's embedded JSON carries the
    # displayed price as list-price minus instant rebate (verified against the rendered
    # page on first-party and marketplace listings alike, 2026-08-24). Recommendation
    # tiles ("ItemCell") don't carry this exact pair, so the first hit is the product.
    m = re.search(r'"OriginalUnitPrice":([\d.]+),"OriginalInstantRebateAmount":([\d.]+)', html)
    if m:
        return round(float(m.group(1)) - float(m.group(2)), 2), in_stock, None
    # Fallback: the realtime product API, for first-party items (/p/N82E...).
    im = re.search(r"/p/([A-Z0-9-]+)", item.get("url") or "")
    if im:
        try:
            api = fetch("https://www.newegg.com/product/api/ProductRealtime?ItemNumber="
                        + im.group(1))
            main = (json.loads(api) or {}).get("MainItem") or {}
            if main.get("FinalPrice"):
                return float(main["FinalPrice"]), 1 if main.get("Instock") else 0, None
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            pass
    return None, None, "no price found"


def parse_ebay(html, item):
    vid = item.get("variation_id")
    if vid:
        idx = html.find('"%s"' % vid)
        if idx < 0:
            return None, None, "variation id %s not on page" % vid
        m = re.search(r"US \$([\d,]+\.\d{2})", html[idx:idx + 600])
        if not m:
            return None, None, "no price near variation id"
        return _money(m.group(1)), 1, None
    if re.search(r"(this listing (was |has )?ended|item is out of stock|listing ended)", html, re.I):
        return None, 0, "listing ended / out of stock"
    m = re.search(r'itemprop="price"[^>]*content="(\d+(?:\.\d+)?)"', html)
    if not m:
        m = re.search(r'"text"\s*:\s*"US \$([\d,]+\.\d{2})(?:/ea)?"', html)
    if not m:
        m = re.search(r"US \$([\d,]+\.\d{2})", html)
    if not m:
        return None, None, "no price found"
    return _money(m.group(1)), 1, None


def parse_amazon(html, item):
    if re.search(r"captcha|Robot Check|automated access", html, re.I):
        return None, None, "bot check"
    m = re.search(r'"priceAmount"\s*:\s*(\d+(?:\.\d+)?)', html)
    if not m:
        m = re.search(r'a-offscreen">\$([\d,]+\.\d{2})<', html)
    if not m:
        return None, None, "no price found"
    in_stock = 0 if re.search(r"Currently unavailable", html) else 1
    return _money(m.group(1)), in_stock, None


PARSERS = {"newegg": parse_newegg, "ebay": parse_ebay, "amazon": parse_amazon}


def check_item(item, verbose=False):
    out = {k: item.get(k) for k in
           ("id", "label", "category", "retailer", "url", "target_price", "note")}
    out["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parser = PARSERS.get(item.get("retailer"))
    if parser is None:
        out.update(price=None, in_stock=None, error="unknown retailer")
        return out
    try:
        html = fetch(item["url"])
        price, in_stock, error = parser(html, item)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        price, in_stock, error = None, None, str(exc)[:200]
    out.update(price=price, in_stock=in_stock, error=error)
    if verbose:
        print("  %-28s %-8s %s" % (item["id"], item["retailer"],
                                   "$%.2f" % price if price else "ERR: %s" % error))
    return out


def build_history(items_now):
    """Per-item daily price series from this collector's own dated reports."""
    series = {}
    dated_dir = os.path.join(agent_logs_dir(), REPORT_BASE)
    files = sorted(os.listdir(dated_dir))[-HISTORY_DAYS:] if os.path.isdir(dated_dir) else []
    for name in files:
        if not name.endswith(".json"):
            continue
        day = name[:-5]
        try:
            with open(os.path.join(dated_dir, name)) as fh:
                for it in json.load(fh).get("items", []):
                    if it.get("price") is not None:
                        series.setdefault(it["id"], []).append({"d": day, "p": it["price"]})
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for it in items_now:
        if it.get("price") is None:
            continue
        s = series.setdefault(it["id"], [])
        if not s or s[-1]["d"] != today:
            s.append({"d": today, "p": it["price"]})
        else:
            s[-1]["p"] = it["price"]
    return series


def main():
    verbose = "-v" in sys.argv
    with open(os.path.join(HERE, "items.json")) as fh:
        config = json.load(fh)
    items = config.get("items", [])

    results = []
    for i, item in enumerate(items):
        if i:
            time.sleep(random.uniform(2, 5))  # polite spacing between retailer hits
        results.append(check_item(item, verbose))

    ok = [r for r in results if r["price"] is not None]
    errs = [r for r in results if r["price"] is None]
    below = [r for r in ok
             if r.get("target_price") is not None and r["price"] <= r["target_price"]]

    status = "ok" if not errs else ("warn" if ok else "error")
    bits = ["%d/%d items priced" % (len(ok), len(results))]
    if below:
        bits.append("%d AT/BELOW target: %s" %
                    (len(below), ", ".join(r["id"] for r in below)))
    if errs:
        bits.append("%d failed" % len(errs))

    report = {
        "tool": "pricewatch",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "summary": " · ".join(bits),
        "items": results,
        "history": build_history(results),
        "below_target": [r["id"] for r in below],
        "findings": [{"severity": "warn",
                      "message": "price-watch: %s at $%.2f, at/below target $%.2f — buy window"
                                 % (r["label"], r["price"], r["target_price"])}
                     for r in below],
    }
    latest, dated = write_report(REPORT_BASE, report)
    if verbose:
        print("wrote %s\n      %s\n%s" % (latest, dated, report["summary"]))


if __name__ == "__main__":
    main()
