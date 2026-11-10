# _botkit — shared Discord bot scaffolding

The Discord bots here were cloned from discord-weather's skeleton, so each one carried
the same config store, daily scheduler, control API and post-with-retry helper. Those
live here once; a migrated bot keeps only its domain logic (fetch, build the embed,
post) and hands it to `Bot`. Stdlib only.

| Module | What it is |
|---|---|
| `config.py` | `ConfigStore`: `/data/config.json` seed-from-env, load (env fallback + new-key defaults), atomic save, common validation, webhook/secret masking, PUT merge |
| `scheduler.py` | `DailyScheduler`: one post a day at `post_time`, catch-up after a restart, retry every 15 min until it lands, `/data/last_post` date stamp |
| `api.py` | the control API on :8080 (`/health`, `/config`, `PUT /config`, `/preview`, `POST /send`, plus bot routes) |
| `net.py` | `http_json` (3 tries, 5 s apart) and `post_webhook` |
| `bot.py` | `Bot`: wires the above to a bot's callbacks; `--once` / `--dry-run` / daemon |

## Migrated bots

| Bot | Status |
|---|---|
| discord-sports | on _botkit (2026-11-10) |
| discord-healthdigest, discord-jellyfin | own copies; candidates (identical scaffolding) |
| discord-hltv | own copy; needs multi-slot `post_times` + failure alert in the kit first |
| discord-weather | own copy; deliberately not migrated (most custom, least to gain) |

## The contract

What the API answers is read by the v3 dashboard's proxies (`webapp.v3.Fable/backend/routes/<bot>.js`),
Pertal (`GET /config` of weather and sports), homelab-db's bot check (`ingest.py`
`ingest_bot_health`: `enabled`, `last_status`, `last_post_at`) and the deploy smoke test.
Change behaviour here and every migrated bot changes with it, so:

- `python3 -m unittest -v test_botkit.py` here, and each migrated bot's contract test
  (`discord-sports/test_sports_contract.py`), must pass. checks.yml runs both.
- Known shared gaps, deliberately left as they were when the copies were merged:
  4xx answers are retried like network errors, Discord 429 `Retry-After` is not honoured,
  and a manual Send-now can race a scheduled post. Fixing them is a behaviour change for
  every migrated bot, so it gets its own change.

## How it reaches an image

Each migrated bot keeps its own build context and adds the kit as a named one:

```yaml
# docker-compose.apps.yml
build:
  context: ./discord-sports
  additional_contexts:
    botkit: ./_botkit
```
```dockerfile
COPY --from=botkit . ./_botkit/
```

`opti-apps-deploy.yml` rsyncs this folder to `/srv/docker/compose/_botkit` next to the
bots. In the repo a bot finds the kit one directory up (`sys.path.append(..)`), so
`--dry-run` and tests work from the bot's folder.

## Migrating a bot

1. Write a contract test for the bot over HTTP (copy `discord-sports/test_sports_contract.py`)
   and make it pass against the bot **before** touching it.
2. Replace the scaffolding with `Bot(...)`; keep `Handler = bot.Handler`.
3. Contract test passes unchanged; diff old vs new responses; add both to checks.yml.
4. Dockerfile `COPY --from=botkit`, compose `additional_contexts`.
