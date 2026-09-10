# Migration and rollback

The source copy was made from `E:\REPO\ptm4\homelab\hosts\rpi\webapp.v2.legacy`. `source-manifest.json` records all 163 copied files and SHA-256 hashes. Dependencies, build outputs, secrets and runtime data were excluded. Fable owns the original rename and its own sibling implementation. The only shared file edited by this implementation is the append-only `E:\REPO\ptm4\AgentComms.md`.

## Page coverage

| Workflow | Local route | Status |
|---|---|---|
| Fleet / widgets | `/`, `/workspace` | New dense monitor, preserved configurable board engine |
| Hosts | `/cockpit`, `/infrastructure/hosts/:id` | Existing deep controls, expanded telemetry and drill-down links; demo actions |
| Containers | `/containers` | Search, host filters, images, ports, actions; cached monitoring, Dozzle linked |
| DNS / network | `/pihole` | Traffic, blocking, top domains; simulated pause/allow |
| History | `/trends` | Resource/range charts; independent persisted view |
| Findings / maintenance | `/operations` | Filtering, saved views, local acknowledgements, detail panels |
| Updates | `/updates` | Images and package/security backlog |
| Reports / backups | `/reports`, `/security`, `/logs` | Latest evidence, history, log tails and simulated controls |
| Streams | `/streams` | New responsive player, slots, quality/buffer, channels, VRS match guide |
| Links | `/links` | New editable/searchable/grouped Launchpad |
| Media/weather/prices | `/personal` | Preserved integration widgets and service links |
| Bots | `/bots` | Existing detailed editors; local simulated config/send; live writes blocked |
| CS2 analysis | `/leetify` | Dimensions, maps, coaching, parsed demo/round details |
| LLM | `/llm` | Status/model/runbook read views; commands linked to live tool |
| Database | `/data`, `/query`, `/workspace?tab=data` | Pipeline, schema, prepared queries, allowlisted data exploration; SQL execution blocked |
| Samba | `/samba` | Storage/status/config/backups read view; live editor/rollback linked |
| Architecture / agents | `/tools`, `/architecture`, `/agents`, `/agentic` | New service-placement map and labeled specialist links; full specialist migrations deferred |
| Notes | `/notes` | Labeled link to existing Notes application |

## Before any live deployment

- [ ] Choose a separate host/vhost and persistent directory; review Fable’s current ownership log.
- [ ] Validate real response contracts and freshness over the VPN, including unavailable phone/host cases.
- [ ] Test actual HLS on iOS Safari and Android, station idle policy, authentication and TLS. The local build cannot manage live slot keepalive by design.
- [ ] Review any proposed operational write support separately, preserve existing typed confirmations, ZFS reboot guard, service allowlists and timeouts.
- [ ] Review bot secrets, query authorization, LLM endpoints and CSP before exposing beyond loopback.
- [ ] Decide which specialist pages to migrate fully; currently no shared nginx, CI, deployment or collector configuration was changed.
- [ ] Back up `.runtime` locally before migrating personalization. Never overwrite v2/Fable settings or acknowledgements.

## Rollback

Run `Stop-Preview.ps1` to stop only this directory’s verified processes. Open the existing site at `https://webapp.rpi.lan:8443/`. No production route was changed, so no deployment rollback is necessary. All original source and standalone specialist assets are preserved in the copied tree; the legacy source remains in its sibling directory. Keep `.runtime` if you want to resume these boards/settings later. No commit or push was made.

## Stream source provenance

- Match data and rankings: existing `/api/hltv/day` and `/api/hltv/vrs`, backed by [HLTV matches](https://www.hltv.org/matches). Rankings are VRS, not HLTV’s separate ranking system.
- [BLAST broadcast information](https://blast.tv/article/where-to-watch) identifies BLASTPremier on Twitch and YouTube.
- [ESL Pro League listing](https://blast.tv/cs/tournaments/esl-pro-league-season-23-2026) links ESL CS broadcasts. The directory labels ESL TV as ESL CS (`eslcs`); it does not assume `esltv` is the current CS channel handle.
- The demo channel directory is an isolated copy of Fable’s released 21-channel `stream-station/presets.json`. It is not a claim that every channel is live or carrying the selected event. Live monitoring reads the upstream station presets.
