"""_botkit — the scaffolding the Discord bots share.

Every bot in this folder was cloned from discord-weather's skeleton: a volume config
the dashboard edits over HTTP, a once-a-day scheduler with catch-up and a 15-minute
retry, a small control API on :8080, and a post-with-retry HTTP helper. Those pieces
live here once; a bot keeps only its domain logic and hands it to `Bot`.

    from _botkit import Bot, http_json, post_webhook
    bot = Bot(name="discord-sports", defaults=DEFAULT_CONFIG,
              env={"webhook_url": "DISCORD_WEBHOOK_URL_SPORTS"},
              validate=validate_extra, post_report=post_report, preview=preview,
              routes={"/teams": teams_route}, extra_keys=("teams",))
    sys.exit(bot.main(sys.argv[1:]))

The control API contract (paths, /health keys, error strings, secret masking) is what
the v3 dashboard, Pertal and homelab-db's bot check read — change it here and every
migrated bot changes with it. See README.md.

Stdlib only, so a bot image stays python:alpine + tzdata.
"""
from .bot import Bot
from .config import ConfigStore, mask_webhook
from .net import http_json, post_webhook
from .log import log

__all__ = ["Bot", "ConfigStore", "http_json", "log", "mask_webhook", "post_webhook"]
