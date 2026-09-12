---
plan: 17
title: Sonnet execution batch 02 (engine data loader, 03b core mechanics, 03d conditions)
stage: 2
model: sonnet
mode: execute
depends_on: [16, 03a]
inputs: [this file, engine/ sources, content/rules/ (Plan 03a output), docs/engine-architecture.md, DECISIONS.md D43–D47]
outputs: [see each task's "Outputs"]
done_when: [every task's done_when holds; `dotnet test` green at the stated count; Peter has the commit list]
status: approved
---

# 17: Sonnet batch 02

Written by Fable on 2026-09-12 after reviewing batch 01. Same rules as Plan 16's "How Sonnet
must work" section: **read that section first and follow it literally** (zero design
decisions, in order, never commit, never edit `config.json`/`DECISIONS.md`/palette files, never
run the dispatcher, never touch the Unity Editor). Two additions for this batch:

- The engine stays **netstandard2.1 / C# 9, no UnityEngine, no System.Text.Json, no NuGet
  packages**. `System.IO` and `System.Text` are fine. If you think you need a package, stop and
  ask Peter.
- Every new rule cites the SRD rule it implements in a one-line `///` comment on the method,
  the way `Encounter.Start()` does. Tests are named after the rule they prove.

Tasks: **B1** JSON reader → **B2** compendium loader → **B3** core mechanics (03b, first half)
→ **B4** conditions (03d) → **B5** housekeeping. B1/B2 are what turns `content/rules` into
`CreatureTemplate`s; B3/B4 are the rules that D&D combat needs before spells (03c, Fable).

---

## B1. `DND.Engine.Data.Json`: a minimal JSON reader

**Why.** The engine must load `content/rules/*.json` in Unity and headless without
System.Text.Json (Unity lacks it) or UnityEngine.JsonUtility (engine is UnityEngine-free).
A ~200-line recursive-descent reader is smaller than any dependency and fully testable.

**Files.** New: `engine/DND.Engine/Runtime/Data/Json.cs`, `engine/DND.Engine.Tests/JsonTests.cs`.

**B1.1 API**, exactly:
```csharp
namespace DND.Engine.Data
{
    /// <summary>Thrown for malformed JSON; Position is the 0-based char offset where parsing failed.</summary>
    public sealed class JsonException : System.Exception
    {
        public readonly int Position;
        public JsonException(string message, int position) : base($"{message} at {position}") { Position = position; }
    }

    /// <summary>Minimal JSON reader. Objects -> Dictionary&lt;string, object?&gt; (insertion order preserved by
    /// the caller iterating a List of keys is NOT required), arrays -> List&lt;object?&gt;, numbers -> double,
    /// strings -> string, true/false -> bool, null -> null. No comments, no trailing commas, no NaN.</summary>
    public static class Json
    {
        public static object? Parse(string text);
        // Typed helpers for the loader; all return the fallback (or null) instead of throwing when the key is absent or the wrong type.
        public static Dictionary<string, object?>? Obj(object? v);
        public static List<object?>? Arr(object? v);
        public static string? Str(object? v);
        public static double? Num(object? v);
        public static int? Int(object? v);            // Num rounded toward zero; null if not a number
        public static bool? Bool(object? v);
        public static object? Get(object? obj, string key);          // Obj(obj)?[key] or null
        public static object? Path(object? obj, params string[] keys); // Get chained; null on the first miss
    }
}
```
- Use `Dictionary<string, object?>` (ordinary; key order is not a contract).
- Strings: handle `\" \\ \/ \b \f \n \r \t \uXXXX`, including UTF-16 surrogate pairs (`😀`). Raw control characters inside strings are an error.
- Numbers: parse with `double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture)` on the maximal `-?digits(.digits)?([eE][+-]?digits)?` span. `Int()` returns null when the double is not integral or out of int range.
- Whitespace: space, tab, CR, LF only.
- `Parse` must reject trailing garbage (`{} x` is an error) and empty input.
- Depth: recursion is fine (our files nest < 20 deep).

**B1.2 Tests** (`JsonTests.cs`, xUnit):
1. `Parse_Scalars` — `"1"`→1.0, `"-2.5e3"`→-2500, `"\"a\""`→"a", `"true"`, `"false"`, `"null"`.
2. `Parse_StringEscapes_IncludingSurrogatePair` — `"\"\\u00e9\\ud83d\\ude00\\n\""` → `"é😀\n"`.
3. `Parse_NestedObjectAndArray` — `{"a":[1,{"b":null}],"c":{}}` shape checks via the helpers.
4. `Parse_RejectsTrailingComma_TrailingGarbage_EmptyInput` — three `JsonException`s with `Position` ≥ 0.
5. `Helpers_ReturnNullOnWrongType` — `Json.Int("x")` null, `Json.Str(1.0)` null, `Json.Path(obj, "a", "zzz")` null.
6. `Int_RejectsNonIntegral` — `Json.Int(Json.Parse("1.5"))` is null; `Json.Int(Json.Parse("7"))` is 7.
7. `Parse_RealFile_MonstersJson` — reads `content/rules/2014/monsters.json` (see B2.4 for how tests find it) and asserts it is a `List` of 334 objects each having `"id"`.

**Verify.** `dotnet test` → 47 + 7 = **54** passing.

---

## B2. `DND.Engine.Data.Compendium`: rules data → templates (D47)

**Why.** Encounters are built from `CreatureTemplate`s; the compendium is the only place that
knows the `content/rules` envelope. 2024 is primary, 2014 fills gaps **per id** (D14).

**Files.** New: `engine/DND.Engine/Runtime/Data/Compendium.cs`, `engine/DND.Engine/Runtime/Data/RulesFiles.cs`, `engine/DND.Engine.Tests/CompendiumTests.cs`. Edited: `engine/DND.Engine.Tests/DND.Engine.Tests.csproj` (copy rules data), `docs/engine-architecture.md` (§2 table row + a §7).

**B2.1 Records.** Add to `Compendium.cs`:
```csharp
public sealed class RulesRecord
{
    public string Id = ""; public string Kind = ""; public string Ruleset = ""; public string Name = "";
    public string Source = ""; public string License = ""; public string Attribution = "";
    public Dictionary<string, object?> Data = new Dictionary<string, object?>();   // the normalized "data" object
}
```
`raw` is **not** loaded (it doubles memory and the engine never reads it).

**B2.2 Compendium API**, exactly:
```csharp
public sealed class Compendium
{
    public static readonly string[] Rulesets = { "2024", "2014" };   // lookup order = fallback order
    /// <summary>Adds every record of one file. kind is the file's kind ("monsters"); ruleset "2024"|"2014".</summary>
    public void AddFile(string ruleset, string kind, string json);
    public IReadOnlyList<RulesRecord> All(string kind, string ruleset);          // records of that kind in that ruleset, sorted by Id
    /// <summary>The record for id, preferring `preferRuleset`, then the other ruleset (D14 fallback). Null if neither has it.</summary>
    public RulesRecord? Find(string kind, string id, string preferRuleset = "2024");
    public CreatureTemplate Monster(string id, string preferRuleset = "2024");     // throws KeyNotFoundException(id) if absent in both
    public bool TryMonster(string id, out CreatureTemplate template, string preferRuleset = "2024");
    public IEnumerable<string> MonsterIds(string ruleset);
    public ObjectTemplate? ObjectTemplateFor(string equipmentId, string preferRuleset = "2024"); // null for now: equipment→object mapping is 03c/12; keep the signature, return null, and test that it returns null.
}
```
Validation on `AddFile`: every record must have non-empty `id`, `kind`, `ruleset` ∈ Rulesets, `license == "CC-BY-4.0"`; otherwise throw `InvalidDataException($"{kind}/{ruleset}: record {index}: {why}")`. Duplicate id within (kind, ruleset) → `InvalidDataException`.

**B2.3 Monster mapping** (`data` → `CreatureTemplate`), exactly; missing values use the default on the right, never throw except where stated:
| CreatureTemplate | from `data` | default |
|---|---|---|
| `Id` | envelope `id` | — |
| `Name` | envelope `name` | — |
| `Ruleset` | envelope `ruleset` | — |
| `Abilities` | `abilities.{str,dex,con,int,wis,cha}` via `Json.Int` | throw `InvalidDataException` if any of the six is missing (a monster without abilities is not usable) |
| `MaxHp` | `hit_points` | throw if missing |
| `ArmorClass` | `armor_class` | throw if missing |
| `SpeedFeet` | `speed_ft.walk` | 30 if null (a swimmer with no walk speed still gets a token 30 for v0; note it in a `///` comment) |
| `ProficiencyBonus` | `proficiency_bonus` | 2 |
| `SkillProficiencies` | keys of `skills` (already lower-case with spaces, e.g. "sleight of hand") | empty |
| `ToolProficiencies` | empty (monsters do not list tools) | empty |
| `Attacks` | one `AttackTemplate` per entry of `attacks`: `Name`=name; `AttackBonus`=attack_bonus; `ReachFeet` = `reach_ft` if non-null, else `range_ft[0]` if non-null, else 5; `RangeFeet`/`LongRangeFeet` (new fields, see B3.1) = `range_ft[0]`/`range_ft[1]` or 0/0; `Damage` = `DiceRoll.Parse(damage[0].dice)` ; `DamageType` = `damage[0].type` or "bludgeoning" | an attack with no `damage` entries or an unparsable dice string is **skipped** and counted in `Compendium.Warnings` (a `List<string>`), never thrown |

`DiceRoll.Parse` must accept `"2d6 + 5"` (spaces) and `"1d4"`; check `Dice.cs` — it strips spaces already. If a dice string has a form it cannot parse (e.g. `"2d6+2d4"`), the attack is skipped with a warning.

**B2.4 Files helper** (`RulesFiles.cs`, `System.IO` allowed here and only here in the engine):
```csharp
public static class RulesFiles
{
    /// <summary>Loads every &lt;root&gt;/{2024,2014}/*.json into a new Compendium. Missing ruleset folders are skipped; a missing root throws DirectoryNotFoundException.</summary>
    public static Compendium LoadDirectory(string rulesRoot);
}
```
Tests find the data by copying it: add to `DND.Engine.Tests.csproj`
```xml
<ItemGroup>
  <None Include="..\..\content\rules\**\*.json" Link="rules\%(RecursiveDir)%(Filename)%(Extension)" CopyToOutputDirectory="PreserveNewest" />
</ItemGroup>
```
and in tests use `Path.Combine(AppContext.BaseDirectory, "rules")`. B1's test 7 uses the same path.

**B2.5 Tests** (`CompendiumTests.cs`):
1. `LoadDirectory_LoadsBothRulesets` — `All("monsters","2014").Count == 334`, `All("monsters","2024").Count == 3`, `All("spells","2024").Count == 339`.
2. `Find_PrefersRequestedRuleset_ThenFallsBack` — `Find("monsters","aboleth","2024")!.Ruleset == "2024"`; `Find("monsters","goblin","2024")!.Ruleset == "2014"` (2024 has no goblin); `Find("monsters","nope")` is null.
3. `Monster_Goblin_MapsStatBlock` — AC 15, MaxHp 7, Speed 30, Abilities (8,14,10,10,8,8), ProficiencyBonus 2, `SkillProficiencies` contains "stealth", 2 attacks; Scimitar: +4, reach 5, `Damage.ToString()=="1d6+2"`, type "slashing"; Shortbow: RangeFeet 80, LongRangeFeet 320.
4. `Monster_Aboleth2024_Reach15` — Tentacle `ReachFeet == 15`, AttackBonus 9, damage "2d6+5".
5. `Monster_Unknown_Throws` — `KeyNotFoundException`; `TryMonster` false.
6. `AllMonsters_MapWithoutThrowing` — every id from `MonsterIds("2014")` and `MonsterIds("2024")` maps; assert `Warnings.Count` is printed via `ITestOutputHelper` and is **< 40** (there are a handful of multi-dice attacks; if it is higher, list the first 10 warnings in the assertion message and stop — do not "fix" the data).
7. `AddFile_RejectsBadLicense_AndDuplicateId` — two `InvalidDataException`s from hand-written JSON strings.
8. `LoadedMonsters_FightDeterministically` — build an `Encounter` from `Monster("goblin")` ×2 (Party side, ids G1 G2) vs `Monster("wolf")` (Enemy), run the Plan 03 replay script from `EncounterTests.Replay_...` twice with seed 5, fingerprints equal.
9. `ObjectTemplateFor_ReturnsNullForNow` — documents the stub.

**B2.6 Docs.** `docs/engine-architecture.md`: add row `| DND.Engine.Data | Json reader, RulesRecord, Compendium, RulesFiles | Core, Model |` to the §2 table (Data may reference Model to build templates; nothing references Data except the host), and a §7 "Data loading" of four sentences: envelope, 2024→2014 per-id fallback, what is mapped, that `raw` is never loaded and files are read by the host (Unity: `StreamingAssets/rules/`, copied by a build step in Plan 14).

**Verify.** `dotnet test` → 54 + 9 = **63** passing. `dotnet build ... -c Release` 0 warnings.

---

## B3. 03b core mechanics, first half

**Why.** Before spells and the auto-DM, combat needs the movement/attack rules that every
5e fight uses. This half is the ones that touch only creatures, the grid, and the action economy.

**Files.** Edited: `Runtime/Model/Creature.cs`, `Runtime/Combat/Encounter.cs`, `Runtime/Intents/Intents.cs`, `Runtime/Events/GameEvents.cs`, `Runtime/Rules/D20Test.cs`. New: `Runtime/Rules/LineOfSight.cs`, `engine/DND.Engine.Tests/CoreMechanicsTests.cs`.

**B3.1 Attack template additions** (`Creature.cs`): `AttackTemplate` gets `public int RangeFeet;` and `public int LongRangeFeet;` (0 = melee). `public bool IsRanged => RangeFeet > 0;`.

**B3.2 Battlefield interface** (`Encounter.cs`). Replace `IBattlefield` with:
```csharp
public interface IBattlefield
{
    bool IsBlocked(GridPos cell);          // terrain that stops movement
    bool BlocksSight(GridPos cell);        // terrain that stops sight (walls, closed doors are objects, not terrain)
    bool IsDifficult(GridPos cell);        // difficult terrain: each foot costs 2 (SRD "Difficult Terrain")
    int CoverBonus(GridPos from, GridPos to);  // 0, 2 (half cover) or 5 (three-quarters); total cover = BlocksSight
}
```
`OpenField` returns false/false/false/0. Add `GridField : IBattlefield` with `HashSet<GridPos> Walls, Difficult` and `Dictionary<GridPos,int> Cover` (cover bonus granted to a target standing **in** that cell against any attacker not in it), all public; `IsBlocked`/`BlocksSight` are `Walls.Contains`. `Encounter.BlocksSight(cell)` (from batch 01) becomes `Field.BlocksSight(cell) || object blocks`. Update the two existing tests that construct `OpenField`/`IBattlefield` only if they no longer compile.

**B3.3 Line of sight** (`Rules/LineOfSight.cs`): port the POC's `GridMap.HasLineOfSight` (cell-center walk with the diagonal-corner rule) to `public static bool HasLineOfSight(GridPos from, GridPos to, Func<GridPos, bool> blocksSight)` on the X/Z plane (Y ignored for v0). `Encounter.HasLineOfSight(a, b)` wraps it with `cell => BlocksSight(cell)`. The origin cell never blocks its own sight; the target cell's own blocking does not matter (you can see a closed door).

**B3.4 Intents** (append):
```csharp
public sealed class DashIntent : Intent { ... }        // SRD "Dash": action; gain extra movement equal to speed this turn
public sealed class DisengageIntent : Intent { ... }   // SRD "Disengage": action; movement doesn't provoke opportunity attacks this turn
public sealed class DodgeIntent : Intent { ... }       // SRD "Dodge": action; until your next turn, attacks against you have disadvantage and you have advantage on Dex saves (saves are 03c; implement the attack half)
public sealed class DeathSaveIntent : Intent { ... }   // only legal for a Dying creature at the start of its turn (see B3.7)
```
`MoveIntent` is unchanged (one cell per intent) — the presentation submits a path as steps.

**B3.5 Turn flags** on `Encounter`: `public bool Dashed { get; private set; }`, `public bool Disengaged { get; private set; }`, and on `Creature`: `public bool Dodging;` (set by Dodge, cleared at the start of that creature's next turn) and `public bool ReactionAvailable = true;` (reset at the start of the creature's own turn: SRD "Reactions"). `AdvanceTurn` resets `Dashed=false`, `Disengaged=false`, `c.Dodging=false`, `c.ReactionAvailable=true` for the creature whose turn starts.

**B3.6 Rules**, each a private handler with a `///` SRD citation:
- **Dash**: needs the action; `MovementLeftFeet += actor.SpeedFeet`; `Dashed=true`; event `ActionTaken(actorId, "Dash")` (new event, `Describe` = `"{id} takes the {name} action"`).
- **Disengage**: needs the action; `Disengaged=true`; `ActionTaken`.
- **Dodge**: needs the action; `actor.Dodging=true`; `ActionTaken`.
- **Difficult terrain**: in `HandleMove`, `cost = Feet * (Field.IsDifficult(m.To) ? 2 : 1)`.
- **Opportunity attacks** (SRD "Opportunity Attacks"): in `HandleMove`, **before** moving, for every hostile creature `h` (other side, not dead, not Incapacitated per B4, `ReactionAvailable`, has at least one melee attack) with `GridPos.Cells(h.Position, actor.Position) <= reach/5` where reach = its first melee attack's `ReachFeet`, and for which the destination is **outside** that reach (`Cells(h.Position, m.To) > reach/5`): if `Disengaged` is false, `h` makes that melee attack against the actor exactly as `HandleAttack` does (roll, hit, damage, death), spends `h.ReactionAvailable=false`, and appends `OpportunityAttack(h.Id, actor.Id)` (new event, `Describe` = `"{h} takes an opportunity attack against {actor}"`) **before** the `AttackRolled`. The move then completes even if the actor was hit (unless the actor died, in which case the move is cancelled and the intent still returns `Ok()`). Order: hostiles in `Order` sequence.
- **Ranged attacks** (SRD "Range", "Ranged Attacks in Close Combat"): `HandleAttack` for an `IsRanged` attack: reject `"reach"` if distance > `LongRangeFeet`; roll with `RollMode.Disadvantage` if distance > `RangeFeet` **or** any hostile that can see the attacker is adjacent (Cells==1); reject `"line-of-sight"` if `!HasLineOfSight(actor, target)`. Melee attacks also require LoS (you cannot attack through a closed door), using the same rejection.
- **Cover** (SRD "Cover"): target AC for the hit check = `target.ArmorClass + Field.CoverBonus(actor.Position, target.Position)`; `AttackRolled.TargetAc` records the effective value. Total cover is already a LoS failure.
- **Advantage/disadvantage stacking** (SRD "Advantage and Disadvantage"): compute `adv` and `dis` booleans from all sources (Dodge → dis; B4 conditions; ranged rules); if both, roll Normal. Put this in `private RollMode ResolveMode(bool adv, bool dis)`.
- **Dodge**: attacks against a `Dodging` target that can see the attacker have disadvantage (the "can see" half is B4's Blinded; for now: always).

**B3.7 Death and dying** (SRD "Dropping to 0 Hit Points", "Death Saving Throws"):
- Only `Side.Party` creatures use death saves; monsters die at 0 HP as now.
- `Creature` gets `public int DeathSuccesses, DeathFailures;`, `public bool IsStable;`, `public bool IsDying => Side == Side.Party && Hp <= 0 && !IsDead && !IsStable;`. `IsDead` becomes `Hp <= 0 && (Side != Side.Party || DeathFailures >= 3)`. Add `public bool IsDown => Hp <= 0;` and mark Down creatures **Unconscious** (B4) automatically.
- Damage that drops a Party creature to 0 sets Hp 0, clears TempHp; if the damage remaining after reaching 0 ≥ MaxHp → **instant death** (`DeathFailures = 3`, `CreatureDied`). Damage while at 0 HP = one failure (two if the hit was a crit); a melee crit from within 5 ft... keep just "crit = 2 failures".
- At the start of a Dying creature's turn the engine **automatically** rolls the death save (no intent needed; `DeathSaveIntent` is therefore only accepted when `IsDying` and it is that creature's turn and no save has been rolled this turn — used by the UI to "roll now" explicitly; both paths call the same method, and the auto-roll happens in `AdvanceTurn` so the intent will usually be rejected `"death-save: already rolled this turn"`). Roll `D20Test.Roll(Rng, 0)`: nat 1 = 2 failures; nat 20 = regain 1 HP (Hp=1, counters reset, no longer Dying); ≥10 success else failure. Event `DeathSaveRolled(id, roll, successes, failures)` `Describe` = `"{id} death save {roll}: {s} successes / {f} failures"`. 3 successes → `IsStable = true` (counters reset), event `Stabilized(id)`; 3 failures → `CreatureDied`.
- A Dying/stable creature at 0 HP takes no actions: `Handle` rejects with `"unconscious"` except `EndTurnIntent` and `DeathSaveIntent`. Healing (`Creature.Heal(int)` — add it: `Hp = Math.Min(MaxHp, Hp + amount)`, resets death counters and `IsStable`) is the only way up in this batch.
- `CheckEnd`: a party of only Dying/dead creatures **has lost** (no one can act) — treat `!IsDead && !IsDown` as "alive" for the party-side check.

**B3.8 Tests** (`CoreMechanicsTests.cs`; reuse batch 01's helpers pattern; a `GridField` with a wall line where needed):
1. `Dash_DoublesMovement_SpendsAction`
2. `Disengage_PreventsOpportunityAttack`
3. `LeavingReach_ProvokesOneOpportunityAttack_UsesReaction` — the goblin gets exactly one `OpportunityAttack` event and its `ReactionAvailable` is false; a second provoking move in the same turn gets none.
4. `MovingWithinReach_DoesNotProvoke` — stepping from one adjacent cell to another adjacent cell.
5. `DifficultTerrain_CostsDouble`
6. `RangedAttack_BeyondLongRange_Rejected` and `RangedAttack_BeyondNormalRange_Disadvantage` (assert `AttackRolled.Roll.Mode`).
7. `RangedAttack_AdjacentHostile_Disadvantage`
8. `Attack_ThroughWall_Rejected_LineOfSight` (melee across a diagonal wall corner and ranged through a wall).
9. `HalfCover_AddsTwoToAc` — `AttackRolled.TargetAc == AC + 2`.
10. `Dodge_GivesAttackerDisadvantage_UntilNextTurn` — disadvantage this round; Normal after the dodger's next turn starts.
11. `AdvantageAndDisadvantage_Cancel`
12. `PartyCreature_AtZero_IsDying_MonsterDies`
13. `DeathSaves_ThreeFailures_Dead` / `DeathSaves_ThreeSuccesses_Stable` / `DeathSave_Nat20_RegainsOneHp` — pick seeds by scanning 1..200 for the needed sequences, as batch 01 did.
14. `DamageWhileDying_IsFailure_CritIsTwo`
15. `MassiveDamage_InstantDeath`
16. `Heal_RevivesDying_ResetsCounters`
17. `Replay_CoreMechanics_SameFingerprint` — a 12-intent script covering Dash, a provoking move, a ranged attack, Dodge; two runs, equal.

**Verify.** `dotnet test` → 63 + 20 = **83** (17 methods, some with two facts; state the true count). Release build 0 warnings.

---

## B4. 03d conditions

**Why.** Conditions are the vocabulary spells, traps and the auto-DM will speak. This batch
implements the core set as rule modifiers with durations, without the spells that cause them.

**Files.** New: `Runtime/Model/Conditions.cs`, `engine/DND.Engine.Tests/ConditionTests.cs`. Edited: `Creature.cs` (replace `HashSet<string> Conditions`), `Encounter.cs`, `Intents.cs`, `GameEvents.cs`, `Plans/Rules/03d-conditions-and-status.md` (status), `docs/engine-architecture.md` (one paragraph in §3).

**B4.1 Model**:
```csharp
public enum Condition { Blinded, Charmed, Deafened, Frightened, Grappled, Incapacitated, Invisible, Paralyzed, Petrified, Poisoned, Prone, Restrained, Stunned, Unconscious, Exhaustion }
public enum ConditionDuration { UntilRemoved, EndOfSourceNextTurn, EndOfTargetNextTurn, Rounds }
public sealed class ActiveCondition { public Condition Kind; public string SourceId; public ConditionDuration Duration; public int RoundsLeft; public int Level; /* Exhaustion 1..6 (2024: 1..10 is 2014; use 2024: each level -2 to d20 tests, speed -5 ft, death at 6) */ }
```
`Creature.Conditions` becomes `List<ActiveCondition>` with `bool Has(Condition c)`, `int ExhaustionLevel`.

**B4.2 API on Encounter** (host/DM/spells call these; not intents):
`ApplyCondition(string targetId, Condition c, string sourceId, ConditionDuration d, int rounds = 0, int level = 1)` and `RemoveCondition(string targetId, Condition c)`, each appending `ConditionApplied(target, c, source, duration)` / `ConditionRemoved(target, c)` (`Describe`: `"{id} is {Condition}"` / `"{id} is no longer {Condition}"`). Applying a condition the creature already has (same Kind) replaces its duration; Exhaustion adds levels (cap 6 → `CreatureDied`). Plus one intent for the player-facing case: `StandUpIntent` (Prone: costs half the creature's speed in movement, SRD "Being Prone"; rejected `"movement"` if not enough movement left).

**B4.3 Durations**: at the **end** of each creature's turn (in `HandleEndTurn`, before `AdvanceTurn`): every `ActiveCondition` on any creature with `EndOfSourceNextTurn` whose `SourceId` is the ending creature, or `EndOfTargetNextTurn` whose target is the ending creature, is removed; `Rounds` decrements at the end of the **target's** turn and is removed at 0.

**B4.4 Mechanical effects** (SRD Appendix "Conditions", 2024 wording), implemented in the attack/move paths from B3 through a single `private (bool adv, bool dis) AttackModifiers(Creature attacker, Creature target, bool ranged)` and checks in `Handle`:
| Condition | Effect implemented |
|---|---|
| Blinded | attacker: dis; target: attackers have adv; cannot "see" (used by Dodge/opportunity attack "can see" checks) |
| Charmed | cannot target the charmer with `AttackIntent`/`AttackObjectIntent`-on-its-cell: reject `"charmed"` |
| Deafened | no mechanical effect in this batch (record only) |
| Frightened | dis on attacks while the source is within LoS; cannot willingly move closer to the source (reject `"frightened"` if `Cells(to, source) < Cells(from, source)`) |
| Grappled | speed 0: any `MoveIntent` rejected `"grappled"`; removed automatically if the source is dead or no longer adjacent at the end of any turn |
| Incapacitated | no actions, bonus actions, or reactions: reject all intents but EndTurn `"incapacitated"`; never makes opportunity attacks |
| Invisible | attacker: adv; target: attackers dis (no "can see" nuance yet) |
| Paralyzed | Incapacitated + speed 0 + attackers adv + any hit from within 5 ft is a critical |
| Petrified | as Paralyzed + immune to all damage (damage 0, `DamageDealt` still logged) |
| Poisoned | dis on attacks (and on checks: ForceOpen/PickLock rolls) |
| Prone | attacker: dis; melee attackers within 5 ft adv, ranged attackers dis; moving while Prone costs double (crawl); `StandUpIntent` ends it |
| Restrained | speed 0; attacker dis; attackers adv |
| Stunned | Incapacitated + speed 0 + attackers adv |
| Unconscious | Incapacitated + Prone-like (attackers adv, hits within 5 ft crit) + drops nothing (no items yet); set/cleared automatically by B3.7's Down state |
| Exhaustion | `-2 × level` to every d20 roll the creature makes (attacks, checks, death saves); `SpeedFeet - 5 × level` (min 0); level 6 → dead |

`Incapacitated` is also implied by Paralyzed/Petrified/Stunned/Unconscious: implement `bool IsIncapacitated(Creature)` that checks all five.

**B4.5 Tests** (`ConditionTests.cs`), one per row above where the row has a mechanical effect (13), plus:
- `Duration_EndOfSourceNextTurn_Expires`, `Duration_Rounds_CountsDown`, `Grappled_AutoRemovedWhenSourceDies`
- `Exhaustion_StacksAndKillsAtSix`
- `StandUp_CostsHalfSpeed_RejectedWithoutMovement`
- `Replay_Conditions_SameFingerprint`

**Verify.** `dotnet test` → 83 + 19 = **102** (state the true count). Release build 0 warnings.

---

## B5. Housekeeping

1. `Plans/README.md`: 03b → `in-progress (first half: B3 …)`, 03d → `done (B4 …)`, 03 → append `; data loader (B1/B2)`, 17 → `done` when B1–B4 verified.
2. `Plans/Rules/03b-core-mechanics.md` and `03d-conditions-and-status.md`: add a "Done in batch 02" list and, for 03b, a "Remaining for batch 03" list: multi-step move intents with pathing, rests, initiative ties by player choice, mounted/flying, the "can see" rule for Dodge/opportunity attacks against Invisible.
3. Final message: verification lines per task and one commit list (ptm4 only; nothing in this batch touches the Dungine repo).

## What Fable does with the results

Reviews B1–B4 in this order: replay determinism across all three test classes, the death-save
edge cases, then the conditions table against the SRD text. Then designs 03c (effects and
spells) on top of `ApplyCondition`, `Heal`, `DamageDealt` and the `Compendium` spell records,
and the Unity "encounter shell" (D44) that consumes `Compendium` + `Encounter` for the first
engine-driven scene.
