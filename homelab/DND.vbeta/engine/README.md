# engine/

Pure C# (netstandard2.1, C# 9) class library + xUnit tests. No `UnityEngine` references,
ever (a test asserts it). Holds the 5e rules engine, and later the storybook runtime and
monster AI. Design: [`../docs/engine-architecture.md`](../docs/engine-architecture.md).

```
engine/
  DND.Engine.sln
  Directory.Build.props        # bin/obj -> engine/.build/ so Unity never imports DLLs
  DND.Engine/                  # UPM package root: package.json + DND.Engine.asmdef + Runtime/
    Runtime/Core/              # SeededRng (xorshift64*), DiceRoll, Ability math, GridPos (5-5-5)
    Runtime/Model/             # CreatureTemplate, Creature (live state, temp HP)
    Runtime/Rules/             # D20Test (advantage, nat 20/1, AC, DC)
    Runtime/Events/            # GameEvent hierarchy, EventLog (append-only, fingerprint)
    Runtime/Intents/           # MoveIntent, AttackIntent, EndTurnIntent, RuleResult
    Runtime/Combat/            # Encounter: initiative, turns, action economy, melee, end detection
  DND.Engine.Tests/            # xUnit; `dotnet test` from this folder
```

Unity consumes `DND.Engine/` as the local package `com.ptm.dnd.engine` (a `file:` entry in
Dungine's manifest). Keep every file Unity-compilable: no `init`, no records, no
`System.Text.Json`, nullable annotations are fine (warnings only in Unity).
