# homelab.db — the queryable homelab

Everything the homelab collects, as rows you can query, on opti. If you are a coding agent
with the `homelab` MCP tools available, **use them before probing a host** — the answer to
most questions is already indexed here.

Design notes and rationale live in `homelab/tools/homelab-db/README.md`. This is the
operator's page.

## Where it is

| Thing | Where |
|---|---|
| Database | `/srv/red/opsdb/homelab.db` (ZFS dataset `red/opsdb`) — **opti-local only** |
| Backup snapshot | `/srv/red/fs/ptm/homelab-db/backup/homelab-snapshot.db` (in the shared tree, so coldcopy takes it) |
| Code | `homelab/tools/homelab-db/` |
| Units | `homelab-db.service` (`:9100`), `homelab-db-ingest.timer` (`*:12,42`) |
| Token | `HL_DB_TOKEN` in `/etc/hl-agents.env` on opti |

**The database is not on the Samba share on purpose.** SQLite WAL requires same-host
shared memory, so opening it over the CIFS mount from tux is unsafe even read-only. There
is no path from `/home/ptm/opti/...` to this file — query `:9100` instead.

## The MCP tools

Registered in the repo-root `.mcp.json`; a session in this repo gets them automatically,
provided `HL_DB_TOKEN` is exported in the shell that launched Claude Code.

| Tool | Use it for |
|---|---|
| `hl_status` | "How is the homelab?" — doctor status, per-host lines, services, open findings, stale feeds |
| `hl_host` | Everything about one host: curated facts, latest reports, containers, recent changes |
| `hl_search_docs` | FTS5 over every runbook, rule, skill and generated doc. **Try this first.** |
| `hl_incidents` | "Have we seen this symptom before?" — curated incident + decision registry |
| `hl_changes` | What containers/mounts/devices appeared, vanished or changed, and when |
| `hl_metrics` | Any numeric history: host vitals at 60s (30d) or hourly, collector metrics back to June 2026 |
| `hl_dataplane` | Where data comes from and whether the pipeline is fresh |
| `hl_schema` | Tables, row counts and querying hints — call before `hl_query` |
| `hl_query` | Read-only SQL for anything the shaped tools do not cover |

### Claude Desktop

Desktop can't read `.mcp.json` and only launches stdio servers, so it goes through
`homelab/tools/homelab-db/mcp_stdio_bridge.py` — a stdlib stdio→HTTP shim (tux has no
node, so `npx mcp-remote` was never an option). Installed copy lives at
`~/.local/bin/hl-mcp-bridge.py` (local disk on purpose: a hung CIFS mount must not stall
Desktop startup); registered in `~/.config/Claude/claude_desktop_config.json` under
`mcpServers.homelab` with the token in its `env` block. After editing the bridge in the
repo, re-copy it. Restart Desktop fully (quit, not close-window) to pick up config
changes.

**Start with `hl_incidents` when something is broken.** Several failures here look like
something they are not — healthy containers plus "services down" is usually DNS on the
*checking* host; a whole host vanishing at once is usually hardware, not software.

Writes are impossible through this surface: the connection is opened read-only, and
`PRAGMA`/`ATTACH`/DML are refused by the engine's authorizer. Results cap at 200 rows.

## Useful queries

```sql
-- is opti's pool actually filling, or does it just feel that way?
SELECT substr(at,1,10) d, ROUND(AVG(value),1) pct FROM collector_metrics
WHERE metric='pool_used_pct' AND host='opti' GROUP BY d ORDER BY d DESC LIMIT 30;

-- what changed on rpi this week
SELECT at, kind, key, change FROM change_events
WHERE host='rpi' AND at > datetime('now','-7 day') ORDER BY at DESC;

-- which findings keep coming back
SELECT severity, COUNT(*) n, substr(message,1,70) FROM findings
WHERE run_at > date('now','-30 day') GROUP BY substr(message,1,70) ORDER BY n DESC LIMIT 10;

-- when did a container first appear
SELECT host, key, first_seen, active FROM live_state WHERE kind='container' ORDER BY first_seen DESC LIMIT 10;

-- is a drive degrading? (reallocated sectors only ever go up)
SELECT substr(at,1,10) d, metric, value FROM collector_metrics
WHERE metric LIKE 'smart%reallocated' AND host='opti' GROUP BY d, metric ORDER BY d DESC LIMIT 10;

-- what is on the LAN, newest first
SELECT hostname, ip, first_seen, active FROM net_devices ORDER BY first_seen DESC;

-- Pi-hole block rate over time
SELECT day, queries, blocked_pct FROM pihole_daily ORDER BY day DESC LIMIT 14;
```

## What gets watched automatically

Each ingest cycle writes findings you can read with `hl_status`:

