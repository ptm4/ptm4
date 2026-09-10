# Decisions log

Append-only. One row per decision. Supersede by adding a new row that references the old
one, never by editing history. Dates are absolute.

| # | Date | Area | Decision |
|---|---|---|---|
| D1 | 2026-09-09 | Presentation | 2.5D isometric, realised as **HD-2D**: pixel-art billboard sprites in a 3D-lit voxel world. |
| D2 | 2026-09-09 | Spine | **CRPG-style** (engine runs NPCs/encounters/dialogue), self-sufficient at runtime. |
| D3 | 2026-09-09 | Token policy | LLM tokens spent at **authoring time only** (Claude Max). Runtime = data files + local engine. Optional local-LLM improv (host GPU, llama.cpp/LLamaSharp, Vulkan backend, CPU fallback, small GGUF). Optional Claude-backed DM switch, never required. |
| D4 | 2026-09-09 | Table | 1 human DM + 3-5 remote players; DM not always present, so auto-DM must run a session. |
| D5 | 2026-09-09 | Content | Peter pre-authors whole campaigns (original, or adaptations for private use). Only SRD ships in builds; adapted copyrighted modules stay in gitignored `content/private/`. |
| D6 | 2026-09-09 | Art refs | Octopath Traveler + Rain World + Sea of Stars; Cloudpunk lighting/mood as stretch. Peter to supply a reference image for the style bible (Plan 04). |
| D7 | 2026-09-09 | World kit | Voxel modular kit (MagicaVoxel to Unity), grid-snapped; procedural voxel gen from palettes optional. |
| D8 | 2026-09-09 | Sprites | Sea of Stars scale (~64-96 px tall); generate large, downscale + palette-quantize via cleanup script. Portrait + billboard; layered paper-doll (body/armor/weapon). Monsters as sprites (assumed, not tokens). |
| D9 | 2026-09-09 | Animation v1 | idle/walk/attack/hit/death, 4 facings, ~20-30 frames per creature from one sheet template. |
| D10 | 2026-09-09 | Time model | **100% turn-based**, exploration included. |
| D11 | 2026-09-09 | Roleplay | Authored dialogue trees + skill checks; voice in Discord with engine enforcing rules; local-LLM improv; optional Claude switch. |
| D12 | 2026-09-09 | Auto-DM scope | Run storybook; tactical monster AI; full rules adjudication; procedural side content. |
| D13 | 2026-09-09 | Player view | Own PC, own camera, shared world, per-player fog of war; DM sees/moves all. |
| D14 | 2026-09-09 | Edition | **2024 rules (SRD 5.2) first**, 2014 (SRD 5.1) layered in where 2024 data/spec can't be met. Every rules entry tagged with ruleset. |
| D15 | 2026-09-09 | Sources | SRD 5.1 + 5.2 (CC-BY-4.0), Open5e API + 5e-database (SRD-derived), homebrew format. **Excluded:** 5e.tools or any non-SRD data in repo/builds. |
| D16 | 2026-09-09 | Networking | Netcode for GameObjects over Unity Relay + Lobby, join codes, host-authoritative. |
| D17 | 2026-09-09 | Delivery | Windows x64 + macOS + Linux standalone. Download hosting (opti web vs itch.io private) **undecided**. |
| D18 | 2026-09-09 | Image gen | Codex CLI / ChatGPT app agent-driven; Claude writes prompt packs, sheet templates, cleanup pipeline. (Codex CLI not on PATH on 2026-09-09; open item.) |
| D19 | 2026-09-09 | Sequence | POC slice, then headless rules engine, then local beta, then friends test over Relay, then complete & ship. |
| D20 | 2026-09-09 | Tooling | Unity 6000.6.0f1 (Hub), URP, C#; dotnet 8 SDK present for the headless engine; official Unity plugin for Claude Code + Unity MCP bridge (`com.unity.ai.assistant`). |
| D21 | 2026-09-09 | Layout | Plans + engine + content + tools live in `homelab/DND.vbeta` (this repo). Unity project lives at `E:\Unity\Projects\DND` in its own git repo and consumes `engine/` as a local UPM package. |
| D22 | 2026-09-09 | Editor control | Live Editor control goes through the **Unity CLI + `com.unity.pipeline`** route (`unity mcp configure claude`), which is what the installed plugin's skills assume. The `com.unity.ai.assistant` MCP bridge is the documented fallback only; never run both (Modding.md rule 8). |
| D23 | 2026-09-09 | Layout | Supersedes the path in D21: Peter created the Unity project as **`E:\Unity\Projects\Dungine`** (URP-blank template 17.x, Unity 6000.6.0f1, git initialized, Unity Cloud project linked). All plans use that path. `com.unity.pipeline` 0.6.0-exp.1 and `com.unity.ai.assistant` 2.19.0-pre.2 are both installed by the template; only the Pipeline route is registered with Claude Code (`unity-editor-mcp`, user scope), per D22. |
| D24 | 2026-09-09 | Delivery | Resolves the open half of D17: **no hosting infrastructure in v1.** Peter hands friends the build (exe/zip) himself. Plan 14 keeps builds + versioning + install notes; drops the download page and update check. |
| D25 | 2026-09-09 | Image gen | Refines D18: **Peter runs the Codex/ChatGPT image agent himself.** Claude's job is to produce hand-off plans (Plan 05/06 prompt packs, templates, inbox layout) that Peter gives to Codex. Claude never invokes Codex. |
| D26 | 2026-09-09 | Engine wiring | `engine/DND.Engine/` is the UPM package root (package.json + asmdef + Runtime/*.cs) referenced from Dungine's manifest as a `file:` local package, not a junction. The same sources build headless via `DND.Engine.csproj`; bin/obj are redirected to `engine/.build/` so Unity never imports DLLs. C# 9 / netstandard2.1 / no UnityEngine. |
| D27 | 2026-09-09 | Art numbers | From `docs/style-bible.md` v0.1: palette **Dungine-54** (`tools/palette.py` is the source; outline ink `#0b0a12`); **PPU 64**; Medium/Small cell **64x96** (body box 40x72, feet 4 px above bottom), Large 128x128; **3 generated facings (S, N, E), W mirrored**; 20 frames per facing (idle 4, walk 6, attack 4, hit 2, death 4); Medium sheet 1280x288; voxels **16 per tile**, walls 32; camera perspective FOV 28° pitch 38°; palette *modes* are lighting profiles (Day / Night), not separate palettes. Numbers marked "open for review" in the bible may move after the POC. |
| D28 | 2026-09-09 | Camera | POC finding supersedes the 38° in D27: **pitch 50°, distance ~11 u, FOV 28°**, and the game must cut away / dither walls between camera and party. Lighting baseline for night scenes: ambient `night_purple_3`, moon 1.6, torch point lights 40 / range 9, post exposure +0.6, DoF band starting beyond the subject distance. |
| D29 | 2026-09-09 | Sprite pipeline | Codex's image tool cannot emit alpha and outputs a fixed ~1774x887. The pipeline keys painted checkerboard/white backgrounds and accepts any slot size (`sprite_clean` 0.2.0); prompts ask for a flat white background; a turnaround alone builds a placeholder sheet. First real asset: `goblin` (turnaround, approved by the pipeline, awaiting Peter's eye). |
