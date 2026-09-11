# Rules & asset sources

Nothing enters `content/` or a build until its row says `confirmed: yes`. Peter confirmed
the rules-data rows on 2026-09-09; asset fallbacks stay pending until first used. Licenses below are as understood on 2026-09-09 and must be re-checked at ingest
(Plan 03a records the exact license text and version it pulled).

## Rules data

| Source | What | License (verify at ingest) | Ships in build? | Confirmed |
|---|---|---|---|---|
| SRD 5.2 (Wizards of the Coast, 2025) | 2024-rules System Reference Document: species, backgrounds, classes, spells, monsters, items | CC-BY-4.0 (attribution text required in-game) | Yes | yes (Peter, 2026-09-09) |
| SRD 5.1 (Wizards of the Coast, 2023 CC re-release) | 2014-rules SRD; fallback where 5.2 lacks data or the 2024 spec can't be met | CC-BY-4.0 | Yes | yes (Peter, 2026-09-09) |
| Open5e API (open5e.com) | SRD content as JSON via REST. Also carries third-party OGL/ORC documents; **ingest the SRD documents only** | Per document; SRD parts CC-BY-4.0 | Yes (SRD documents only) | yes (Peter, 2026-09-09) |
| 5e-database (github.com/5e-bits/5e-database) | SRD 5.1 as JSON dumps, well-structured for monsters/spells/classes | MIT (code) + SRD terms (data); verify | Yes | yes (Peter, 2026-09-09) |
| Homebrew (Peter) | Own classes, monsters, items in the engine's homebrew format | Peter's | Yes | yes (Peter, 2026-09-09) |

## Reference only (read to understand rules; never ingested, never quoted into content/)

| Source | Use | Why not ingested |
|---|---|---|
| dnd5e.wikidot.com (2014 rules) and dnd2024.wikidot.com (2024 rules) | Peter's chosen reference for character-sheet structure, class features, spell text, and rule interpretation while designing Plans 03/03e/11. Cross-check implementations against it. | Fan transcription of the full published books, including non-SRD material; not licensed for redistribution. SRD-covered facts it shows are the same facts the confirmed sources carry. Added 2026-09-11 (Peter). |

## Explicitly excluded

| Source | Why |
|---|---|
| 5e.tools and any non-SRD WotC text | Copyrighted, not licensed for redistribution. Never in the repo or a build. Private-table use only, and only in gitignored `content/private/`. |
| Published modules (e.g. Descent into Avernus) | Same. An adapted campaign file may exist in `content/private/` for the home table only. |

## Asset fallbacks (used only where generation can't deliver)

| Source | What | License | Confirmed |
|---|---|---|---|
| MagicaVoxel | Voxel authoring tool (free) | Freeware | pending |
| Kenney.nl | CC0 3D/2D packs | CC0 | pending |
| Quaternius | Low-poly packs | CC0 | pending |
| OpenGameArt (CC0 filter only) | Misc 2D | CC0 only | pending |

## Tooling (not content, listed for completeness)

| Tool | Role | Notes |
|---|---|---|
| Unity 6000.6.0f1 + URP | Engine | Installed in Hub. |
| Unity plugin for Claude Code (`unity@unity-agent-plugin`) | Skills + CLI + MCP server | Install via Claude Code plugin marketplace. |
| `com.unity.ai.assistant` | Unity MCP bridge (Editor control) | Requires Unity account sign-in and accepting Unity AI terms. |
| llama.cpp / LLamaSharp | Optional local-LLM improv on the host GPU | Plan 09 decides which. |
