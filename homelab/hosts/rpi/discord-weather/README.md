# discord-weather

Posts a daily weather report (Open-Meteo, no API key) to a Discord channel
webhook as an embed, and exposes a control API used by the rpi webapp's
**Weather Channel Bot Settings** tab (`https://rpi:8443/#weather`) — locations,
post time, enable/disable, test send and preview are all managed from there,
not by editing files.

Runs as the `discord-weather` service in `../docker-compose.yml`. The webhook
URL comes from `DISCORD_WEBHOOK_URL` in the stack's gitignored `.env` (seed
only — after first boot the volume-persisted config is authoritative and the
URL can be rotated from the webapp tab).

## Config

`/data/config.json` on the `weather_data` volume, seeded on first boot:

```json
{"enabled": true, "post_time": "07:00", "timezone": "America/New_York",
 "webhook_url": "https://discord.com/api/webhooks/…",
 "locations": [{"name": "Bellerose, NY", "lat": 40.7328, "lon": -73.7178}, …]}
```

Edit via the webapp tab (preferred) or `PUT /config`. `/data/last_post` tracks
the last posted date so a restart spanning post time catches up instead of
double-posting. A failed daily post is re-attempted every 15 minutes until it
lands ("late rather than never"); progress shows in `GET /health` and the
webapp's Home-page Weather Bot card.

Layout: locations render as a 2-per-row grid (inline fields + invisible
spacer fields). Sunrise/sunset appear once in the header, taken from the
first location in the list — fine while all locations share a metro area.

## Control API (`:8080`, internal docker network only — never published)

| Endpoint | Purpose |
|---|---|
| `GET /health` | ok flag, enabled, next/last post, last status |
| `GET /config` | config (webhook URL masked) |
| `PUT /config` | update settings; validates, reschedules immediately |
| `POST /send` | build + post the report right now |
| `GET /preview` | today's payload JSON without posting |
| `GET /geocode?q=name` | Open-Meteo geocoding search (top 5) for adding locations |

The webapp proxies these at `/api/weather/*` (backend/routes/weather.js).

## Shell testing

```sh
python3 discord-weather.py --dry-run    # print payload, no post
python3 discord-weather.py --once      # post now and exit
docker logs discord-weather            # daemon activity + schedule
```
