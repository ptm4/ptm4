# DND.Engine architecture (Plan 03, v0.1, 2026-09-09)

Pure C# (netstandard2.1, C# 9, no UnityEngine, no System.Text.Json) in `engine/DND.Engine/`.
The same sources compile in Unity (UPM package `com.ptm.dnd.engine`) and headless
(`dotnet test`). Everything below is designed so the runtime needs no LLM (D3) and so a
networked client can replay the host's decisions byte-for-byte (D16).

## 1. Three invariants

1. **Deterministic.** All randomness comes from `IRng` seeded per encounter. Same seed +
   same intents = same events. Tests assert this by replaying.
2. **Intent in, events out.** The presentation layer never mutates rules state. It submits
   an `Intent` (move, attack, cast, end turn); the engine validates it against the rules and
   either appends `GameEvent`s to the `EventLog` or returns a `Rejection` with the rule
   that refused it. The event log *is* the network protocol and the save file.
3. **Data-driven.** Creatures, spells, items and conditions are data (`content/rules`,
   Plan 03a) tagged `ruleset: 2024 | 2014` (D14). Engine code implements mechanics; it never
   hard-codes a monster.

## 2. Layers (namespaces)

| Namespace | Owns | Depends on |
|---|---|---|
| `DND.Engine.Core` | `IRng`/`SeededRng`, `Dice`, `Ability`, `GridPos`, `Distance` | nothing |
| `DND.Engine.Model` | `Creature` (live stat block + position + conditions), `Condition` | Core |
| `DND.Engine.Rules` | `D20Test` (checks, saves, attacks, advantage), `Damage`, movement rules, cover/LoS (later 03b) | Core, Model |
| `DND.Engine.Events` | `GameEvent` hierarchy, `EventLog` | Model |
| `DND.Engine.Intents` | `Intent` hierarchy, `RuleResult` | Model |
| `DND.Engine.Combat` | `Encounter`: initiative, turn structure, action economy, intent handling | all above |
| `DND.Engine.Story` (Plan 08) | storybook runtime, triggers, flags | Combat |
| `DND.Engine.Ai` (Plan 08) | tactical monster AI proposing intents | Combat |

Rule of thumb: a namespace may reference only the rows above it.

## 3. Turn structure (v0.1 subset, 2024 rules)

- `Encounter.Start()` rolls initiative (d20 + Dex mod; ties by Dex score, then stable
  order) and emits `InitiativeRolled` + `RoundStarted` + `TurnStarted`.
- A turn has a **movement budget** (speed in ft), one **action**, one **bonus action**, one
  **reaction** (reset at the start of the creature's turn), and free interaction (later).
- `MoveIntent` spends budget using the 5-5-5 diagonal rule (bible/DECISIONS: 8-way, every
  step 5 ft) on a 3D grid; occupied or blocked cells reject. Difficult terrain, opportunity
  attacks, cover, line of sight come in 03b.
- `AttackIntent` (melee, reach 5 ft): d20 + attack bonus vs AC; natural 20 hits and doubles
  damage dice; natural 1 misses. Damage reduces temp HP first. HP 0 = dead for monsters,
  unconscious/dying for PCs (death saves in 03b).
- `EndTurnIntent` advances; dead creatures are skipped; a new round emits `RoundStarted`.

## 4. Event log

Append-only list of immutable events with a monotonically increasing `Sequence`. Clients
apply events in order to a local mirror of the model; the host is authoritative. A snapshot
(full model) plus the log tail is the late-join protocol (Plan 10). Every event carries
enough data to render it (who, what, numbers) so the UI never re-derives rules.

## 5. What 03b-03e add

03b core mechanics (checks/saves everywhere, cover, LoS, difficult terrain, opportunity
attacks, death saves, rests); 03c effects/spells (composable primitives); 03d conditions as
rule modifiers; 03e the 2024 character model and level-up. Each ships with tests that name
the SRD rule they prove.

## 6. Testing convention

xUnit in `engine/DND.Engine.Tests`. One test class per rule area. Deterministic seeds. A
`Replay` test runs the same intent script twice and asserts identical event logs. Run:

```
cd homelab/DND.vbeta/engine && dotnet test
```
