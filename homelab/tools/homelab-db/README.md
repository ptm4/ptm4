# homelab-db

The homelab's queryable index of itself: collector history, host inventory, container
change history, and full-text search over every runbook — in one SQLite database on opti,
served read-only over HTTP and MCP.

```
collectors ─► agent-logs JSON ──┐
security tools ─► reports ──────┤
arch-agents :8787 ─► merged ────┤─ ingest.py (timer *:12,42) ─► /srv/red/opsdb/homelab.db
runbooks · rules · skills ──────┘                                        │
                                              server.py :9100 ───────────┘
                                                ├─ /api/*  webapp widgets + Data page
                                                └─ /mcp    Claude Code sessions
```

## Why this exists

The homelab was never short of data — five collectors, two security auditors, three
arch-agents and a shelf of runbooks. What it lacked was a way to *ask*: when did that disk
start filling, what changed on rpi last week, have we seen this symptom before. Those
questions all needed a human opening files.

This is the ETL half of the answer. It **reads** the existing outputs and never replaces
them: the collectors keep writing JSON exactly as before, the webapp still reads those
files, and everything keeps working when opti is down.

## Files

| File | What it is |
|---|---|
| `schema.sql` | The whole schema. Applied by migration 1; every statement is `IF NOT EXISTS`. |
| `db.py` | Connection discipline (WAL, `BEGIN IMMEDIATE`, `mode=ro`), migrations, untrusted-SQL hardening. |
| `ingest.py` | The ETL, the curated `DATASETS` registry, freshness checks, backup, `92-data-flows.md`. |
| `mcp_tools.py` | The nine read-only tools, shared by the JSON API and MCP. |
| `server.py` | The `:9100` daemon: `/api/*` and `/mcp`. |
| `vitals_logger.py` | 60-second host vitals, 30 days raw + hourly rollups forever. |

Units live in `homelab/hosts/opti/systemd/`: `homelab-db-ingest.{service,timer}`,
`homelab-db.service` and `homelab-db-vitals.service`. `opti-deploy.yml` installs them on
push.

## What it folds in

Everything below is read, never rewritten — the producers keep writing exactly as before:

- **Collector reports** (`agent-logs/`) and **security reports**, latest plus ~70 days of
  dated history. Numeric leaves become `collector_metrics` series automatically, which is
  how SMART reallocated-sector history came for free.
- **Merged architecture data**, giving the nightly fragments the history they never had:
  `live_state` + `change_events` answer "when did that container appear".
- **The docs corpus** — runbooks, rules, skills, generated docs — chunked by heading into
  FTS5.
- **A curated incident + decision registry** (`homelab/agentic/incidents.json`). This is
  the one thing here that is hand-written, because no collector can observe that a host
  died of a cooling fault or that a token rotation was deliberately declined.
- **Live checks each cycle**: TLS expiry, SMART degradation, deploy-target drift, Discord
  bot silence, Uptime Kuma availability, Pi-hole DHCP leases and query stats, *arr library
  and queue counters.
- Anything else JSON-shaped lands in `raw_documents`, so nothing is un-queryable.

## Three rules that are load-bearing

**1. Only opti-local processes open the database.** It sits on ZFS dataset `red/opsdb`,
deliberately *outside* the Samba-exported `red/fs`, so the CIFS mount on tux cannot even
see it. SQLite's WAL needs same-host shared memory; over CIFS that is unsupported by
design, including read-only opens. From tux or rpi, query `:9100`.

**2. Never rsync the live database.** Copying `homelab.db` together with its `-wal` is a
documented corruption path. The daily maintenance block writes a `VACUUM INTO` snapshot to
`/srv/red/fs/ptm/homelab-db/backup/homelab-snapshot.db`, integrity-checks it, and only then
publishes it — that snapshot is what the weekly coldcopy picks up.

**3. Writers take the write lock up front.** Python's driver defers `BEGIN` to the first
DML statement, so a writer that reads first has to upgrade its lock — and a failed upgrade
raises `SQLITE_BUSY_SNAPSHOT`, which `busy_timeout` does *not* retry. Every writer wraps a
cycle in `db.writing(conn)`, which issues `BEGIN IMMEDIATE`.

