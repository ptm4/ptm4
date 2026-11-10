"""Post-with-retry JSON over urllib — the helper every bot carried a copy of."""
import json
import time
import urllib.request

RETRY_SLEEP = 5  # seconds between attempts


def http_json(url, body=None, tries=3, timeout=30, ua=None, headers=None, method=None):
    """Returns (status, parsed JSON or None). Raises RuntimeError after `tries` failures.

    The User-Agent is per call because the endpoints disagree (verified 2026-08-07):
    ESPN's edge 403s custom/browser-spoofed UAs but allows urllib's default, while
    Discord's Cloudflare 403s the default Python-urllib UA and allows a custom one.
    So `ua=None` sends urllib's default; Discord callers pass their bot's own string.
    """
    for attempt in range(tries):
        hdrs = {"Content-Type": "application/json"}
        if ua:
            hdrs["User-Agent"] = ua
        hdrs.update(headers or {})
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(RETRY_SLEEP)


def post_webhook(url, payload, ua=None):
    """POST a webhook payload; raises RuntimeError unless Discord answers 2xx."""
    status, _ = http_json(url, body=payload, ua=ua)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")
