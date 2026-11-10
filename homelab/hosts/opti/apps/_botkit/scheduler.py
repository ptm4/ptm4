"""Once-a-day poster with catch-up and paced retry.

/data/last_post holds the local date ("YYYY-MM-DD") of the last post that landed.
Each pass: if today's slot has passed and today isn't stamped, post now (catch-up
after a restart, or a retry every RETRY_INTERVAL after a failure); otherwise sleep
until the next slot. A config change sets `wake`, which recomputes immediately.
A run that the bot reports as ok (posted, or deliberately skipped) stamps the day.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .log import log

RETRY_INTERVAL = 900   # a failed daily post is re-attempted every 15 min until it lands
IDLE_WAIT = 3600       # longest single sleep; disabled bots re-check this often


def next_post_dt(cfg, now):
    """Next scheduled datetime strictly after `now` (tz-aware)."""
    hh, mm = map(int, cfg["post_time"].split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


class DailyScheduler:
    def __init__(self, store, post_report, status, lock, wake, last_post_path, clock=None):
        self.store = store
        self.post_report = post_report   # cfg -> (ok, detail); scheduled, so not forced
        self.status = status
        self.lock = lock
        self.wake = wake
        self.last_post_path = last_post_path
        self.now = clock or (lambda tz: datetime.now(tz))
        self.retry = {"date": None, "at": None}

    def read_last_post(self):
        try:
            with open(self.last_post_path) as f:
                return f.read().strip()
        except OSError:
            return ""

    def write_last_post(self, date_str):
        tmp = self.last_post_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(date_str)
        os.replace(tmp, self.last_post_path)

    def scheduled_post(self, cfg, today_str):
        self.retry.update(date=today_str, at=self.now(ZoneInfo(cfg["timezone"])))
        ok, detail = self.post_report(cfg)
        with self.lock:
            self.status["last_post_at"] = self.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
            self.status["last_status"] = detail if ok else f"failed: {detail}"
        if ok:
            self.write_last_post(today_str)
        log(f"daily post: {'ok — ' + detail if ok else 'FAILED — ' + detail}")

    def step(self):
        """One pass of the loop: post, or wait (at most IDLE_WAIT)."""
        cfg = self.store.load()
        tz = ZoneInfo(cfg["timezone"])
        now = self.now(tz)
        today = now.date().isoformat()

        if not cfg["enabled"]:
            with self.lock:
                self.status["next_post_at"] = None
            self.wake.wait(timeout=IDLE_WAIT)
            self.wake.clear()
            return

        # catch-up / retry: today's post is due but hasn't landed yet
        hh, mm = map(int, cfg["post_time"].split(":"))
        todays_slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= todays_slot and self.read_last_post() != today:
            if self.retry["date"] == today:
                since = (now - self.retry["at"]).total_seconds()
                if since < RETRY_INTERVAL:  # pace re-attempts after a failure
                    next_try = self.retry["at"] + timedelta(seconds=RETRY_INTERVAL)
                    with self.lock:
                        self.status["next_post_at"] = next_try.isoformat(timespec="seconds")
                    if self.wake.wait(timeout=RETRY_INTERVAL - since):
                        self.wake.clear()
                    return
                log(f"retrying today's post (last attempt {round(since / 60)} min ago)")
            else:
                log(f"catch-up: {today} {cfg['post_time']} is due, posting now")
            self.scheduled_post(cfg, today)
            return

        nxt = next_post_dt(cfg, now)
        with self.lock:
            self.status["next_post_at"] = nxt.isoformat(timespec="seconds")
        wait = (nxt - now).total_seconds()
        if self.wake.wait(timeout=min(wait, IDLE_WAIT)):
            self.wake.clear()
            return  # config changed — recompute
        if self.now(tz) >= nxt:
            self.scheduled_post(self.store.load(), nxt.date().isoformat())

    def run(self):
        while True:
            self.step()
