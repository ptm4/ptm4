# discord-healthdigest

Posts a daily homelab health digest to a Discord channel webhook as an embed,
and exposes a control API used by the rpi webapp's **Health Bot** tab
(`https://rpi:8443/#healthdigest`) — post time, alerts-only mode, Pi-hole
credentials, enable/disable, test send and preview are all managed from there,
not by editing files.

Clone of `../discord-weather` (same scaffolding: volume config, catch-up
scheduler, control API on internal :8080); only the domain logic differs.

## Data sources

- **homelab-doctor** — reads `homelab-doctor-latest.json` from the agent-logs
  mount (`/mnt/opti-fs/ptm/agent-logs` → `/agent-logs:ro`). The doctor SSHes
  around the homelab from opti every 30 min; this bot never SSHes anywhere.
  Covers: host reachability, root/pool disk, containers, services + certs,
  vpn-stack-heal watchdog state, autoupdate/autoreboot timer results, stale
  reports.
- **Pi-hole v6 API** — queried live (Pi-hole runs on this same rpi):
  `POST /api/auth` → `GET /api/stats/summary` + `top_domains?blocked=true`
  → `DELETE /api/auth` (session always released; v6 caps concurrent sessions).

Every section is independently error-guarded — a dead source renders as
"⚠️ unavailable" instead of killing the digest. If the doctor report is older
than `doctor_max_age_hours` the digest still posts, with a staleness warning.
Optional `request_fresh_report` kicks a doctor run via the opti dispatcher
first (needs `DISPATCHER_URL` + `HL_DISPATCH_TOKEN`).

## Config

`/data/config.json` on the `healthdigest_data` volume, seeded on first boot
from `DISCORD_WEBHOOK_URL_HEALTHDIGEST` + `PIHOLE_WEB_PASSWORD` in the stack's
gitignored `.env` (seed only — after first boot the volume config is
authoritative; rotate secrets from the webapp tab).

`post_mode`:
- `always` — post every day at `post_time`.
- `alerts_only` — quiet days are skipped (stamped as done, logged); anything
  red/amber posts. The webapp's **Send now** button always posts.

## Control API (internal :8080)

`GET /health` · `GET /config` (secrets masked) · `PUT /config` ·
`POST /send` (always posts) · `GET /preview` (payload + `has_alerts`, no post)
