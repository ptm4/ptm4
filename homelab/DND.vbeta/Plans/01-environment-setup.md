---
plan: 01
title: Environment setup
stage: 1
model: sonnet
mode: execute
depends_on: [00]
inputs: [Unity 6000.6.0f1 in Hub, dotnet 8 SDK, Unity plugin for Claude Code (done), Unity CLI 1.0.0-beta.6 (done), Dungine project (done)]
outputs: [E:\Unity\Projects\Dungine with packages, Pipeline + MCP registered with Claude Code, engine/ .NET solution junctioned into Packages/, UGS Relay + Lobby enabled, HD-2D post baseline]
done_when: [unity status reports Dungine ready (done), Unity MCP tools respond from a fresh Claude Code session, dotnet test passes on an empty suite, Editor compiles with the engine package, Relay + Lobby SDKs resolve]
status: in-progress
---

# 01: Environment setup

## Goal
A working Unity 6 URP project that Claude Code can drive live through the Unity CLI's MCP
server, plus the headless `engine/` solution wired in as a local package. Nothing
game-specific yet.

## How Editor control actually works (verified 2026-09-09)
The installed plugin (`unity@unity-agent-plugin` 0.1.2-beta) **ships skills only, no MCP
server**. Live Editor control in the plugin's own model is:

1. the **Unity CLI** (`unity` 1.0.0-beta.6 at `%LOCALAPPDATA%\Unity\bin\unity.exe`), signed
   in as Peter (Unity Personal license active);
2. the project's **`com.unity.pipeline`** package (0.6.0-exp.1, already in Dungine), which
   serves an HTTP API on a local port while the Editor runs (`unity status` → `ready`,
   `unity command` lists the exposed commands, `unity command eval '<C#>'` runs code);
3. the CLI's **`unity mcp`** stdio server, registered with Claude Code at user scope as
   `unity-editor-mcp` (absolute path to `unity.exe`, because `unity` is not on the PATH of
   shells the Desktop app spawned before the CLI was installed). The Editor's commands appear
   as MCP tools in any fresh Claude Code session.

`com.unity.ai.assistant` (2.19.0-pre.2) is also in the project from the template. It carries
a second MCP bridge (Edit > Project Settings > AI > Unity MCP). **Leave it unregistered** so
the two do not stack (D22); the package itself can stay for the in-Editor assistant.

## Checklist (status as of 2026-09-09)