## Read-only means read-only

`hl_query` runs model-authored SQL, so the guarantee is layered, engine first:

1. `db.connect_ro()` opens with URI `mode=ro` — a read-only file descriptor no statement
   can talk its way around. (`PRAGMA query_only` is *not* a boundary: the SQL being run
   can turn it back off.)
2. A default-deny authorizer allows only `SELECT` / `READ` / `FUNCTION` — no `PRAGMA`, no
   `ATTACH`. This is what stops `WITH x AS (SELECT 1) DELETE FROM …`, which passes a
   naive "starts with SELECT or WITH" check.
3. `setlimit` caps attached databases (0), VDBE ops, expression depth, SQL length.
4. A progress handler aborts at 15 seconds — also what stops a runaway query from pinning
   the WAL end-mark and growing the `-wal` without bound.
5. Results cap at 200 rows / 100 KB and say `truncated: true`, because Claude Code clips
   MCP results at 25k tokens and a silently-clipped result is worse than a small one.

Every call is written to `query_audit` (through a separate connection with a fixed
statement) and to the journal. Read-only access is necessary but not sufficient: rows and
ingested docs are an injection channel into an agent, so there is a trail.

## MCP

Pinned to protocol **2025-06-18**. The 2026-07-28 revision removed the initialize
handshake and protocol-level sessions and added required per-request headers — a much
larger surface for no gain on a tools-only LAN server. Current Claude Code still runs the
initialize handshake, and the deprecation policy guarantees a 12-month runway. The server
logs the version each client requests, which is the canary for when that stops being true.

Registered in the repo-root `.mcp.json` (committed — only `.claude/` is gitignored). It
points at `192.168.1.11` rather than `opti.lan` on purpose: DNS being down is exactly when
you want to ask the homelab what is wrong. The token comes from `${HL_DB_TOKEN}` in the
environment, so no secret is in git.

## Operating it

```bash
ssh opti 'sudo systemctl status homelab-db homelab-db-ingest.timer'
ssh opti 'journalctl -u homelab-db -f'                      # every query, live
ssh opti 'sudo systemctl start homelab-db-ingest.service'   # ingest now
ssh opti 'sqlite3 /srv/red/opsdb/homelab.db "SELECT * FROM datasets"'
```

`ingest.py --check` applies the schema to an in-memory database, validates the dataset
registry and ingests a fixture — it runs in CI, so a broken migration fails on push rather
than at the next `:12`.

**Restore:** stop `homelab-db` and the ingest timer, copy
`backup/homelab-snapshot.db` over `/srv/red/opsdb/homelab.db` (removing any stale `-wal`
and `-shm`), start both. Nothing here is primary data — worst case, delete the database
and re-run `ingest.py --init --backfill`, which rebuilds it from the JSON reports in about
a second.

## Adding a data source

1. Write the ingest function in `ingest.py`, following the existing ones (idempotent
   upserts, never raise on a missing source — record it on the dataset row instead).
2. Add its row to `DATASETS`. That single entry is what makes it appear on the webapp's
   Data page, in `generated/92-data-flows.md`, in `hl_dataplane`, and in the freshness
   checks. A source without a registry row is invisible to all four.
3. `python3 ingest.py --check`.

## Deliberately not used

Considered and rejected for this scale, all documented here so the question is not
re-litigated: **Prometheus + Grafana** (hundreds of MB of RAM, and Grafana duplicates the
custom webapp), **VictoriaMetrics** (a second query language for four hosts; downsampling
is enterprise-only, so its free tier cannot do the tiered retention this does in ~50 lines
of SQL), **NetBox** (Postgres + Redis to model racks and cables this lab does not have),
**Netdata** (SD-card-hostile on the rpi), **the official MCP Python SDK** (a pydantic +
uvicorn venv for a ~500-line problem, against the stdlib-only house rule), and the
**archived official SQLite MCP server** (unmaintained since 2025-05).

Escape hatches if the constraints change, all still free and single-binary:
VictoriaMetrics if cardinality ever explodes, Litestream if this becomes primary data,
DuckDB for ad-hoc analytics over the JSON tree, the official SDK if the protocol outruns
the hand-rolled server.
