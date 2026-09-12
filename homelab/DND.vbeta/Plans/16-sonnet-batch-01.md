---
plan: 16
title: Work split and Sonnet execution batch 01
stage: 2
model: sonnet
mode: execute
depends_on: [02, 03, 06]
inputs: [this file, engine/ sources, tools/bridge/, Assets/Dungine/POC/PocHud.cs, SOURCES.md]
outputs: [see each task's "Outputs"; every task ends with a "paths to commit" list]
done_when: [every task's done_when holds; `dotnet test` green; `bridge.py test` green; Peter has the commit list]
status: approved
---

# 16: Work split and Sonnet execution batch 01

Written by Fable on 2026-09-11 after the door pilot. Part A is the honest split of the
remaining work by who should do it. Part B is a pack of tasks for **Sonnet in execute mode**.

## How Sonnet must work on this plan (read twice)

- **Zero design decisions.** Every choice that matters is made in this file. If a step is
  ambiguous, underspecified, or turns out to be impossible as written, **stop that task and
  ask Peter** in one short message that quotes the step number. Do not pick "the sensible
  option"; do not refactor beyond what a step names; do not add features, options, flags,
  abstractions, or "while I'm here" cleanups.
- Do the tasks **in order** (S1 → S5). Each is independent enough to commit on its own.
- **Never `git commit`, `amend`, `reset`, `stash`, or push.** End each task with the list of
  paths to commit. Peter commits.
- **Never edit** `tools/palette.py`, `assets-src/palettes/`, `Plans/DECISIONS.md`,
  `tools/bridge/config.json` beyond what a step names, or anything under `.agent-state/`.
- **Never run the bridge dispatcher** (`bridge.py run`) and never touch the Unity Editor
  except in S2, which tells you exactly which commands to run.
- Tests are the spec. Where a step lists tests by name, write those tests with those names
  and make them pass; do not delete or weaken an existing test to make a new one pass.
- Engine code is **netstandard2.1, C# 9, no UnityEngine, no System.Text.Json, no LINQ in hot
  loops is not a rule but keep the style of the existing files** (readonly fields, sealed
  classes, `RuleResult.Reject("rule-name", "why")`).
- Python is 3.12, **stdlib only** (the bridge and tools have no dependencies; keep it so).
- When you finish a task, run its verification commands and paste their last lines into
  your final message. "It should work" is not a result.

---

## Part A: who does what from here

Remaining work to reach the **local beta** (stage 3) of Plan 00, sized in agent-days and
attributed to the agent that should own it. Percentages are of the remaining total.

| Owner | Share | What | Why them |
|---|---|---|---|
| **Sonnet** (execute) | ~45 % | Everything with a spec: this batch (bridge lock/doctor, HUD fix, engine object interaction, SRD ingest), then 03b core mechanics, 03d conditions, 10 networking, 12 map editor, 14 builds. | Cheapest per token; correct when the spec is complete. |
| **Fable** (decide) | ~25 % | Designs that gate Sonnet: engine effect/spell model (03c), 2024 character model (03e), campaign schema (07), auto-DM (08), UI design (11 first half), reviews of every Sonnet and Astra deliverable, bridge task registration. | Judgement calls with cross-plan consequences. |
| **Astra / Codex** (execute, via bridge) | ~20 % | Unity-side and asset work: door visibility polish in the POC, chest/lever/brazier interactables (voxels + POC wiring), second biome voxel kit (cave), sprite batch 3 (townsfolk and animals), portrait set. | Has the image tool, the voxel writer, and now a proven Unity workflow through the bridge. |
| **Peter** | ~10 % | Look reviews (kit room, sprites), source confirmations already done, commits, UGS Relay/Lobby link, friend sessions, campaign content choices. | Only he can. |

What Fable specifically cannot hand off: **03c** (effects need a composable primitive
design that everything else builds on), **07** (the storybook schema is the content contract),
**08** (the auto-DM behaviour), and the **engine loader design** (how `content/rules` JSON
becomes `CreatureTemplate` without System.Text.Json). Those four are the next Fable sessions,
in that order, and each one produces a Sonnet batch like this one.

The bridge pilot showed the split works: Astra implements in Unity, Fable reviews with live
verification, and the 5e rule text lives in the engine, which Sonnet can grow from specs.

---

## Part B: Sonnet batch 01

### S1. Bridge: single-dispatcher lock and `doctor` command

**Why.** Three `bridge run` dispatchers ran at once on 2026-09-11 and double-launched runs.
Both provider executables also moved during self-updates. The bridge needs to refuse a second
dispatcher and to tell an operator, in one command, whether it can run at all.

**Files.** `homelab/DND.vbeta/tools/bridge/bridge.py`, `tools/bridge/test_bridge.py`,
`homelab/agentic/runbooks/11-dungine-agent-collaboration.md` (one paragraph).

**S1.1 Lock file.**
- Path: `<state_root>/dispatcher.lock`. Content: JSON `{"pid": <int>, "started": <iso utc>, "heartbeat": <iso utc>, "host": <socket.gethostname()>}`.
- Add to class `Bridge`:
  ```python
  def acquire_dispatcher_lock(self, force: bool = False) -> tuple[bool, str]:
      """True if this process now owns the lock. False + reason if another live dispatcher holds it."""
  def refresh_dispatcher_lock(self) -> None:      # rewrite heartbeat; called from tick() first line
  def release_dispatcher_lock(self) -> None:      # delete only if the file's pid == os.getpid()
  @staticmethod
  def pid_alive(pid: int) -> bool
  ```
- `pid_alive` on Windows: `ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)` (PROCESS_QUERY_LIMITED_INFORMATION); if the handle is 0 return False; else `GetExitCodeProcess` and return True only if the code is 259 (STILL_ACTIVE); always `CloseHandle`. On non-Windows: `os.kill(pid, 0)` in try/except (`ProcessLookupError` → False, `PermissionError` → True).
- `acquire_dispatcher_lock` logic, exactly:
  1. If the file does not exist → write it, return `(True, "acquired")`.
  2. Parse it. If parsing fails → overwrite, return `(True, "acquired (replaced unreadable lock)")`.
  3. If `pid == os.getpid()` → refresh, return `(True, "already ours")`.
  4. If `pid_alive(pid)` and heartbeat is younger than `limits.lease_stale_seconds` (existing config key, currently 120) → if `force` overwrite and return `(True, "forced takeover of pid N")`, else return `(False, f"dispatcher pid {pid} is alive (heartbeat {age:.0f}s ago); stop it first or use --force")`.
  5. Otherwise (dead pid or stale heartbeat) → overwrite, return `(True, f"replaced stale lock of pid {pid}")`.
- Writes are atomic (`atomic_write_json` already exists in the file; use it).
- `tick()`: first statement becomes `self.refresh_dispatcher_lock()` **only when the lock is ours** (check pid in file == os.getpid(); if the file is missing or someone else's, do nothing; do not throw).

**S1.2 CLI.**
- `run` gets `--force` (store_true). In the `run` branch of `main()`, before the loop: call `acquire_dispatcher_lock(a.force)`; on False print the reason to stderr and `return 2`; on True print `dispatcher pid {os.getpid()}: {reason}`. Wrap the loop in `try/finally` and call `release_dispatcher_lock()` in the `finally`. Also register `atexit.register(b.release_dispatcher_lock)`.
- `status` and `write_status()` add one line after `enabled/paused`: `dispatcher: pid N, heartbeat Xs ago` or `dispatcher: none`. Stale (heartbeat older than `lease_stale_seconds`) prints `dispatcher: STALE pid N (heartbeat Xs ago)`.
- The `event()` feed line for a refused start is not needed (it's a CLI refusal, not a bridge event).

**S1.3 `doctor` command.** `bridge.py doctor` prints a table and exits 1 if any row is FAIL. Rows, in this order, each `PASS|WARN|FAIL  <name>  <detail>`:
1. `config` — config.json parses, `enabled` value shown (WARN if false).
2. `state_root` — exists and is writable (create a temp file and delete it).
3. `dispatcher` — lock file state as in S1.2 (`PASS none`, `PASS pid N alive`, `WARN stale`, never FAIL).
4. `exe:<agent>` for each agent — `resolve_exe()` result exists (FAIL if not). Show the resolved path. If it differs from `cfg["exe"]`, WARN with "config path missing; resolved via exe_glob" so Peter knows to update config.
5. `auth:fable` — run `[exe, "--version"]` with a 30 s timeout; PASS if exit 0 (print the version line). FAIL on nonzero or timeout.
6. `auth:astra` — run `[exe, "login", "status"]` 30 s timeout; PASS if exit 0 and output contains "Logged in"; else FAIL with the first output line.
7. `unity` — `_unity_reachable()`; PASS/FAIL. Use the existing `unity_probe` config. If `unity_probe` is missing, WARN "no probe configured".
8. `repo:ptm4`, `repo:dungine` — `git -C <root> rev-parse --is-inside-work-tree` exit 0.
9. `agentcomms` — the `agentcomms` file path exists and is writable.
Environment for 5–7: strip `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` exactly as `_launch` does, and apply `path_prepend` the same way. Reuse; do not copy-paste the env code a third time: extract it into `def _run_env(self) -> dict` and call it from `_launch`, `_unity_reachable`, and `doctor`.

**S1.4 Tests** (append to `test_bridge.py`, follow its `check(name, cond, detail)` style; the runner is `run_all()` and prints `N/N checks pass`):
- `test_13_dispatcher_lock`:
  - fresh Env: `acquire_dispatcher_lock()` → True; file exists with our pid.
  - second Bridge object on the same state root: `acquire_dispatcher_lock()` → False and reason contains "alive".
  - same second object with `force=True` → True, reason contains "forced".
  - write a lock with pid 999999 (not alive) → acquire → True, reason contains "stale" or "replaced".
  - write a lock with our pid but heartbeat 10 minutes old → acquire → True (own pid always re-acquires).
  - `release_dispatcher_lock()` on a lock owned by another pid does **not** delete the file.
- `test_14_doctor_runs`: monkeypatch `Bridge._unity_reachable` to return True and `subprocess.run` for auth rows to a stub returning exit 0 with "Logged in" output; call the doctor function (factor it as `Bridge.doctor() -> list[tuple[str,str,str]]` returning rows, with the CLI printing them) and check that rows include `dispatcher`, `exe:astra`, `exe:fable`, and that no row is FAIL under the dummy config. Keep the dummy agents' `exe` pointing at `sys.executable` as the existing tests do, so `exe:*` rows PASS.
- Existing 16 checks must still pass. Target: **18/18** (or more if you split; state the count).

**S1.5 Runbook.** In `11-dungine-agent-collaboration.md` add to the "Operating it" code block the lines `python tools/bridge/bridge.py doctor` (with comment `# preflight: exes, auth, Editor, repos, dispatcher lock`) and `bridge.py run --force` (comment `# take over a dead dispatcher's lock`), and in the "Protections" table add a row `| Second dispatcher | **Enforced**: dispatcher.lock with pid + heartbeat; a live holder refuses a second run. |`. Change the "Exactly one dispatcher" bullet under "Operating rules learned from the pilot" to say it is now enforced.

**Verify.** `cd homelab/DND.vbeta && python tools/bridge/bridge.py test` → all pass. `python tools/bridge/bridge.py doctor` → paste the table (WARN rows are fine, FAIL rows must be explained). Start `python tools/bridge/bridge.py run --once` twice in two terminals is not possible headless; instead run `run --loops 3` in the background (`Start-Process`) and, while it is alive, run `run --once` in the foreground and paste the refusal line; then wait for the background one to exit and confirm the lock file is gone.

**Outputs / commit list.** `tools/bridge/bridge.py`, `tools/bridge/test_bridge.py`, `homelab/agentic/runbooks/11-dungine-agent-collaboration.md`.

---

### S2. POC HUD: stop the `null texture passed to GUI.DrawTexture` warning flood

**Why.** `PocHud.EnsureStyles()` guards on `_text != null`, but `_white` (a runtime `Texture2D`) is destroyed when Play Mode exits or a domain reload happens, while the `GUIStyle` fields survive. Every `OnGUI` then draws with a destroyed texture: 306,150 warnings in one session and a 2 GB `Logs/Editor.log`.

**Files.** `E:/Unity/Projects/Dungine/Assets/Dungine/POC/PocHud.cs` only.

**S2.1 Code change**, exactly:
- Replace the guard `if (_text != null) return;` with `if (_text != null && _white != null) return;` (Unity's `==`/`!=` on `UnityEngine.Object` reports destroyed objects as null; that is the intended check — do not switch to `ReferenceEquals` or `is null`).
- After creating `_white`, set `_white.hideFlags = HideFlags.HideAndDontSave;` and `_white.name = "PocHud.white";`.
- Add:
  ```csharp
  private void OnDestroy()
  {
      if (_white != null) Destroy(_white);
      _white = null; _text = null;
  }
  ```
- Add a one-line comment above `EnsureStyles` stating why both fields are checked (the texture dies on Play exit / domain reload while the styles survive).
- Do not change anything else in the file (no layout, no colours, no style sizes).

**S2.2 Verification through the Editor.** Preconditions: the Unity Editor is open on Dungine (`unity status` lists it as `ready`; if it does not, stop and ask Peter to open it; do not open it yourself). Prepend `C:/Users/ptm/AppData/Local/Unity/bin` to PATH in your shell. All commands take `--project-path E:/Unity/Projects/Dungine`.
1. `unity command recompile --project-path ...` and wait until `unity command eval --code "return UnityEditor.EditorApplication.isCompiling;"` returns `false`. If the eval result shows compile errors, paste them and stop.
2. Clear the console: `unity command clear_console --project-path ...`.
3. Three times in a row: `unity command editor_play --project-path ...`, wait 8 s (`python -c "import time; time.sleep(8)"`), `unity command editor_stop --project-path ...`, wait 4 s.
4. Read the console counts with this eval (one line):
   `--code "var t=System.Type.GetType(\"UnityEditor.LogEntries,UnityEditor\"); var m=t.GetMethod(\"GetCountsByType\", System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic); var a=new object[]{0,0,0}; m.Invoke(null,a); return $\"errors={a[0]} warnings={a[1]} logs={a[2]}\";"`
   Expected: `errors=0 warnings=0`. If warnings > 0, run `unity command eval --code "return UnityEditor.LogEntries..."` is not available for text; instead read the last 200 lines of `E:/Unity/Projects/Dungine/Logs/Editor.log` and paste any line containing `null texture`. Then stop and ask Peter; do not iterate on the fix.
5. Paste the `errors=/warnings=` line in your final message.

**Outputs / commit list.** `Assets/Dungine/POC/PocHud.cs` (in the Dungine repo).

---

### S3. Engine: world objects and the Interact action (5e 2024 object rules)

**Why.** The POC door is a Unity-side toggle with no cost. The engine must own object
interaction so it follows the 5e action economy and so the AI, netcode and save file see it as
events. This is the engine-side design Fable chose for "sprites interacting with objects":
objects have stat blocks, interacting uses the **free interaction / Utilize action**, forcing
and lockpicking are **ability checks**, and objects can be **attacked**.

**Files.** New: `engine/DND.Engine/Runtime/Model/WorldObject.cs`, `engine/DND.Engine.Tests/ObjectInteractionTests.cs`. Edited: `Runtime/Intents/Intents.cs`, `Runtime/Events/GameEvents.cs`, `Runtime/Combat/Encounter.cs`, `Runtime/Model/Creature.cs`, `docs/engine-architecture.md` (one section).

**Rules being implemented (SRD 5.2 / 2024 unless noted).**
- *Interacting with things around you*: once per turn a creature can interact with one object for free as part of its move or action (open a door, pull a lever). A **second** interaction on the same turn costs the **Utilize** action.
- *Utilize action*: the action used to interact with an object when it is not free.
- *Forcing / picking*: opening a stuck or locked object without the key is a Strength (Athletics) check to force, or a Dexterity (Sleight of Hand) check with **Thieves' Tools** to pick, against the object's DC. Each is an action.
- *Objects* (DMG object rules, unchanged in 2024): AC by material — cloth/paper/rope 11; crystal/glass/ice 13; wood/bone 15; stone 17; iron/steel 19; mithral 21; adamantine 23. Hit points by size and resilience — Tiny fragile 2 / resilient 5; Small 3 / 10; Medium 4 / 18; Large 5 / 27. Objects are **immune to poison and psychic damage**. At 0 HP an object is broken.
- Reach: interacting requires the actor to be within 5 ft (adjacent cell, Chebyshev 1, same elevation for v0.1).

**S3.1 Model** — `Runtime/Model/WorldObject.cs`:
```csharp
namespace DND.Engine.Model
{
    public enum ObjectKind { Door, Chest, Lever, Other }
    public enum ObjectMaterial { Cloth, Crystal, Wood, Stone, Iron, Mithral, Adamantine }
    public enum ObjectSize { Tiny, Small, Medium, Large }
    public enum ObjectState { Open, Closed, Locked, Broken }

    public sealed class ObjectTemplate
    {
        public string Id = "";
        public string Name = "";
        public string Ruleset = "2024";
        public ObjectKind Kind = ObjectKind.Other;
        public ObjectMaterial Material = ObjectMaterial.Wood;
        public ObjectSize Size = ObjectSize.Medium;
        public bool Fragile;                    // false = resilient
        public int? LockDc;                     // null = no lock. Applies to PickLock and ForceOpen when Locked.
        public int? StuckDc;                    // null = not stuck. Applies to ForceOpen when Closed (not locked).
        public bool BlocksMovementWhenClosed = true;
        public bool BlocksSightWhenClosed = true;
        public int ArmorClass => Material switch { ObjectMaterial.Cloth => 11, ObjectMaterial.Crystal => 13, ObjectMaterial.Wood => 15, ObjectMaterial.Stone => 17, ObjectMaterial.Iron => 19, ObjectMaterial.Mithral => 21, _ => 23 };
        public int MaxHp => (Size, Fragile) switch { (ObjectSize.Tiny, true) => 2, (ObjectSize.Tiny, false) => 5, (ObjectSize.Small, true) => 3, (ObjectSize.Small, false) => 10, (ObjectSize.Medium, true) => 4, (ObjectSize.Medium, false) => 18, (ObjectSize.Large, true) => 5, _ => 27 };
    }

    public sealed class WorldObject
    {
        public readonly string Id;
        public readonly ObjectTemplate Template;
        public GridPos Cell;
        public ObjectState State;
        public int Hp;
        public WorldObject(string id, ObjectTemplate template, GridPos cell, ObjectState initial) { Id = id; Template = template; Cell = cell; State = initial; Hp = template.MaxHp; }
        public bool IsBroken => State == ObjectState.Broken;
        public bool BlocksMovement => !IsBroken && State != ObjectState.Open && Template.BlocksMovementWhenClosed;
        public bool BlocksSight => !IsBroken && State != ObjectState.Open && Template.BlocksSightWhenClosed;
    }
}
```
Add `using DND.Engine.Core;` for `GridPos`. Values above are fixed; do not "improve" them.

**S3.2 Creature proficiencies** — in `CreatureTemplate` add
`public HashSet<string> SkillProficiencies = new HashSet<string>();` and
`public HashSet<string> ToolProficiencies = new HashSet<string>();` (skill names lower-case
as in the SRD: "athletics", "sleight of hand"; tool: "thieves' tools"). Add to `Creature`:
`public int SkillMod(Ability ability, string skill) => Template.Abilities.Mod(ability) + (Template.SkillProficiencies.Contains(skill) ? Template.ProficiencyBonus : 0);`
and `public int StrMod => Template.Abilities.Mod(Ability.Str);`.

**S3.3 Intents** — append to `Intents.cs`:
```csharp
public enum Interaction { Open, Close, ForceOpen, PickLock }
public sealed class InteractIntent : Intent { public readonly string ObjectId; public readonly Interaction Kind; public InteractIntent(string actorId, string objectId, Interaction kind) : base(actorId) { ObjectId = objectId; Kind = kind; } }
public sealed class AttackObjectIntent : Intent { public readonly string ObjectId; public readonly int AttackIndex; public AttackObjectIntent(string actorId, string objectId, int attackIndex = 0) : base(actorId) { ObjectId = objectId; AttackIndex = attackIndex; } }
```

**S3.4 Events** — append to `GameEvents.cs` (same style as existing events; `Describe()` texts exactly as given so replay fingerprints are stable):
- `ObjectStateChanged(string objectId, ObjectState from, ObjectState to, string byId, string cost)` → `"{byId} {verb} {objectId} ({cost})"` where verb = `"opens"` if to==Open, `"closes"` if to==Closed, `"unlocks"` if from==Locked && to==Closed, `"breaks"` if to==Broken. `cost` is one of `"free"`, `"action"`, `"damage"`.
- `ObjectCheckRolled(string actorId, string objectId, Interaction kind, string skill, D20Result roll, int dc, bool success)` → `"{actorId} {kind} {objectId}: {skill} {roll} vs DC {dc} => {(success ? "success" : "failure")}"`.
- `ObjectDamaged(string sourceId, string objectId, int amount, string damageType, int hpAfter)` → `"{objectId} takes {amount} {damageType} (HP {hpAfter})"`.
- `ObjectAttackRolled(string attackerId, string objectId, string attackName, D20Result roll, int ac, bool hit, bool crit)` → same text shape as `AttackRolled` with the object id.

**S3.5 Encounter changes** (`Encounter.cs`):
- Registry: `private readonly Dictionary<string, WorldObject> _objects` + `public IReadOnlyCollection<WorldObject> Objects`, `public WorldObject AddObject(WorldObject o)` (throws on duplicate id, like `Add`), `public WorldObject? GetObject(string id)`, `public WorldObject? ObjectAt(GridPos cell)`.
- Blocking: add `public bool IsBlocked(GridPos cell) => Field.IsBlocked(cell) || (ObjectAt(cell)?.BlocksMovement ?? false);` and `public bool BlocksSight(GridPos cell) => (ObjectAt(cell)?.BlocksSight ?? false);` (sight through terrain is 03b; leave `IBattlefield` unchanged). `HandleMove` must use `IsBlocked(m.To)` instead of `Field.IsBlocked(m.To)`.
- Economy: add `public bool FreeInteractionAvailable { get; private set; }`, set true in `AdvanceTurn` next to `ActionAvailable = true`.
- `Handle` switch: add `InteractIntent i => HandleInteract(actor, i)`, `AttackObjectIntent ao => HandleAttackObject(actor, ao)`.
- `HandleInteract(actor, i)`, checks in this order, each a `RuleResult.Reject(rule, why)`:
  1. `"object"`: unknown object id.
  2. `"object"`: object is Broken → "…is broken".
  3. `"reach"`: `GridPos.Cells(actor.Position, obj.Cell) != 1` → "{objectId} is {feet} ft away; you must be within 5 ft".
  4. Per kind:
     - **Open**: state must be Closed (Locked → reject `"locked"`: "…is locked; force it or pick the lock"; Open → reject `"object"`: "already open"). Cost: if `FreeInteractionAvailable` → consume it, cost="free"; else if `ActionAvailable` → consume it, cost="action"; else reject `"action-economy"`: "free interaction and action both used this turn". Then state=Open, append `ObjectStateChanged(..., "free"/"action")`.
     - **Close**: state must be Open (else reject `"object"`: "not open"). If `OccupantAt(obj.Cell) != null` → reject `"occupied"`: "{creature} is standing in the doorway". Cost as for Open. State=Closed.
     - **ForceOpen**: state must be Closed with `StuckDc != null`, or Locked with `LockDc != null`; otherwise reject `"object"`: "nothing to force" (a plain closed door is just opened). Requires `ActionAvailable` (reject `"action-economy"`); consume the action **before rolling** (a failed check still spends it). Roll `D20Test.Roll(Rng, actor.SkillMod(Ability.Str, "athletics"))`; dc = LockDc if Locked else StuckDc; success = `D20Test.MeetsDc`. Append `ObjectCheckRolled(..., "Strength (Athletics)", roll, dc, success)`. On success: state=Open and append `ObjectStateChanged(from, Open, actor, "action")`. On failure: nothing else.
     - **PickLock**: state must be Locked (else reject `"object"`: "not locked"). Actor must have `"thieves' tools"` in `ToolProficiencies` (else reject `"tools"`: "requires thieves' tools"). Requires and consumes the action before rolling. Roll Dex + "sleight of hand" vs LockDc; append `ObjectCheckRolled(..., "Dexterity (Sleight of Hand)", …)`. Success: state=Closed (unlocked, still shut) and `ObjectStateChanged(Locked, Closed, actor, "action")`.
- `HandleAttackObject(actor, ao)`: mirror `HandleAttack` but: target is an object (unknown → reject `"object"`); Broken → reject; reach check against `obj.Cell`; consume action; roll vs `Template.ArmorClass`; append `ObjectAttackRolled`. On hit: damage as in `HandleAttack`; **if `atk.DamageType` is `"poison"` or `"psychic"` the amount is 0** (immunity) but the `ObjectDamaged` event is still appended with amount 0; `obj.Hp = Math.Max(0, obj.Hp - amount)`; append `ObjectDamaged`; if `obj.Hp == 0`: previous state → `Broken`, append `ObjectStateChanged(prev, Broken, actor.Id, "damage")`. Broken objects never block movement or sight (already true via `IsBroken`).
- No opportunity attacks, no AI, no LoS algorithm here (03b/08).

**S3.6 Tests** — `ObjectInteractionTests.cs`, xUnit, seeded `SeededRng`, helpers `WoodenDoor()` (Door, Wood, Medium, resilient → AC 15, HP 18) and `IronChest(lockDc: 15)` (Chest, Iron, Small, resilient → AC 19, HP 10), a fighter with `SkillProficiencies {"athletics"}` and a rogue with `ToolProficiencies {"thieves' tools"}` and `SkillProficiencies {"sleight of hand"}`. Build an encounter with the actor adjacent to the object unless the test says otherwise; use a two-creature party-vs-enemy setup so the encounter does not end. Test names and what they assert:
1. `Open_ClosedDoor_UsesFreeInteraction_ThenActionStillAvailable` — after Open: `FreeInteractionAvailable == false`, `ActionAvailable == true`, last event `ObjectStateChanged` with cost "free", `Describe()` equals `"F opens door (free)"`.
2. `SecondInteraction_SameTurn_ConsumesAction` — Open then Close: second event cost "action", `ActionAvailable == false`.
3. `ThirdInteraction_SameTurn_Rejected_ActionEconomy` — Open, Close, Open → third rejected, reason starts with `"action-economy:"`.
4. `Interact_NotAdjacent_Rejected_Reach` — actor 2 cells away → `"reach:"`.
5. `Close_OccupiedCell_Rejected` — a creature standing on the door cell → `"occupied:"`; door stays Open.
6. `ClosedDoor_BlocksMovement_OpenDoor_DoesNot` — `IsBlocked(doorCell)` true while Closed, false after Open; a `MoveIntent` into the closed door cell is rejected `"movement:"`.
7. `ClosedDoor_BlocksSight_OpenDoor_DoesNot` — `BlocksSight(doorCell)`.
8. `Open_LockedDoor_Rejected_Locked` — `"locked:"`.
9. `ForceOpen_SpendsAction_EvenOnFailure` — pick a seed where the roll fails (search seeds 1..50 in the test until `ObjectCheckRolled.Success == false`; assert one was found), `ActionAvailable == false`, state unchanged.
10. `ForceOpen_Success_OpensAndLogsCheck` — seed where it succeeds; events end with `ObjectCheckRolled(success)` then `ObjectStateChanged(Locked→Open, "action")`.
11. `PickLock_WithoutTools_Rejected` — fighter → `"tools:"`.
12. `PickLock_Success_UnlocksButStaysClosed` — rogue, succeeding seed; state Closed; `Describe()` of the state event is `"R unlocks chest (action)"`.
13. `AttackObject_Hit_ReducesHp_PoisonDoesNothing` — attack with a `"slashing"` attack reduces HP; a `"poison"` attack that hits appends `ObjectDamaged` with amount 0 and HP unchanged.
14. `AttackObject_ToZero_Breaks_AndStopsBlocking` — repeat attacks (advance turns as needed with `EndTurnIntent` for both creatures) until HP 0; assert `ObjectStateChanged(to Broken, "damage")`, `IsBlocked(cell) == false`, `BlocksSight(cell) == false`, and a further `InteractIntent` is rejected `"object:"` (broken).
15. `Replay_SameSeedSameIntents_SameFingerprint` — run a script of 8 intents including interactions and an object attack twice with the same seed; `Log.Fingerprint()` equal.
16. `FreeInteraction_ResetsEachTurn` — Open on turn 1 (free), end turn, other creature ends turn, Close on turn 2 → cost "free" again.
All existing tests (31) stay green. Target: **47** passing.

**S3.7 Docs.** Add section "3b. Objects and interaction (v0.2)" to `docs/engine-architecture.md` after §3: five sentences covering free interaction vs Utilize, checks for force/pick, object AC/HP tables by reference to `ObjectTemplate`, immunity, and that broken objects stop blocking. Update the README index row for plan 03 to append "; objects + Interact action (S3, 2026-09-xx)".

**Verify.** `cd homelab/DND.vbeta/engine && dotnet test` → paste the `Passed! - Failed: 0, Passed: 47` line (or the true count). Also `dotnet build engine/DND.Engine/DND.Engine.csproj -c Release` warns 0 errors (the Unity compile of the same sources is checked by Fable later).

**Outputs / commit list.** The five engine files, the test file, `docs/engine-architecture.md`, `Plans/README.md`.

---

### S4. Plan 03a: SRD data ingest (`tools/ingest_srd.py`)

**Why.** The engine is data-driven and nothing has been ingested. This produces the
ruleset-tagged JSON that Fable's loader design (next Fable session) will read. All sources are
confirmed in `SOURCES.md`; only the SRD documents may be ingested.

**Files.** New: `tools/ingest_srd.py`, `tools/validate_rules.py`, `content/rules/2024/*.json`, `content/rules/2014/*.json`, `content/rules/manifest.json`, `content/rules/LICENSES.md`, `content/rules/coverage.md`. Edited: `Plans/Rules/03a-data-ingest.md` (status → done, plus a "How it ran" section), `Plans/README.md` row 03a.

**S4.1 Source discovery (do exactly this, in order; stop and ask Peter at the first "ask").**
1. 5e-database on GitHub. Fetch `https://api.github.com/repos/5e-bits/5e-database/git/trees/main?recursive=1` (stdlib `urllib`, User-Agent header set to `dungine-ingest/1.0`). Collect blob paths matching `src/2014/5e-SRD-*.json` and `src/2024/5e-SRD-*.json`. Record the tree SHA and the `main` commit SHA (`.../commits/main` → `sha`).
2. If **no** `src/2024/` files exist: try Open5e v2, `https://api.open5e.com/v2/documents/` and look for a document whose `key` is `srd-2024` (or name contains "SRD 5.2"). If that exists, 2024 data comes from Open5e v2 endpoints filtered with `document__key=<that key>` (`/v2/creatures/`, `/v2/spells/`, `/v2/conditions/`, `/v2/items/`, `/v2/classes/`, `/v2/species/`, `/v2/backgrounds/`; paginate via `next`). If neither source has 2024 data: **ask Peter** with the two findings; do not ingest 2014 only.
3. 2014 data always comes from 5e-database `src/2014/` (its shape is stable and well known). Do not use Open5e for 2014.
4. Do not fetch anything that is not an SRD document. Never fetch from wikidot or 5e.tools (see `SOURCES.md`).

**S4.2 Kinds and files.** Ingest these kinds; the output file per kind is `content/rules/<ruleset>/<kind>.json`:
`monsters`, `spells`, `conditions`, `equipment`, `classes`, `species` (2014 calls them "races": map to `species`), `backgrounds`, `skills`, `damage-types`. Skip everything else in this batch (feats, magic items, subclasses, rules text) — list what was skipped in `coverage.md`.

**S4.3 Record envelope** (every record in every file):
```json
{
  "id": "goblin",                       // slug: lower-case, ASCII, hyphens; from the source index/slug
  "kind": "monster",                    // singular of the file kind
  "ruleset": "2024",                    // or "2014"
  "name": "Goblin",
  "source": "5e-database@<commit sha>", // or "open5e-v2@<document key>"
  "source_url": "<raw file url or api url>",
  "license": "CC-BY-4.0",
  "attribution": "SRD 5.2.1 (Wizards of the Coast) via 5e-database", // matches LICENSES.md
  "data": { ... normalized ... },
  "raw": { ... the untouched source record ... }
}
```
`data` per kind (missing values are `null`, never invented):
- **monster**: `size`, `type`, `alignment`, `armor_class` (int; 5e-database gives a list, take the first `value`), `hit_points` (average int), `hit_dice` ("7d8+7" string if present), `speed_ft` (object walk/fly/swim/climb/burrow ints, parse "30 ft."), `abilities` {str,dex,con,int,wis,cha}, `proficiency_bonus` (if absent derive from CR: CR 0-4 → 2, 5-8 → 3, 9-12 → 4, 13-16 → 5, 17-20 → 6, 21-24 → 7, 25-28 → 8, 29-30 → 9), `challenge_rating` (float), `xp`, `saving_throws` {ability: bonus}, `skills` {name: bonus}, `senses`, `languages`, `damage_immunities`/`resistances`/`vulnerabilities` (lists), `condition_immunities` (list of names), `attacks`: list of `{name, attack_bonus (int), reach_ft (int|null), range_ft ([normal,long]|null), damage: [{dice:"1d6+2", type:"slashing"}], description}` parsed from the source's `actions` where an entry has an attack bonus; `actions` (all, as `{name, desc}`), `traits`, `legendary_actions`.
- **spell**: `level` (int), `school`, `casting_time`, `range`, `components` (list), `material`, `duration`, `concentration` (bool), `ritual` (bool), `classes` (list of class slugs), `description` (text, paragraphs joined by "\n\n"), `higher_level`, `damage` (if present: `{type, at_slot_level: {level: dice}}`), `dc` (if present: `{ability, success}`), `area` (if present: `{type, size_ft}`).
- **condition**: `description`.
- **equipment**: `category`, `cost` {quantity, unit}, `weight_lb`, `weapon` (if weapon: `{category, range_class, damage:{dice,type}, two_handed_damage, range_ft:[normal,long]|null, properties:[...]}`), `armor` (if armor: `{category, base_ac, dex_bonus (bool), max_dex_bonus, str_minimum, stealth_disadvantage}`), `description`.
- **class**: `hit_die`, `proficiency_choices` (raw), `proficiencies` (list), `saving_throws` (list), `starting_equipment` (raw), `spellcasting` (raw or null), `subclasses` (names).
- **species**: `speed_ft`, `size`, `ability_bonuses` (list of {ability, bonus}), `traits` (names), `languages`, `description`.
- **background**, **skill**, **damage-type**: `description` plus the source's obvious scalar fields (skill: `ability`).

**S4.4 Determinism and idempotence.** Records sorted by `id`; JSON written with `indent=2`, `ensure_ascii=False`, `sort_keys=True`, trailing newline. Running the script twice with the same upstream commit must produce byte-identical files (the test in S4.7 checks this). The script caches downloads in `tools/.ingest-cache/` (gitignored: add the line to `homelab/DND.vbeta/.gitignore`) keyed by URL sha256, with `--refresh` to bypass.

**S4.5 Manifest and licenses.**
- `content/rules/manifest.json`: `{ "generated": "<iso utc>", "tool": "ingest_srd.py <version>", "sources": [{name, commit_or_key, fetched_at, url}], "files": [{path, sha256, records}] }`.
- `content/rules/LICENSES.md`: the two CC-BY-4.0 attribution statements, verbatim:
  - "This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode."
  - "This work includes material from the System Reference Document 5.1 (“SRD 5.1”) by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode."
  - plus one line naming 5e-database (MIT for code; data under the SRD terms) and, if used, Open5e (link to its license page). Note in the file that this text must appear in the game's credits screen (Plan 11) and in the build's `THIRD-PARTY.md` (Plan 14).
- If the 2024 source turns out to be SRD 5.2 (not 5.2.1), keep the version string the source states; do not guess.

**S4.6 `coverage.md`.** Generated by the script: a table per kind with counts for 2024 and 2014 and the count of 2014 records whose `id` has **no** 2024 counterpart (the fallback set), then two lists: monsters with CR ≤ 5 and spells of level ≤ 3, each row `id | 2024 yes/no | 2014 yes/no`. Then "Skipped kinds" and "Parse warnings" (records where an attack could not be parsed, with the monster id and action name).

**S4.7 `tools/validate_rules.py`.** Reads every file under `content/rules/`, checks: envelope fields present and non-empty; `ruleset` ∈ {2024, 2014}; `license` == "CC-BY-4.0"; `id` unique within a file; monster `abilities` has all six ints 1..30; monster `armor_class` int; spell `level` 0..9; manifest sha256s match the files. Exit 1 with a list of problems, else prints `OK <n files> <m records>`. Add a `--twice` mode to `ingest_srd.py` used by you for the idempotence check: run, hash all outputs, run again, compare, print `IDEMPOTENT` or the differing paths.

**S4.8 CLI.** `python tools/ingest_srd.py [--refresh] [--kinds monsters,spells] [--out content/rules]`. Version constant `1.0.0`. Log one line per fetched URL and per written file. No other output.

**Verify and paste:** the source-discovery result (which 2024 source was used and its commit/key), `validate_rules.py` output, the `IDEMPOTENT` line, and the count table from `coverage.md`. If total size of `content/rules/` exceeds 40 MB, stop and ask Peter before committing (raw copies may need to be dropped).

**Outputs / commit list.** `tools/ingest_srd.py`, `tools/validate_rules.py`, `.gitignore`, `content/rules/**`, `Plans/Rules/03a-data-ingest.md`, `Plans/README.md`.

---

### S5. Housekeeping

1. Run `python homelab/agentic/probe.py --wire claude` from `E:/REPO/ptm4` so the runbook edits from S1 are materialized; paste the drift summary.
2. `Plans/README.md`: set plan 16 row to `in-progress` when you start and `done` when S1–S4 are verified; update rows 03 and 03a as S3/S4 say.
3. Final message: for each task, the verification lines you pasted and the commit list, merged into one list for the ptm4 repo and one for the Dungine repo.

---

## What Fable will do with the results

- Review S3 in Unity: compile the engine package in the Editor and wire the POC door to
  `InteractIntent` (or hand that to Astra through the bridge as a task).
- Design the JSON → `CreatureTemplate` loader (no System.Text.Json) on top of S4's envelope,
  then write batch 02 (03b core mechanics: cover, LoS, opportunity attacks, death saves,
  difficult terrain; 03d conditions) in this same format.
- Register the Astra tasks listed in Part A through the bridge once S1 is in.
