"""The bot's /data/config.json: seed, load, validate, mask, merge.

The volume config is authoritative after first boot; env vars only seed it (and fill a
secret the config never got). The dashboard edits it through PUT /config, which merges
into the current config, so a field the form doesn't send keeps its value.
"""
import json
import os
import re
from zoneinfo import ZoneInfo

from .log import log

WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"
POST_TIME_RE = r"([01]\d|2[0-3]):[0-5]\d"
COMMON_KEYS = ("enabled", "post_time", "timezone", "message", "webhook_url")


def mask_webhook(url):
    return f"{WEBHOOK_PREFIX}…{url[-6:]}" if url else ""


class ConfigStore:
    """`env` maps config field -> env var that seeds it, e.g.
    {"webhook_url": "DISCORD_WEBHOOK_URL_SPORTS", "api_key": "JELLYFIN_API_KEY"}.
    `secret_fields` are blanked in public views (with a `<field>_configured` flag) and
    a blank value in a PUT keeps the stored one; webhook_url is always treated so,
    masked rather than blanked. `validate_extra(cfg)` checks the bot's own fields and
    returns an error string or None."""

    def __init__(self, data_dir, defaults, env=None, secret_fields=(), extra_keys=(),
                 validate_extra=None):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, "config.json")
        self.defaults = defaults
        self.env = dict(env or {})
        self.secret_fields = tuple(secret_fields)
        self.keys = COMMON_KEYS + tuple(k for k in (*extra_keys, *self.secret_fields)
                                        if k not in COMMON_KEYS)
        self.validate_extra = validate_extra

    def _env_value(self, field):
        return os.environ.get(self.env[field], "")

    def load(self):
        try:
            with open(self.path) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = dict(self.defaults)
            for field in self.env:
                cfg[field] = self._env_value(field)
            self.save(cfg)
            log(f"seeded default config at {self.path}")
        # env secrets as fallback if config never got them
        for field in self.env:
            if not cfg.get(field):
                cfg[field] = self._env_value(field)
        # configs written before a key existed pick up its default
        for k, v in self.defaults.items():
            cfg.setdefault(k, v)
        return cfg

    def fallback(self):
        """Defaults + env, for --once/--dry-run where DATA_DIR isn't writable."""
        return {**self.defaults, **{f: self._env_value(f) for f in self.env}}

    def save(self, cfg):
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, self.path)

    def validate(self, cfg):
        """Returns an error string, or None if cfg is a valid full config. The common
        checks run first and the webhook last, around the bot's own, so the first
        error a form sees is the same as before the kit existed."""
        if not isinstance(cfg, dict):
            return "config must be an object"
        if not isinstance(cfg.get("enabled"), bool):
            return "enabled must be true/false"
        if not re.fullmatch(POST_TIME_RE, str(cfg.get("post_time", ""))):
            return "post_time must be HH:MM (24h)"
        msg = cfg.get("message", "")
        if not isinstance(msg, str) or len(msg) > 2000:
            return "message must be text, max 2000 characters"
        try:
            ZoneInfo(str(cfg.get("timezone")))
        except Exception:
            return f"unknown timezone {cfg.get('timezone')!r}"
        if self.validate_extra:
            err = self.validate_extra(cfg)
            if err:
                return err
        url = cfg.get("webhook_url", "")
        if url and not url.startswith(WEBHOOK_PREFIX):
            return f"webhook_url must start with {WEBHOOK_PREFIX}"
        return None

    def public(self, cfg):
        pub = dict(cfg)
        pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
        pub["webhook_configured"] = bool(cfg.get("webhook_url"))
        for k in self.secret_fields:
            pub[k] = ""
            pub[f"{k}_configured"] = bool(cfg.get(k))
        return pub

    def merge(self, current, incoming):
        """PUT /config: known keys from `incoming` over `current`. A masked or blank
        webhook, or a blank secret, means "keep the current one"."""
        merged = {**current, **{k: v for k, v in incoming.items() if k in self.keys}}
        wh = incoming.get("webhook_url", "")
        if not wh or "…" in wh:
            merged["webhook_url"] = current.get("webhook_url", "")
        for k in self.secret_fields:
            if not incoming.get(k):
                merged[k] = current.get(k, "")
        return merged
