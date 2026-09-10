---
plan: 00
title: Master plan
stage: 0
model: fable
mode: decide
depends_on: []
inputs: [DECISIONS.md, SOURCES.md, CONVENTIONS.md]
outputs: [this plan set, Unity plugin + MCP bridge installed]
done_when: [all stage plans exist as stubs, plugin installed, bridge verified from a Unity-project session]
status: done
---

# DND.vbeta: master plan

## Vision

A Unity game, not a website: an **HD-2D D&D 5e CRPG sandbox**. Pixel-art sprites (Sea of
Stars fidelity, Rain World grit) stand in a 3D-lit voxel world (Octopath's tilt-shift depth
of field and bloom, Cloudpunk's moody lighting and weather). A DM picks environments and
sprites, loads an authored campaign, and 3-5 friends join by typing a code. When no human DM
is present, the engine runs the campaign itself: it advances the story, plays the monsters,
and adjudicates every rule. It does this with **zero LLM tokens at runtime**. Claude is used
at *authoring* time to write campaigns, dialogue, and content; the game just executes data.

Everything decided so far is in [DECISIONS.md](DECISIONS.md) (D1-D21). Do not re-litigate
those in later plans; supersede them with a new dated row if something must change.
(D1-D22 as of 2026-09-09.)

## Architecture in one paragraph

Three layers, hard boundaries. **`engine/`** is a pure C# library with no Unity
dependency: the 5e rules engine (2024 first, 2014 fallback), the storybook runtime, monster
AI, and a deterministic event log. It is tested with `dotnet test` and never opens the
Editor. **`content/`** is data: ruleset-tagged rules JSON ingested from the SRD/Open5e,
homebrew, and campaign files in the storybook schema. **The Unity project**
(`E:\Unity\Projects\Dungine`, its own git repo) is presentation and netcode only: it renders the
engine's state, sends player intents to the host, and replicates the engine's event log over
Unity Relay. Netcode is host-authoritative; the host's engine instance is the truth.

## Stages and sequence (D19)

| Stage | Name | Exit criterion | Plans |
|---|---|---|---|
| 1 | POC | One voxel room, 4 pregens, one fight, hotseat, throwaway. Proves the HD-2D look and the Unity plugin workflow. | 01, 02, (04, 05, 06 first drafts) |
| 2 | Engine | Headless 5e engine passes its test suite for a level 1-5 party: checks, attacks, movement, spells, conditions, monster AI. No graphics required. | 03 (+ Rules/03a-e), 07, 08 |
| 3 | Local beta | Full game loop on one machine with two local clients over Relay: character creation, exploration, dialogue, combat, save/load, DM tools, auto-DM mode. | 09, 10, 11, 12, 13 |
| 4 | Friends test | Friends install a build, join by code, play a session. Feedback captured against a checklist. | 14, 15 |
| 5 | Ship | Complete development from feedback; final builds published. | 14, 15 |

Stage plans are stubs until their turn. Each is fleshed out in its own session with Peter,
then executed by the model named in its frontmatter (see [CONVENTIONS.md](CONVENTIONS.md)).

## Plan index

See [README.md](README.md) for the routing table (plan, stage, model, mode, status).

## Unity plugin + MCP bridge (done in the master-plan session)

The Unity integration is **a Claude Code plugin, not a Unity Hub or Editor extension**, which
is why it isn't findable from Hub. Two halves:

1. **Unity plugin for Claude Code** (`unity@unity-agent-plugin`): skills (uGUI/UI Toolkit,
   2D and tilemaps, hex tile palettes, pixel-art camera fixes, TextMeshPro, multiplayer,
   Shader Graph, render features), the Unity CLI, and Unity's MCP server entry. Installed at
   user scope with the app's bundled CLI:
   ```
   claude plugin marketplace add Unity-Technologies/unity-agent-plugin
   claude plugin install unity@unity-agent-plugin
   ```
   (In the Desktop app: Plugins, Browse, search "Unity", Install.)
   **Installed 2026-09-09** (0.1.2-beta, user scope, enabled). It ships **skills only**: no
   hooks, no MCP server.
2. **Live Editor control** comes from the **Unity CLI** plus the project's
   `com.unity.pipeline` package: `unity pipeline install`, then `unity mcp configure claude`
   writes the CLI's MCP server into the client config so the Editor's commands show up as
   tools. It needs a Unity account sign-in (`unity auth login`). The `com.unity.ai.assistant`
   package has a second, separate MCP bridge; this project does not stack both (D22).

Status of each step is tracked in [01-environment-setup.md](01-environment-setup.md).

## Open items carried into later plans

- Peter's art reference image (Plan 04).
- How the Codex/ChatGPT image agent is invoked; Codex CLI not on PATH on 2026-09-09 (Plan 05).
- Download hosting: opti web vs itch.io private (Plan 14).
- Every row in [SOURCES.md](SOURCES.md) is `pending` until Peter confirms (Plan 03a).
