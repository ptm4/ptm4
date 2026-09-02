# Homelab data flows

> ⚙️ **AUTO-GENERATED — do not hand-edit.** Rewritten by `homelab/tools/homelab-db/ingest.py` from the `datasets` registry in that file (the curated description of the data plane) joined with live ingest state.
> Generated: `2026-09-02T01:42:55+00:00`

Every fact the homelab collects flows producer → store → `homelab.db` → consumer. Query any of it with the `homelab` MCP tools (`hl_status`, `hl_query`, `hl_search_docs`), or read it on the webapp's Data page.

## Producers — what generates facts

| Dataset | Host | Source | Cadence | Freshness | Consumers |
|---|---|---|---|---|---|
| **hl-arch-agent fleet** | opti, rpi, noblenumbat | `:8787 (push at 00:00 local)` | 24.0h | 22h ago | arch fragments, vitals |
| **Discord bot post freshness** | rpi | `GET /api/<bot>/status (via webapp)` | 0.5h | 0m ago | findings |
| **Homelab collectors** | opti | `GitHub Actions homelab-agents.yml` | 0.5h | 1h ago | agent-logs |
| **Deployed-copy drift** | opti | `hash of /srv/docker/compose/webapp vs repo` | 0.5h | 0m ago | findings |
| **Incident & decision registry** | git | `homelab/agentic/incidents.json` | on demand | 0m ago | hl_incidents, Claude sessions |
| **Curated repo facts** | git | `homelab/{agentic,tools/architecture}` | on demand | 1h ago | docs, arch graph |
| **Security auditors** | opti | `GitHub Actions homelab-agents.yml` | 24.0h | 12h ago | security-reports |

- **hl-arch-agent fleet** — Pushes a full host fragment to the webapp; also serves /vitals counters and the control POSTs.
- **Discord bot post freshness** — A dead daily bot is silent, and silence looks exactly like a quiet day.
- **Homelab collectors** — doctor + network every 30min; hardware + software daily 09:00 UTC. SSH fan-out via hl_agents key.
- **Deployed-copy drift** — A direct edit to a deploy target is reverted by the next CI run — this makes that silent loss loud.
- **Incident & decision registry** — Why a host went down and which choices are settled — the judgment no collector can observe.
- **Curated repo facts** — Runbooks, rules, skills, and the 68-node architecture graph. CI validates referential integrity.
- **Security auditors** — journald-hunter + persistence-auditor, daily 09:00 UTC, local to opti (no fan-out).

## Stores — where they land

| Dataset | Host | Source | Cadence | Freshness | Consumers |
|---|---|---|---|---|---|
| **agent-logs reports** | opti | `<agent-logs>/*-latest.json + dated dirs` | 0.5h | 1h ago | webapp, session hook, homelab-db |
| **Merged architecture data** | rpi | `GET /api/architecture/data` | 24.0h | 0m ago | gen-agentic-docs, homelab-db |
| **LAN device inventory** | rpi | `pihole:/etc/pihole/dhcp.leases (over SSH)` | 0.5h | 0m ago | net_devices, change_events |
| **Docs corpus** | git | `runbooks, rules, skills, generated docs` | on demand | 1h ago | Claude sessions, homelab-db FTS |
| **Leetify CS2 stats** | opti | `<agent-logs>/leetify-latest.json` | on demand | 83d ago | cs2_matches, cs2_ratings |
| **Media library counters** | noblenumbat | `localhost *arr APIs (queried over SSH)` | 0.5h | 0m ago | media_counters |
| **Pi-hole query stats** | rpi | `GET /api/pihole/summary (via webapp)` | 0.5h | 0m ago | pihole_daily |
| **PC-part price watch** | opti | `<agent-logs>/pricewatch-latest.json` | 6.0h | 2h ago | price_history, findings, webapp widget |
| **security-reports** | opti | `<security-reports>/*-latest.json` | 24.0h | 12h ago | webapp, homelab-db |
| **Uptime Kuma monitors** | rpi | `GET /api/uptime (via webapp)` | 0.5h | 0m ago | monitor_history |

- **agent-logs reports** — Atomic tmp+fsync+rename. Still the transport; the DB indexes it rather than replacing it.
- **Merged architecture data** — Curated graph ⊕ per-host fragments. Fragments overwrite in place and keep no history — which is exactly the gap live_state/change_events fills.
- **LAN device inventory** — Pi-hole is the only DHCP server on this LAN, so its leases are the whole picture. A device never seen before becomes a change event.
- **Leetify CS2 stats** — Manual runs only (paid API). Broken out of the 135KB blob into columns so trends are queryable.
- **Media library counters** — The query runs on noblenumbat so each API key is read from its own config.xml and used against localhost — no key is copied to opti.
- **PC-part price watch** — Newegg/eBay/Amazon prices for the opti hypervisor rebuild (2026-08). Items + buy targets in pricewatch/items.json; a price at/below target raises a warn finding.
- **Uptime Kuma monitors** — Kuma's own history is behind an admin login; sampling the read-only /metrics view is what makes availability queryable.

## The database

| Dataset | Host | Source | Cadence | Freshness | Consumers |
|---|---|---|---|---|---|
| **homelab.db** | opti | `/srv/red/opsdb/homelab.db` | 0.5h | 0m ago | MCP tools, webapp widgets, Data page |

- **homelab.db** — WAL. opti-local processes only — never opened over the CIFS mount. Backed up by VACUUM INTO snapshot so the weekly coldcopy never rsyncs a live WAL pair.

## Consumers — what reads them back

| Dataset | Host | Source | Cadence | Freshness | Consumers |
|---|---|---|---|---|---|
| **92-data-flows.md** | opti | `homelab/agentic/generated/92-data-flows.md` | 24.0h | 21h ago | Claude sessions |
| **MCP + JSON API** | opti | `:9100 (/api, /mcp)` | on demand | 12h ago | Claude Code, webapp |
| **Webapp widgets + Data page** | rpi | `GET /api/hldb/*` | on demand | never | browser |

- **92-data-flows.md** — So a future session can read the data plane instead of re-deriving it.
- **MCP + JSON API** — Read-only. Bearer token + Host/Origin validation. MCP pinned to spec 2025-06-18.

## What is in the database right now

| Table | Rows |
|---|---|
| `agent_runs` | 382 |
| `findings` | 931 |
| `collector_metrics` | 22,432 |
| `docs` | 208 |
| `change_events` | 110 |
| `arch_nodes` | 70 |
| `raw_documents` | 5 |
| `vitals_samples` | 46,952 |

History reaches back to **2026-06-07**.
