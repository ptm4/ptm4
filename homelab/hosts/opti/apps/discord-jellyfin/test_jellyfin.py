"""Offline regression tests: no Jellyfin calls and no Discord messages sent.

Run from this folder:  python3 -m unittest -v test_jellyfin.py
"""
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="jfbot-test-"))
spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-jellyfin.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

KEY = "0123456789abcdef0123456789abcdef"  # fake, test-only
CFG = {**bot.DEFAULT_CONFIG, "api_key": KEY,
       "webhook_url": "https://discord.com/api/webhooks/test/test"}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code):
    return urllib.error.HTTPError("http://jf/x", code, "nope", {}, io.BytesIO(b""))


def yesterday_item():
    created = datetime.now(timezone.utc) - timedelta(days=1)
    return {"Type": "Movie", "Name": "Test Movie", "ProductionYear": 2026,
            "DateCreated": created.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")}


class AuthHeader(unittest.TestCase):
    def test_sends_authorization_header_not_legacy_token(self):
        seen = []

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return FakeResponse(json.dumps({"ServerName": "nn"}).encode())

        with patch.object(bot.urllib.request, "urlopen", fake_urlopen):
            bot.jf_get(CFG, "/System/Info")
        headers = {k.lower(): v for k, v in seen[0].header_items()}
        self.assertEqual(headers.get("authorization"), f'MediaBrowser Token="{KEY}"')
        self.assertNotIn("x-emby-token", headers)


class FailureReporting(unittest.TestCase):
    def _post(self, side_effect):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            raise side_effect

        with patch.object(bot.urllib.request, "urlopen", fake_urlopen), \
                patch.object(bot.time, "sleep", lambda s: None), \
                patch.object(bot, "post_webhook") as webhook:
            ok, detail = bot.post_report(CFG, force=True)
            payload, failed, _ = bot.build_payload(CFG)
        webhook.assert_not_called()
        return ok, detail, payload, failed, calls

    def test_401_is_reported_as_auth_failure_and_not_retried(self):
        ok, detail, payload, failed, calls = self._post(http_error(401))
        self.assertFalse(ok)
        self.assertIn("rejected the API key (HTTP 401)", detail)
        self.assertNotIn("unreachable", detail)
        self.assertEqual(failed, ["Jellyfin"])
        self.assertIn("rejected the API key (HTTP 401)", payload["embeds"][0]["description"])
        self.assertEqual(len(calls), 2)  # one post_report + one build_payload, no retries

    def test_403_is_reported_as_auth_failure(self):
        ok, detail, *_ = self._post(http_error(403))
        self.assertIn("rejected the API key (HTTP 403)", detail)

    def test_connection_error_is_reported_as_unreachable(self):
        ok, detail, payload, failed, calls = self._post(urllib.error.URLError("refused"))
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("Jellyfin unreachable"))
        self.assertEqual(payload["embeds"][0]["description"],
                         "⚠️ Jellyfin unreachable — no arrivals data")
        self.assertEqual(len(calls), 4)  # tries=2, for each of the two builds

    def test_check_endpoint_error_names_the_auth_failure(self):
        with patch.object(bot.urllib.request, "urlopen", side_effect=http_error(401)):
            with self.assertRaises(bot.JellyfinAuthError) as cm:
                bot.jf_get(CFG, "/System/Info", timeout=10)
        self.assertIn("HTTP 401", str(cm.exception))


class HappyPath(unittest.TestCase):
    def test_yesterdays_movie_is_listed(self):
        body = json.dumps({"Items": [yesterday_item()]}).encode()
        # exactly 24h ago always falls inside "yesterday" in UTC
        with patch.object(bot.urllib.request, "urlopen",
                          lambda req, timeout=None: FakeResponse(body)):
            payload, failed, has_items = bot.build_payload({**CFG, "timezone": "UTC"})
        self.assertEqual(failed, [])
        self.assertTrue(has_items)
        self.assertIn("Test Movie", payload["embeds"][0]["fields"][0]["value"])


if __name__ == "__main__":
    unittest.main()
