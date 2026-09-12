# Plan index

Routing table for every plan. `model`/`mode` follow [CONVENTIONS.md](CONVENTIONS.md).
Keep `status` here in sync with each file's frontmatter.

| Plan | Title | Stage | Model | Mode | Depends on | Status |
|---|---|---|---|---|---|---|
| [00](00-MASTER.md) | Master plan | 0 | fable | decide | | done (awaiting Peter's review) |
| [01](01-environment-setup.md) | Environment setup (Unity project, plugin, MCP, engine solution) | 1 | sonnet | execute | 00 | in-progress (all agent steps done; Peter: fresh-session MCP check + UGS Relay/Lobby) |
| [02](02-poc-vertical-slice.md) | POC vertical slice (throwaway) | 1 | fable | decide | 01 | in-progress (two review rounds addressed 2026-09-11: ranged, highlights, camera, grounding, pathing, wall cutaway, portrait HUD; re-test pending) |
| [03](03-rules-engine.md) | Rules engine (headless) | 2 | fable | decide | 01 | in-progress (skeleton + 31 tests; architecture doc written; objects + Interact action (S3, 2026-09-11)) |
| [03a](Rules/03a-data-ingest.md) | SRD / Open5e data ingest | 2 | sonnet | execute | 03 | done (2026-09-12: all 9 kinds, both rulesets, 1553 records, validated + idempotent; 2024 spells via Open5e through a curl transport fallback) |
| [03b](Rules/03b-core-mechanics.md) | Core mechanics | 2 | sonnet | execute | 03, 03a | stub |
| [03c](Rules/03c-spells-and-effects.md) | Spells and effects | 2 | fable | decide | 03b | stub |
| [03d](Rules/03d-conditions-and-status.md) | Conditions and status | 2 | sonnet | execute | 03b | stub |
| [03e](Rules/03e-character-model-2024.md) | 2024 character model | 2 | fable | decide | 03a, 03b | stub |
| [04](04-art-style-bible.md) | Art style bible | 1 | fable | decide | 00 | drafted (v0.1; Peter review + POC check pending) |
| [05](05-sprite-pipeline.md) | Sprite pipeline | 1 | codex-image + sonnet | execute | 04 | done-pending-review (24 creatures verified + installed 2026-09-11; Peter's in-scene look approval outstanding) |
| [06](06-voxel-world-kit.md) | Voxel world kit | 1 | codex (vox files) + fable (importer) | execute | 04 | in-progress (35 dungeon tiles delivered + imported; POC rebuilt on the kit; Peter's look review pending) |
| [07](07-campaign-format-storybook.md) | Campaign format (storybook schema) | 2 | fable | decide | 03 | stub |
| [08](08-auto-dm-engine.md) | Auto-DM engine | 2 | fable | decide | 03, 07 | stub |
| [09](09-local-llm-improv.md) | Local LLM improv (optional layer) | 3 | fable | decide | 07, 08 | stub |
| [10](10-networking-relay.md) | Networking (NGO + Relay + Lobby) | 3 | sonnet | execute | 03, 02 | stub |
| [11](11-ui-ux.md) | UI / UX | 3 | fable then sonnet | decide | 03e, 04 | stub |
| [12](12-dm-tools-map-editor.md) | DM tools and map editor | 3 | sonnet | execute | 06, 07 | stub |
| [13](13-first-campaign-content.md) | First campaign content | 3 | fable + peter | decide | 07, 08 | stub |
| [14](14-build-and-distribution.md) | Build and distribution | 4 | sonnet | execute | 10 | stub |
| [15](15-beta-test-playbook.md) | Beta test playbook | 4 | peter | n/a | 14 | stub |
| [16](16-sonnet-batch-01.md) | Work split + Sonnet execution batch 01 (bridge lock/doctor, HUD fix, engine objects + Interact, SRD ingest) | 2 | sonnet | execute | 02, 03, 06 | done except S2 verification (2026-09-12: S1/S3/S4 verified, Fable reviewed and fixed layering + ingest nits; S2 HUD fix awaits an open Editor) |
| [17](17-sonnet-batch-02.md) | Sonnet execution batch 02 (engine JSON reader + compendium loader, 03b core mechanics first half, 03d conditions) | 2 | sonnet | execute | 16, 03a | approved (written by Fable 2026-09-12; hand to Sonnet) |

Reference files: [DECISIONS.md](DECISIONS.md), [SOURCES.md](SOURCES.md),
[CONVENTIONS.md](CONVENTIONS.md), [AGENT-COLLABORATION-PROPOSAL.md](AGENT-COLLABORATION-PROPOSAL.md)
(the Astra-Fable bridge; implemented, disabled until activated; runbook `homelab/agentic/runbooks/11-dungine-agent-collaboration.md`).
