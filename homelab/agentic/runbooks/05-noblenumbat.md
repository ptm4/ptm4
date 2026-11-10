# noblenumbat (media server)

## Roles
- Jellyfin / Kavita / *arr media stack, with qBittorrent, SABnzbd, Prowlarr, Mylar3 and
  FlareSolverr behind Gluetun. Compose at `/opt/yams/docker-compose.yaml`.
- Media itself lives on **opti**, mounted at `/mnt/opti-library`, `/mnt/opti-shows` and
  `/mnt/opti-media` — not on the local NVMe.

## It is NOT a code server (corrected 2026-07-25)
The `noblenumbat:~/code/ptm4` clone **was deleted on 2026-07-22** and this host no longer
holds a copy of the repo. Earlier revisions of this runbook called it the primary copy and
said "edit there — the opti mount is stale"; that is wrong, and following it sends you to a
path that does not exist.

Deleting that clone is also what destroyed the only copy of several (then gitignored) skills
and rules. For where the working copy lives now, see "Where the repo lives" in
[`../rules/01-homelab-context.md`](../rules/01-homelab-context.md) — not restated here so it
can't drift again.

## Known incident: cooling outage (2026-07-16)
- **Symptom:** the whole host went unreachable.
- **Cause:** a **cooling/thermal issue** — NOT a Jellyfin or software fault.
- **Lesson:** if noblenumbat drops off entirely (no SSH, no services), suspect **hardware
  thermal** first, not the media apps. Check physical cooling / ambient temp / fans before
  debugging software.

## Unattended reboots are HELD here (2026-11-09)
- **Why:** the 03:00 `homelab-autoreboot` left the box dark for 1-6 days on 09-11, 09-25,
  10-14, 10-21 and 11-04. The OS shuts down cleanly each time; the next kernel only starts
  when someone powers it on, so the hang is in firmware. Most likely cause: Latitude 7400
  BIOS 1.6.1 (2019) with `WarningsAndErr=PromptWrnErr`, which stops POST on any warning
  (adapter/dock warnings are on, power is USB-C) and waits for F1.
- **State:** `noblenumbat-deploy.yml` keeps `homelab-autoreboot.timer` disabled
  (`NN_AUTOREBOOT: "off"`). Auto-updates still install; a pending kernel reboot waits for a
  hand reboot. BIOS `WarningsAndErr` set to `ContWrnErr`; read/set it from the OS at
  `/sys/class/firmware-attributes/dell-wmi-sysman/attributes/WarningsAndErr/current_value`
  (no BIOS password set), or F2 > POST Behavior > Warnings and Errors.
- **To re-enable:** one supervised reboot with someone at the box. If it returns within ~5
  min, flip `NN_AUTOREBOOT` to `"on"`. If it hangs, the screen names the POST warning.
- **Alerting:** ntfy runs on this host, so it can't page about this host. `notify.py` falls
  back to the `HL_DISCORD_WEBHOOK` Discord webhook (opti `/etc/hl-agents.env`) when ntfy
  fails, and homelab-doctor probes Jellyfin and ntfy from opti as critical services.

## Adding media
- Movies: use the `radarr-add` skill (adds to Radarr on noblenumbat, triggers a search).
- TV/docuseries: use the `sonarr-add` skill.

## stream-station (:8098) — debugging the dashboard's Streams page

Container `stream-station`, added 2026-08-07. Backs `https://webapp.lan:8443/streams/`:
streamlink resolves a Twitch/YouTube/Kick channel, headless VLC remuxes it to HLS. Four slots.
Source in the repo at `homelab/hosts/noblenumbat/stream-station/`; **it is the only service in
this stack that is built rather than pulled**, so a code change needs a rebuild, not a restart.

### Is it broken, or is the source just offline?

`/status` answers this without guessing. Per slot it reports `state`
(`idle → starting → running → ended`), the source, and two numbers that matter:

```bash
curl -s http://192.168.1.6:8098/status | python3 -m json.tool
```

- **`state: ended` with `error` naming the platform** — the *source* is offline, not a fault.
  A dead channel reads literally `No playable streams found on this URL: …` within ~15s.
- **`state: running` but `last_segment_age_s` climbing past ~20** — this is the
  **alive-but-stalled** case, and the one worth chasing. VLC is up, the slot looks healthy,
  but no new video is being written. Ad break, source hiccup, or the rot below.
- **`state: ended` with `reaped: idle`** — nobody was watching for 5 minutes. Working as
  intended, not a bug. The page sends `/keepalive` for every live slot while it is open and
  visible; close or hide the page and every slot stops on schedule.

### THE known failure mode: streamlink ad-bypass rot

**Symptom: Twitch streams start fine, then stall every few minutes.** This is streamlink's
Twitch ad-bypass breaking against a site change — it happens every few months and it is by far
the most likely cause of flaky playback.

**Fix it by rebuilding the image. Do not debug VLC first** — VLC is downstream of the problem
and its logs will only show a starved input.

```bash
ssh noblenumbat 'cd /opt/yams && docker compose build --no-cache stream-station && docker compose up -d stream-station'
```

For a durable fix, bump `STREAMLINK_REV` in `stream-station/Dockerfile` (any new value busts
the pip layer) and push, or re-run the **Deploy noblenumbat Stack** workflow via
`workflow_dispatch` — its build step pulls the current streamlink release.

### Reading the logs

Two sources, and they fail in visibly different ways:

```bash
ssh noblenumbat 'docker logs stream-station --tail 50'
curl -s http://192.168.1.6:8098/status | python3 -c "import json,sys; [print(s['slot'], s['error']) for s in json.load(sys.stdin)['slots'] if s['error']]"
```

- The container log carries the control plane: starts, stops, and `[reaper]` lines.
- `/status.error` carries the **last 50 stderr lines of whichever process died**, which is
  usually the faster answer. **streamlink errors name the platform, channel or quality**
  (`No playable streams found`, `Unable to open URL`); **VLC errors name `sout`, `mux`,
  `livehttp` or `access_output`**. That single distinction tells you which half to fix.

### Other things that bite

- **Token mismatch → every start returns 401.** `HL_STREAM_TOKEN` in `/opt/yams/.env` must
  equal the one in the webapp's `/srv/docker/compose/.env` on **opti** (the app tier moved
  off rpi 2026-09-10). Neither file is in git, and
  the deploy workflows never touch `.env` — so a rebuilt host needs it re-added by hand.
- **Nothing plays but `/status` says running** → check the video path separately from the
  control path. `curl -sk https://webapp.lan:8443/hls/slot1/index.m3u8` must return a
  playlist with **no redirect**; if it 301s, someone added a trailing slash to the `/hls`
  location in `nginx-wg.conf` (documented trap — it rewrites to nginx's container-internal
  port 443 and lands on Vaultwarden).
- **Segment length isn't what you set.** `seglen` is a floor, not a setting: `mux=ts{use-key-frames}`
  only cuts on keyframes, so a source with 10-second GOPs yields 10-second segments.
- **VLC will not run as root.** The container runs as uid 1000 and the tmpfs is mounted
  `uid=1000`; if you change one, change the other or VLC cannot write segments.
- **Thermals.** This is the host with a cooling outage on record (above). The service is
  remux-only by design (~3.5% CPU for a live 1080p stream) and is the only container in the
  stack with `mem_limit`/`cpus` caps. If you are ever tempted to add transcoding, that is the
  constraint you are trading against.