| Step | Who | Status |
|---|---|---|
| Install Unity plugin for Claude Code (`unity@unity-agent-plugin`, user scope) via the app's bundled CLI `%APPDATA%\Claude\claude-code\<ver>\claude.exe` | agent | **done** (0.1.2-beta, enabled) |
| Install Unity CLI, sign in, license | Peter | **done** (1.0.0-beta.6, OAuth, Unity Personal) |
| Create the project | Peter | **done**: `E:\Unity\Projects\Dungine`, URP-blank template, Unity Cloud project linked, `.git` present |
| `com.unity.pipeline` installed and reachable | template | **done** (0.6.0-exp.1, port 7802, state ready) |
| Register the CLI's MCP server with Claude Code: `claude mcp add --scope user --transport stdio unity-editor-mcp -- <abs path>\unity.exe mcp` | agent | **done**, `claude mcp get unity-editor-mcp` → Connected |
| `unity skill install claude-code --local` inside Dungine | agent | **done**: `E:\Unity\Projects\Dungine\.claude\skills\unity-cli` |
| Prove the MCP server answers: stdio probe (`initialize` + `tools/list`) against `unity.exe mcp` with the Editor open | agent | **done**: server `unity-mcp 1.0.0-beta.6`, **149 tools** (create_scene, create_gameobject(s), create_prefab, add_component, attach_script, create_asset, capture_game_view/scene_view, console, build, run tests, bake lighting/navmesh, batch, ...) |
| Verify from a **fresh** Claude Code session opened in `E:\Unity\Projects\Dungine`: `unity-editor-mcp` tools listed and `/unity:` skills in the slash menu; run one read-only tool (e.g. `console` or a hierarchy read) | agent | pending (needs a new session) |
| Unity `.gitignore` in Dungine | template | **done** (github/gitignore Unity template, synced 2026-07-02) |
| Add packages `com.unity.netcode.gameobjects` 2.13.2, `com.unity.services.relay` 1.2.0, `com.unity.services.lobby` 1.3.0, `com.unity.2d.sprite` 1.0.0 (pulled in transport 6.6.0, services core/auth/qos/wire) | agent | **done** via manifest edit + Editor relaunch; `package_list` confirms |
| `engine/`: `DND.Engine.sln`, `DND.Engine` (netstandard2.1, C# 9, nullable), `DND.Engine.Tests` (xUnit, net8.0), `Directory.Build.props` redirecting bin/obj to `engine/.build/`, `package.json` + `DND.Engine.asmdef` (`noEngineReferences`), placeholder `EngineInfo` + 2 tests | agent | **done**: `dotnet test` → 2 passed |
| Wire engine into Dungine as a **`file:` local package** (`com.ptm.dnd.engine` → `file:E:/REPO/ptm4/homelab/DND.vbeta/engine/DND.Engine`), replacing the junction idea (D26) | agent | **done**: Editor loads `DND.Engine v0.1.0`, 0 UnityEngine refs, 0 compile errors |
| Unity Gaming Services: enable Relay + Lobby on the linked cloud project (free tier) | Peter | pending (dashboard.unity3d.com → project → Multiplayer → Relay / Lobby → Get started) |
| HD-2D post baseline: `Assets/Dungine/Rendering/HD2D_Base.asset` (Bloom 0.9/thr 1.1/scatter 0.65, Gaussian DoF 12→40, ACES, contrast +12/sat +6/exposure +0.1, Vignette 0.28, FilmGrain Thin1 0.25) created by `Dungine.EditorTools.HD2DSetup` (menu **Dungine > Create HD-2D Base Profile**) | agent | **done**; Plan 04 retunes the numbers |
| Pixel-art import: `Assets/Dungine/Editor/PixelSpriteImportPostprocessor.cs` applies Point filter, uncompressed, no mips, bottom-center pivot, FullRect, **PPU 64 placeholder** to first imports under `Assets/Dungine/Sprites/` | agent | **done**; Plan 04 sets the real PPU |
| Assign `HD2D_Base` to a scene Volume and enable post-processing on the camera | Plan 02 | deferred (scene work belongs to the POC) |

## Notes
- The plugin is a Claude Code plugin, not a Hub extension. `claude` is not on PATH; the
  Desktop app's bundled CLI is at `%APPDATA%\Claude\claude-code\<version>\claude.exe`.
- `unity mcp configure claude` targets Claude *Desktop chat* config, not the Code tab; the
  Code tab reads Claude Code's own user config, which is why `claude mcp add` was used.
- If the Editor boots into Safe Mode (compile errors), the Pipeline package does not load and
  `unity status` cannot connect: fix the errors first, do not hand-edit scene files blind.
- Keep Dungine's git separate from `ptm4`. Peter commits both.

## Gotchas learned 2026-09-09 (read before driving the Editor)
- **`package_add` kills its own reply.** Adding a package triggers a domain reload; the
  Pipeline server stops mid-response ("Dispatcher is shutting down") and follow-up commands
  see "No Pipeline instance". Safe pattern: edit `Packages/manifest.json` (ideally with the
  Editor closed), then open/focus the Editor and poll `unity status` until `ready`. If the
  Editor must stay open, add one package, then poll status to `ready` before the next.
- **`Get-Process Unity` matches the CLI too.** The Unity CLI binary is `unity.exe`, and every
  Claude Code session spawns `unity.exe mcp`. To detect the *Editor*, filter processes whose
  command line contains `Hub\Editor`. This false positive made a session believe the Editor
  was open when it had been closed.
- **`unity open` blocks** for the whole Editor start (minutes on first import). Run it with a
  long timeout or in the background; the Editor keeps running after the CLI call ends.
- Version pins used: `com.unity.netcode.gameobjects` 2.13.2, `com.unity.services.relay`
  1.2.0, `com.unity.services.lobby` 1.3.0, `com.unity.2d.sprite` 1.0.0 (from
  packages.unity.com dist-tags on 2026-09-09). Manifest backup: `manifest.json.bak-2026-09-09`.
- NuGet: this machine had **no package sources**; `nuget.org` was added to the user config
  so `dotnet test` can restore xunit.

## What remains (2026-09-09 end of session)
1. **Peter:** open a fresh Claude Code session in `E:\Unity\Projects\Dungine` and confirm the
   `unity-editor-mcp` tools and `/unity:` skills appear. Then mark this plan `done`.
2. **Peter:** enable Relay + Lobby on the Unity Cloud project (needed by Plan 10, not before).

## Open questions
- Does the Code tab list `unity-editor-mcp` tools in a fresh session? First thing to check.
- Whether `com.unity.ai.assistant` should be removed from Dungine to save Editor startup time
  (only if it is never used in-Editor).