| Check | Fires when |
|---|---|
| Feed freshness | a registered dataset is older than twice its cadence (critical past 6x), **or its last ingest attempt recorded `last_error`** — an erroring feed gets both findings, so a long outage escalates |
| Step crash | an ingest step raised; its writes roll back to a SAVEPOINT, its dataset gets `last_error`, and **the rest of the cycle still runs** |
| TLS expiry | a certificate is inside 30 days (critical inside 7) |
| SMART | reallocated/pending sectors are non-zero, **critical if they have grown** |
| Deploy drift | opti's `/srv/docker/compose/webapp/backend` differs from `webapp.v3.Fable/backend` (skipped only in a dirty git checkout; opti's `.git`-less CI snapshot counts as clean) |
| Bot health | a bot's status route fails (e.g. 502 = container down), its last attempt reported failure, or it has not posted in 30h |
| New device | a MAC never seen before appears in Pi-hole FTL's network table (seen in the last 24h = active) |

`hl_status.stale_datasets` lists every dataset that is past budget **or** erroring (with
`age_hours` and `last_error`); `hl_dataplane` marks the same ones `stale: true`.

### Where each live feed comes from (since the 2026-09-10 app-tier move)

| Dataset | Read from | Notes |
|---|---|---|
| `uptime-kuma` | `GET https://webapp.lan:8443/api/uptime` | Kuma itself is on noblenumbat `:3001`; the webapp on opti proxies it |
| `pihole-stats` | `GET https://webapp.lan:8443/api/pihole/summary` | rpi runs **Pi-hole v6** (session-auth `/api`); the webapp holds the login, so the ingest needs **no Pi-hole secret** |
| `bot-health` | `GET https://webapp.lan:8443/api/<bot>/status` | bots are docker-internal on opti |
| `arch-merged` | `GET https://webapp.lan:8443/api/architecture/data` | |
| `dhcp-leases` (LAN inventory) | `pihole-FTL sqlite3 -readonly /etc/pihole/pihole-FTL.db` on rpi, over SSH (hl_agents key) | **Not** `dhcp.leases` any more: the router does DHCP, that file is frozen at 2026-09-08 |
| `media-counters` | *arr APIs on noblenumbat localhost, over SSH | |

Every webapp read tries `webapp.lan` first, then opti's IP `192.168.1.11` (so a DNS outage on
rpi does not also blind the ingest). Override with `HL_WEBAPP_API` / `HL_ARCH_DATA_URL`.

Cadences are what the producer really does, not what it aims for: `collectors`/`agent-logs`
are **4h** because GitHub throttles the `*/30` cron in `homelab-agents.yml` to one run every
~3–6h (every run succeeds; the gaps are dropped schedule events). If 30-minute collectors
matter, move that schedule to a systemd timer on opti and set the cadence back.

## Operating

```bash
ssh opti 'systemctl status homelab-db homelab-db-ingest.timer'
ssh opti 'journalctl -u homelab-db -f'                       # live query log
ssh opti 'sudo systemctl start homelab-db-ingest.service'    # ingest right now
ssh opti 'sqlite3 /srv/red/opsdb/homelab.db "SELECT id, stage, last_source_at FROM datasets"'
```

Curl it directly (token from `/etc/hl-agents.env`):

```bash
curl -s -H "Authorization: Bearer $HL_DB_TOKEN" http://192.168.1.11:9100/api/status
```

## When something looks wrong

- **MCP tools missing in a session** — `HL_DB_TOKEN` is probably not exported in the shell
  that launched Claude Code; every call 401s. Check with `python3 homelab/agentic/probe.py`,
  which reports `claude_mcp` including whether the token is set and whether `:9100` answers.
- **`hl_status` looks stale** — the ingest timer runs at `*:12,42`; check
  `systemctl list-timers homelab-db-ingest.timer`. `hl_dataplane` names which feed is stale
  and how old it is; `SELECT id, last_error FROM datasets WHERE last_error IS NOT NULL`
  says why. The journal line `[ingest] {...}` carries a `step_errors` key when a step crashed.
- **A feed says "Connection refused"** — check the URL in `last_error` against the table
  above. The 2026-09-10 → 09-24 `pihole-stats`/`uptime-kuma` outage was the ingest still
  pointing at the webapp's old rpi address (`192.168.1.10:8443`).
- **Service will not start** — it refuses to run without `HL_DB_TOKEN` rather than exposing
  the database anonymously. Check `journalctl -u homelab-db -n 20`.
- **Data looks wrong, not missing** — nothing here is primary data. Delete the database and
  run `python3 ingest.py --init --backfill`; it rebuilds from the JSON reports in about a
  second.
- **Do not** hand-edit rows. Everything is derived; the next ingest overwrites. Curated
  facts belong in the repo (`build-arch-data.py`, runbooks), which is what gets ingested.
