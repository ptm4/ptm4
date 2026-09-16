using System;
using System.Collections.Generic;
using System.Linq;
using DND.Engine.Core;
using DND.Engine.Events;
using DND.Engine.Intents;
using DND.Engine.Model;
using DND.Engine.Rules;

namespace DND.Engine.Combat
{
    /// <summary>Terrain for v0.2: which cells block movement/sight, which are difficult, and cover.</summary>
    public interface IBattlefield
    {
        bool IsBlocked(GridPos cell);          // terrain that stops movement
        bool BlocksSight(GridPos cell);        // terrain that stops sight (walls, closed doors are objects, not terrain)
        bool IsDifficult(GridPos cell);        // difficult terrain: each foot costs 2 (SRD "Difficult Terrain")
        int CoverBonus(GridPos from, GridPos to);  // 0, 2 (half cover) or 5 (three-quarters); total cover = BlocksSight
    }

    public sealed class OpenField : IBattlefield
    {
        public bool IsBlocked(GridPos cell) => false;
        public bool BlocksSight(GridPos cell) => false;
        public bool IsDifficult(GridPos cell) => false;
        public int CoverBonus(GridPos from, GridPos to) => 0;
    }

    /// <summary>A battlefield described by cell sets: walls (block movement and sight), difficult terrain,
    /// and per-cell cover bonuses (granted to a creature standing IN that cell against an attacker outside it).</summary>
    public sealed class GridField : IBattlefield
    {
        public readonly HashSet<GridPos> Walls = new HashSet<GridPos>();
        public readonly HashSet<GridPos> Difficult = new HashSet<GridPos>();
        public readonly Dictionary<GridPos, int> Cover = new Dictionary<GridPos, int>();

        public bool IsBlocked(GridPos cell) => Walls.Contains(cell);
        public bool BlocksSight(GridPos cell) => Walls.Contains(cell);
        public bool IsDifficult(GridPos cell) => Difficult.Contains(cell);
        public int CoverBonus(GridPos from, GridPos to) => Cover.TryGetValue(to, out var bonus) ? bonus : 0;
    }

    /// <summary>
    /// The combat state machine: initiative, turns, action economy, and the rules that decide
    /// whether an intent becomes events. v0.2 adds difficult terrain, opportunity attacks, ranged
    /// attacks, cover, line of sight, advantage/disadvantage, and death saves (03b).
    /// </summary>
    public sealed class Encounter
    {
        public readonly EventLog Log = new EventLog();
        public readonly IRng Rng;
        public readonly IBattlefield Field;
        private readonly Dictionary<string, Creature> _byId = new Dictionary<string, Creature>();
        private readonly List<Creature> _creatures = new List<Creature>();
        private readonly Dictionary<string, WorldObject> _objects = new Dictionary<string, WorldObject>();
        private bool _deathSaveRolledThisTurn;

        public IReadOnlyList<Creature> Creatures => _creatures;
        public IReadOnlyCollection<WorldObject> Objects => _objects.Values;
        public IReadOnlyList<Creature> Order { get; private set; } = Array.Empty<Creature>();
        public int Round { get; private set; }
        public int TurnIndex { get; private set; } = -1;
        public bool Started => Round > 0;
        public bool Finished { get; private set; }

        // Per-turn economy
        public int MovementLeftFeet { get; private set; }
        public bool ActionAvailable { get; private set; }
        public bool BonusActionAvailable { get; private set; }
        public bool FreeInteractionAvailable { get; private set; }
        public bool Dashed { get; private set; }
        public bool Disengaged { get; private set; }

        public Creature? Current => TurnIndex >= 0 && TurnIndex < Order.Count ? Order[TurnIndex] : null;

        public Encounter(IRng rng, IBattlefield? field = null)
        {
            Rng = rng;
            Field = field ?? new OpenField();
        }

        public Creature Add(Creature c)
        {
            if (_byId.ContainsKey(c.Id)) throw new ArgumentException($"duplicate creature id {c.Id}");
            _byId[c.Id] = c;
            _creatures.Add(c);
            return c;
        }

        public Creature? Get(string id) => _byId.TryGetValue(id, out var c) ? c : null;
        public Creature? OccupantAt(GridPos p) => _creatures.FirstOrDefault(c => !c.IsDead && c.Position == p);

        public WorldObject AddObject(WorldObject o)
        {
            if (_objects.ContainsKey(o.Id)) throw new ArgumentException($"duplicate object id {o.Id}");
            _objects[o.Id] = o;
            return o;
        }

        public WorldObject? GetObject(string id) => _objects.TryGetValue(id, out var o) ? o : null;
        public WorldObject? ObjectAt(GridPos cell) => _objects.Values.FirstOrDefault(o => o.Cell == cell);

        /// <summary>True if the cell is blocked by terrain or by a closed/locked object occupying it.</summary>
        public bool IsBlocked(GridPos cell) => Field.IsBlocked(cell) || (ObjectAt(cell)?.BlocksMovement ?? false);

        /// <summary>True if terrain or an object occupying the cell blocks sight.</summary>
        public bool BlocksSight(GridPos cell) => Field.BlocksSight(cell) || (ObjectAt(cell)?.BlocksSight ?? false);

        /// <summary>SRD: cell-center sight on the X/Z plane; a wall/closed object blocks it (D31/03b).</summary>
        public bool HasLineOfSight(GridPos a, GridPos b) => LineOfSight.HasLineOfSight(a, b, BlocksSight);

        /// <summary>SRD: initiative = d20 + Dex mod. Ties: higher Dex score first, then insertion order (table decides; we make it deterministic).</summary>
        public void Start()
        {
            if (Started) throw new InvalidOperationException("already started");
            foreach (var c in _creatures) c.Initiative = D20Test.Roll(Rng, c.DexMod).Total;
            Order = _creatures
                .Select((c, i) => (c, i))
                .OrderByDescending(t => t.c.Initiative)
                .ThenByDescending(t => t.c.Template.Abilities.Dex)
                .ThenBy(t => t.i)
                .Select(t => t.c).ToList();
            Log.Append(new InitiativeRolled(Order.Select(c => (c.Id, c.Initiative)).ToList()));
            Round = 1;
            Log.Append(new RoundStarted(Round));
            TurnIndex = -1;
            AdvanceTurn();
        }

        public RuleResult Handle(Intent intent)
        {
            if (!Started) return RuleResult.Reject("encounter", "not started");
            if (Finished) return RuleResult.Reject("encounter", "already over");
            // A creature that died during its own turn (or out of band) cannot act or end its turn:
            // the engine yields for it. Dead creatures never hold the turn.
            while (Current != null && Current.IsDead && !Finished)
            {
                CheckEnd();
                if (Finished) return RuleResult.Reject("encounter", "already over");
                Log.Append(new TurnEnded(Current.Id));
                AdvanceTurn();
            }
            var actor = Get(intent.ActorId);
            if (actor == null) return RuleResult.Reject("actor", $"unknown creature {intent.ActorId}");
            if (actor != Current) return RuleResult.Reject("turn-order", $"it is {Current!.Id}'s turn, not {actor.Id}'s");
            if (actor.IsDead) return RuleResult.Reject("dead", "dead creatures do not act");
            var alwaysLegal = intent is EndTurnIntent || intent is DeathSaveIntent;
            if (actor.Hp <= 0 && !alwaysLegal)
                return RuleResult.Reject("unconscious", "unconscious creatures cannot act");
            if (IsIncapacitated(actor) && !alwaysLegal)
                return RuleResult.Reject("incapacitated", $"{actor.Id} is incapacitated and cannot take actions, bonus actions, or reactions");

            return intent switch
            {
                MoveIntent m => HandleMove(actor, m),
                AttackIntent a => HandleAttack(actor, a),
                EndTurnIntent => HandleEndTurn(actor),
                InteractIntent i => HandleInteract(actor, i),
                AttackObjectIntent ao => HandleAttackObject(actor, ao),
                DashIntent => HandleDash(actor),
                DisengageIntent => HandleDisengage(actor),
                DodgeIntent => HandleDodge(actor),
                DeathSaveIntent => HandleDeathSave(actor),
                StandUpIntent => HandleStandUp(actor),
                _ => RuleResult.Reject("intent", $"unsupported intent {intent.GetType().Name}"),
            };
        }

        private RuleResult HandleMove(Creature actor, MoveIntent m)
        {
            if (actor.Has(Condition.Grappled)) return RuleResult.Reject("grappled", $"{actor.Id} is grappled (speed 0)");
            if (actor.Has(Condition.Restrained)) return RuleResult.Reject("restrained", $"{actor.Id} is restrained (speed 0)");
            var cells = GridPos.Cells(actor.Position, m.To);
            if (cells == 0) return RuleResult.Reject("movement", "already there");
            if (cells != 1) return RuleResult.Reject("movement", "v0.1 moves one cell per intent; send a path as single steps");
            if (IsBlocked(m.To)) return RuleResult.Reject("movement", $"{m.To} is blocked");
            if (OccupantAt(m.To) != null) return RuleResult.Reject("movement", $"{m.To} is occupied");

            var fearSource = actor.Conditions.FirstOrDefault(ac => ac.Kind == Condition.Frightened);
            if (fearSource != null)
            {
                var source = Get(fearSource.SourceId);
                if (source != null && GridPos.Cells(m.To, source.Position) < GridPos.Cells(actor.Position, source.Position))
                    return RuleResult.Reject("frightened", $"{actor.Id} cannot willingly move closer to what it fears");
            }

            var multiplier = 1 + (Field.IsDifficult(m.To) ? 1 : 0) + (actor.Has(Condition.Prone) ? 1 : 0); // SRD "Difficult Terrain" / "Being Prone" (crawling): each is an extra foot per foot moved.
            var cost = GridPos.Feet(actor.Position, m.To) * multiplier;
            if (cost > MovementLeftFeet) return RuleResult.Reject("movement", $"needs {cost} ft, {MovementLeftFeet} ft left");

            CheckOpportunityAttacks(actor, m.To);
            if (actor.IsDead) return RuleResult.Ok(); // the move is cancelled; an opportunity attack killed the mover

            var from = actor.Position;
            actor.Position = m.To;
            MovementLeftFeet -= cost;
            Log.Append(new Moved(actor.Id, from, m.To, cost, MovementLeftFeet));
            return RuleResult.Ok();
        }

        /// <summary>SRD "Opportunity Attacks": before actor moves out of a hostile's reach, that hostile
        /// (with a reaction and a melee attack, and not incapacitated) gets one free attack, unless actor Disengaged.</summary>
        private void CheckOpportunityAttacks(Creature actor, GridPos destination)
        {
            if (Disengaged) return;
            foreach (var h in Order)
            {
                if (actor.IsDead) return;
                if (h == actor || h.Side == actor.Side || h.IsDead || !h.ReactionAvailable) continue;
                if (IsIncapacitated(h)) continue;
                var melee = h.Template.Attacks.FirstOrDefault(a => !a.IsRanged);
                if (melee == null) continue;
                var reachCells = melee.ReachFeet / GridPos.FeetPerCell;
                if (GridPos.Cells(h.Position, actor.Position) > reachCells) continue;   // not currently within reach
                if (GridPos.Cells(h.Position, destination) <= reachCells) continue;      // destination still within reach

                h.ReactionAvailable = false;
                Log.Append(new OpportunityAttack(h.Id, actor.Id));
                ResolveAttack(h, actor, melee);
            }
        }

        private RuleResult HandleAttack(Creature actor, AttackIntent a)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            var target = Get(a.TargetId);
            if (target == null) return RuleResult.Reject("target", $"unknown creature {a.TargetId}");
            if (target.IsDead) return RuleResult.Reject("target", $"{target.Id} is already dead");
            if (a.AttackIndex < 0 || a.AttackIndex >= actor.Template.Attacks.Count) return RuleResult.Reject("attack", "no such attack");
            var atk = actor.Template.Attacks[a.AttackIndex];

            var conditionRejection = CheckAttackConditions(actor, target);
            if (conditionRejection != null) return conditionRejection.Value;

            var feet = GridPos.Feet(actor.Position, target.Position);
            var rangedDisadvantage = false;
            if (atk.IsRanged)
            {
                if (feet > atk.LongRangeFeet) return RuleResult.Reject("reach", $"{target.Id} is {feet} ft away, long range is {atk.LongRangeFeet} ft");
                if (feet > atk.RangeFeet) rangedDisadvantage = true;
                if (ThreatenedInMelee(actor)) rangedDisadvantage = true;
            }
            else
            {
                if (feet > atk.ReachFeet) return RuleResult.Reject("reach", $"{target.Id} is {feet} ft away, reach is {atk.ReachFeet} ft");
            }
            if (!HasLineOfSight(actor.Position, target.Position)) return RuleResult.Reject("line-of-sight", $"no line of sight to {target.Id}");

            ActionAvailable = false;
            ResolveAttack(actor, target, atk, rangedDisadvantage);
            return RuleResult.Ok();
        }

        /// <summary>True if a hostile (not dead) is within 5 ft of c (SRD "Ranged Attacks in Close Combat").</summary>
        private bool ThreatenedInMelee(Creature c) => Order.Any(h => h != c && h.Side != c.Side && !h.IsDead && GridPos.Cells(h.Position, c.Position) == 1);

        /// <summary>Rolls, resolves hit/miss, applies damage and death for one attack. Shared by AttackIntent and opportunity attacks.</summary>
        private void ResolveAttack(Creature attacker, Creature target, AttackTemplate atk, bool extraDisadvantage = false)
        {
            var (condAdv, condDis) = AttackModifiers(attacker, target, atk.IsRanged);
            var adv = condAdv;
            var dis = condDis || extraDisadvantage || target.Dodging;
            var mode = ResolveMode(adv, dis);
            var effectiveAc = target.ArmorClass + Field.CoverBonus(attacker.Position, target.Position);
            var roll = D20Test.Roll(Rng, atk.AttackBonus + ExhaustionPenalty(attacker), mode);
            var hit = D20Test.AttackHits(roll, effectiveAc);
            var crit = hit && (roll.IsNat20 || AutoCrit(target, attacker));
            Log.Append(new AttackRolled(attacker.Id, target.Id, atk.Name, roll, effectiveAc, hit, crit));
            if (hit)
            {
                var dmg = (crit ? atk.Damage.Doubled() : atk.Damage).Roll(Rng);
                var amount = target.Has(Condition.Petrified) ? 0 : Math.Max(0, dmg.Total); // SRD "Petrified": immune to all damage
                DealDamage(attacker, target, amount, atk.DamageType, dmg.Dice, crit);
            }
        }

        /// <summary>Applies damage and the SRD death-and-dying consequences for a Party creature at or reaching 0.</summary>
        private void DealDamage(Creature source, Creature target, int amount, string damageType, IReadOnlyList<int> dice, bool crit)
        {
            var hpBefore = target.Hp;
            var wasDying = target.Side == Side.Party && hpBefore <= 0 && !target.IsDead;
            target.ApplyDamage(amount, out var overkill);
            Log.Append(new DamageDealt(source.Id, target.Id, amount, damageType, dice, target.Hp));

            if (target.Side == Side.Party && !target.IsDead)
            {
                if (wasDying)
                {
                    target.DeathFailures = Math.Min(3, target.DeathFailures + (crit ? 2 : 1));
                }
                else if (hpBefore > 0 && target.Hp == 0 && overkill >= target.Template.MaxHp)
                {
                    target.DeathFailures = 3; // SRD "Instant Death": massive damage
                }
            }

            if (target.IsDead)
            {
                Log.Append(new CreatureDied(target.Id));
                CheckEnd();
            }
        }

        private RuleResult HandleDash(Creature actor)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            ActionAvailable = false;
            MovementLeftFeet += actor.SpeedFeet;
            Dashed = true;
            Log.Append(new ActionTaken(actor.Id, "Dash"));
            return RuleResult.Ok();
        }

        private RuleResult HandleDisengage(Creature actor)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            ActionAvailable = false;
            Disengaged = true;
            Log.Append(new ActionTaken(actor.Id, "Disengage"));
            return RuleResult.Ok();
        }

        private RuleResult HandleDodge(Creature actor)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            ActionAvailable = false;
            actor.Dodging = true;
            Log.Append(new ActionTaken(actor.Id, "Dodge"));
            return RuleResult.Ok();
        }

        private RuleResult HandleDeathSave(Creature actor)
        {
            if (!actor.IsDying) return RuleResult.Reject("death-save", "not dying");
            if (_deathSaveRolledThisTurn) return RuleResult.Reject("death-save", "already rolled this turn");
            RollDeathSave(actor);
            return RuleResult.Ok();
        }

        /// <summary>SRD "Death Saving Throws": unmodified d20; nat 1 = 2 failures, nat 20 = regain 1 HP, else >=10 success.</summary>
        private void RollDeathSave(Creature c)
        {
            _deathSaveRolledThisTurn = true;
            var roll = D20Test.Roll(Rng, ExhaustionPenalty(c));
            if (roll.IsNat20)
            {
                c.Heal(1);
                Log.Append(new DeathSaveRolled(c.Id, roll, c.DeathSuccesses, c.DeathFailures));
                return;
            }
            if (roll.IsNat1) c.DeathFailures = Math.Min(3, c.DeathFailures + 2);
            else if (D20Test.MeetsDc(roll, 10)) c.DeathSuccesses = Math.Min(3, c.DeathSuccesses + 1);
            else c.DeathFailures = Math.Min(3, c.DeathFailures + 1);
            Log.Append(new DeathSaveRolled(c.Id, roll, c.DeathSuccesses, c.DeathFailures));

            if (c.DeathFailures >= 3)
            {
                Log.Append(new CreatureDied(c.Id));
                CheckEnd();
                return;
            }
            if (c.DeathSuccesses >= 3)
            {
                c.IsStable = true;
                c.DeathSuccesses = 0;
                c.DeathFailures = 0;
                Log.Append(new Stabilized(c.Id));
            }
        }

        private RuleResult HandleEndTurn(Creature actor)
        {
            ExpireConditions(actor);
            Log.Append(new TurnEnded(actor.Id));
            AdvanceTurn();
            return RuleResult.Ok();
        }

        /// <summary>Consumes the free interaction if it is still available this turn, else the action, else rejects.</summary>
        private RuleResult ConsumeInteractionCost(out string cost)
        {
            if (FreeInteractionAvailable) { FreeInteractionAvailable = false; cost = "free"; return RuleResult.Ok(); }
            if (ActionAvailable) { ActionAvailable = false; cost = "action"; return RuleResult.Ok(); }
            cost = "";
            return RuleResult.Reject("action-economy", "free interaction and action both used this turn");
        }

        private RuleResult HandleInteract(Creature actor, InteractIntent i)
        {
            var obj = GetObject(i.ObjectId);
            if (obj == null) return RuleResult.Reject("object", $"unknown object {i.ObjectId}");
            if (obj.IsBroken) return RuleResult.Reject("object", $"{i.ObjectId} is broken");
            var feet = GridPos.Feet(actor.Position, obj.Cell);
            if (GridPos.Cells(actor.Position, obj.Cell) != 1) return RuleResult.Reject("reach", $"{i.ObjectId} is {feet} ft away; you must be within 5 ft");

            return i.Kind switch
            {
                Interaction.Open => HandleObjectOpen(actor, obj),
                Interaction.Close => HandleObjectClose(actor, obj),
                Interaction.ForceOpen => HandleObjectForceOpen(actor, obj),
                Interaction.PickLock => HandleObjectPickLock(actor, obj),
                _ => RuleResult.Reject("interact", $"unsupported interaction {i.Kind}"),
            };
        }

        private RuleResult HandleObjectOpen(Creature actor, WorldObject obj)
        {
            if (obj.State == ObjectState.Locked) return RuleResult.Reject("locked", $"{obj.Id} is locked; force it or pick the lock");
            if (obj.State == ObjectState.Open) return RuleResult.Reject("object", "already open");
            var costResult = ConsumeInteractionCost(out var cost);
            if (!costResult.Accepted) return costResult;
            var from = obj.State;
            obj.State = ObjectState.Open;
            Log.Append(new ObjectStateChanged(obj.Id, from, ObjectState.Open, actor.Id, cost));
            return RuleResult.Ok();
        }

        private RuleResult HandleObjectClose(Creature actor, WorldObject obj)
        {
            if (obj.State != ObjectState.Open) return RuleResult.Reject("object", "not open");
            var occupant = OccupantAt(obj.Cell);
            if (occupant != null) return RuleResult.Reject("occupied", $"{occupant.Id} is standing in the doorway");
            var costResult = ConsumeInteractionCost(out var cost);
            if (!costResult.Accepted) return costResult;
            var from = obj.State;
            obj.State = ObjectState.Closed;
            Log.Append(new ObjectStateChanged(obj.Id, from, ObjectState.Closed, actor.Id, cost));
            return RuleResult.Ok();
        }

        private RuleResult HandleObjectForceOpen(Creature actor, WorldObject obj)
        {
            int? dc = obj.State == ObjectState.Locked ? obj.Template.LockDc
                : obj.State == ObjectState.Closed ? obj.Template.StuckDc
                : null;
            if (dc == null) return RuleResult.Reject("object", "nothing to force");
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            ActionAvailable = false;
            var mode = actor.Has(Condition.Poisoned) ? RollMode.Disadvantage : RollMode.Normal; // SRD "Poisoned": disadvantage on ability checks
            var roll = D20Test.Roll(Rng, actor.SkillMod(Ability.Str, "athletics") + ExhaustionPenalty(actor), mode);
            var success = D20Test.MeetsDc(roll, dc.Value);
            Log.Append(new ObjectCheckRolled(actor.Id, obj.Id, Interaction.ForceOpen, "Strength (Athletics)", roll, dc.Value, success));
            if (success)
            {
                var from = obj.State;
                obj.State = ObjectState.Open;
                Log.Append(new ObjectStateChanged(obj.Id, from, ObjectState.Open, actor.Id, "action"));
            }
            return RuleResult.Ok();
        }

        private RuleResult HandleObjectPickLock(Creature actor, WorldObject obj)
        {
            if (obj.State != ObjectState.Locked) return RuleResult.Reject("object", "not locked");
            if (!actor.Template.ToolProficiencies.Contains("thieves' tools")) return RuleResult.Reject("tools", "requires thieves' tools");
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            ActionAvailable = false;
            var dc = obj.Template.LockDc ?? 0;
            var mode = actor.Has(Condition.Poisoned) ? RollMode.Disadvantage : RollMode.Normal; // SRD "Poisoned": disadvantage on ability checks
            var roll = D20Test.Roll(Rng, actor.SkillMod(Ability.Dex, "sleight of hand") + ExhaustionPenalty(actor), mode);
            var success = D20Test.MeetsDc(roll, dc);
            Log.Append(new ObjectCheckRolled(actor.Id, obj.Id, Interaction.PickLock, "Dexterity (Sleight of Hand)", roll, dc, success));
            if (success)
            {
                var from = obj.State;
                obj.State = ObjectState.Closed;
                Log.Append(new ObjectStateChanged(obj.Id, from, ObjectState.Closed, actor.Id, "action"));
            }
            return RuleResult.Ok();
        }

        private RuleResult HandleAttackObject(Creature actor, AttackObjectIntent ao)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            var obj = GetObject(ao.ObjectId);
            if (obj == null) return RuleResult.Reject("object", $"unknown object {ao.ObjectId}");
            if (obj.IsBroken) return RuleResult.Reject("object", $"{ao.ObjectId} is already broken");
            var charm = actor.Conditions.FirstOrDefault(ac => ac.Kind == Condition.Charmed);
            if (charm != null)
            {
                var charmer = Get(charm.SourceId);
                if (charmer != null && charmer.Position == obj.Cell) return RuleResult.Reject("charmed", $"{actor.Id} cannot attack an object occupied by its charmer");
            }
            if (ao.AttackIndex < 0 || ao.AttackIndex >= actor.Template.Attacks.Count) return RuleResult.Reject("attack", "no such attack");
            var atk = actor.Template.Attacks[ao.AttackIndex];
            var feet = GridPos.Feet(actor.Position, obj.Cell);
            if (feet > atk.ReachFeet) return RuleResult.Reject("reach", $"{obj.Id} is {feet} ft away, reach is {atk.ReachFeet} ft");

            ActionAvailable = false;
            var roll = D20Test.Roll(Rng, atk.AttackBonus + ExhaustionPenalty(actor));
            var hit = D20Test.AttackHits(roll, obj.Template.ArmorClass);
            var crit = roll.IsNat20;
            Log.Append(new ObjectAttackRolled(actor.Id, obj.Id, atk.Name, roll, obj.Template.ArmorClass, hit, crit));
            if (hit)
            {
                var dmg = (crit ? atk.Damage.Doubled() : atk.Damage).Roll(Rng);
                var rawAmount = Math.Max(0, dmg.Total);
                var immune = atk.DamageType == "poison" || atk.DamageType == "psychic";
                var amount = immune ? 0 : rawAmount;
                obj.Hp = Math.Max(0, obj.Hp - amount);
                Log.Append(new ObjectDamaged(actor.Id, obj.Id, amount, atk.DamageType, obj.Hp));
                if (obj.Hp == 0)
                {
                    var from = obj.State;
                    obj.State = ObjectState.Broken;
                    Log.Append(new ObjectStateChanged(obj.Id, from, ObjectState.Broken, actor.Id, "damage"));
                }
            }
            return RuleResult.Ok();
        }

        private void AdvanceTurn()
        {
            if (Finished) return;
            CheckEnd(); // deaths from any source (attack, trap, out-of-band) end the fight at the next boundary
            if (Finished) return;
            for (var i = 0; i < Order.Count; i++)
            {
                TurnIndex++;
                if (TurnIndex >= Order.Count)
                {
                    TurnIndex = 0;
                    Round++;
                    Log.Append(new RoundStarted(Round));
                }
                if (!Order[TurnIndex].IsDead) break;
            }
            var c = Order[TurnIndex];
            MovementLeftFeet = c.SpeedFeet;
            ActionAvailable = true;
            BonusActionAvailable = true;
            FreeInteractionAvailable = true;
            Dashed = false;
            Disengaged = false;
            c.Dodging = false;
            c.ReactionAvailable = true;
            _deathSaveRolledThisTurn = false;
            Log.Append(new TurnStarted(c.Id, MovementLeftFeet));
            if (c.IsDying) RollDeathSave(c);
        }

        private void CheckEnd()
        {
            var party = _creatures.Any(c => c.Side == Side.Party && !c.IsDead && !c.IsDown);
            var enemy = _creatures.Any(c => c.Side == Side.Enemy && !c.IsDead);
            if (party && enemy) return;
            Finished = true;
            Log.Append(new EncounterEnded(party ? "party-wins" : enemy ? "enemies-win" : "mutual-destruction"));
        }

        /// <summary>Combines advantage/disadvantage from every source: both cancel to Normal (SRD "Advantage and Disadvantage").</summary>
        private RollMode ResolveMode(bool adv, bool dis)
        {
            if (adv && dis) return RollMode.Normal;
            if (adv) return RollMode.Advantage;
            if (dis) return RollMode.Disadvantage;
            return RollMode.Normal;
        }

        /// <summary>Condition-driven advantage/disadvantage on an attack roll (SRD Appendix "Conditions").</summary>
        private (bool adv, bool dis) AttackModifiers(Creature attacker, Creature target, bool ranged)
        {
            var adv = false;
            var dis = false;

            if (attacker.Has(Condition.Blinded)) dis = true;
            if (target.Has(Condition.Blinded)) adv = true;

            if (attacker.Has(Condition.Invisible)) adv = true;
            if (target.Has(Condition.Invisible)) dis = true;

            if (target.Has(Condition.Paralyzed) || target.Has(Condition.Petrified) || target.Has(Condition.Stunned) || target.Has(Condition.Unconscious) || target.Has(Condition.Restrained))
                adv = true;

            if (attacker.Has(Condition.Restrained)) dis = true;
            if (attacker.Has(Condition.Poisoned)) dis = true;
            if (attacker.Has(Condition.Prone)) dis = true;

            var fear = attacker.Conditions.FirstOrDefault(ac => ac.Kind == Condition.Frightened);
            if (fear != null)
            {
                var source = Get(fear.SourceId);
                if (source != null && !source.IsDead && HasLineOfSight(attacker.Position, source.Position)) dis = true;
            }

            if (target.Has(Condition.Prone))
            {
                if (ranged) dis = true;
                else if (GridPos.Feet(attacker.Position, target.Position) <= 5) adv = true;
            }

            return (adv, dis);
        }

        /// <summary>SRD "Incapacitated": also implied by Paralyzed, Petrified, Stunned, Unconscious.</summary>
        private bool IsIncapacitated(Creature c) =>
            c.Has(Condition.Incapacitated) || c.Has(Condition.Paralyzed) || c.Has(Condition.Petrified) || c.Has(Condition.Stunned) || c.Has(Condition.Unconscious);

        /// <summary>SRD "Paralyzed"/"Petrified": any hit against the target from within 5 ft is a critical.</summary>
        private bool AutoCrit(Creature target, Creature attacker) =>
            (target.Has(Condition.Paralyzed) || target.Has(Condition.Petrified) || target.Has(Condition.Unconscious)) && GridPos.Feet(attacker.Position, target.Position) <= 5;

        /// <summary>SRD "Exhaustion": -2 per level on every d20 the creature rolls.</summary>
        private int ExhaustionPenalty(Creature c) => -2 * c.ExhaustionLevel;

        /// <summary>Intent-level rejections driven by the actor's/target's conditions (SRD "Charmed").</summary>
        private RuleResult? CheckAttackConditions(Creature actor, Creature target)
        {
            var charm = actor.Conditions.FirstOrDefault(ac => ac.Kind == Condition.Charmed);
            if (charm != null && charm.SourceId == target.Id) return RuleResult.Reject("charmed", $"{actor.Id} cannot attack its charmer {target.Id}");
            return null;
        }

        /// <summary>SRD "Being Prone": stand up for half your speed.</summary>
        private RuleResult HandleStandUp(Creature actor)
        {
            if (!actor.Has(Condition.Prone)) return RuleResult.Reject("prone", $"{actor.Id} is not prone");
            var cost = actor.SpeedFeet / 2;
            if (cost > MovementLeftFeet) return RuleResult.Reject("movement", $"standing up needs {cost} ft, {MovementLeftFeet} ft left");
            MovementLeftFeet -= cost;
            RemoveCondition(actor.Id, Condition.Prone);
            return RuleResult.Ok();
        }

        /// <summary>Adds or refreshes a condition (host/DM/spells call this; not an intent). Applying a
        /// condition the creature already has replaces its duration; Exhaustion adds levels (cap 6 kills).</summary>
        public void ApplyCondition(string targetId, Condition condition, string sourceId, ConditionDuration duration, int rounds = 0, int level = 1)
        {
            var target = Get(targetId) ?? throw new KeyNotFoundException(targetId);

            if (condition == Condition.Exhaustion)
            {
                var existingExhaustion = target.Conditions.FirstOrDefault(ac => ac.Kind == Condition.Exhaustion);
                var newLevel = Math.Min(6, (existingExhaustion?.Level ?? 0) + level);
                if (existingExhaustion != null) { existingExhaustion.Level = newLevel; existingExhaustion.SourceId = sourceId; existingExhaustion.Duration = duration; existingExhaustion.RoundsLeft = rounds; }
                else target.Conditions.Add(new ActiveCondition { Kind = condition, SourceId = sourceId, Duration = duration, RoundsLeft = rounds, Level = newLevel });
                Log.Append(new ConditionApplied(targetId, condition, sourceId, duration));
                if (newLevel >= 6 && !target.IsDead)
                {
                    target.Hp = 0;
                    if (target.Side == Side.Party) target.DeathFailures = 3;
                    Log.Append(new CreatureDied(target.Id));
                    CheckEnd();
                }
                return;
            }

            var existing = target.Conditions.FirstOrDefault(ac => ac.Kind == condition);
            if (existing != null) { existing.SourceId = sourceId; existing.Duration = duration; existing.RoundsLeft = rounds; }
            else target.Conditions.Add(new ActiveCondition { Kind = condition, SourceId = sourceId, Duration = duration, RoundsLeft = rounds, Level = level });
            Log.Append(new ConditionApplied(targetId, condition, sourceId, duration));
        }

        /// <summary>Removes every ActiveCondition of that kind from the target (host/DM/spells call this; not an intent).</summary>
        public void RemoveCondition(string targetId, Condition condition)
        {
            var target = Get(targetId) ?? throw new KeyNotFoundException(targetId);
            var removed = target.Conditions.RemoveAll(ac => ac.Kind == condition);
            if (removed > 0) Log.Append(new ConditionRemoved(targetId, condition));
        }

        /// <summary>Expires timed conditions at the end of `endingCreature`'s turn, and auto-removes Grappled
        /// when its source is dead or no longer adjacent (checked at the end of any turn).</summary>
        private void ExpireConditions(Creature endingCreature)
        {
            foreach (var c in _creatures)
            {
                foreach (var ac in c.Conditions.Where(ac => ac.Duration == ConditionDuration.EndOfSourceNextTurn && ac.SourceId == endingCreature.Id).ToList())
                {
                    c.Conditions.Remove(ac);
                    Log.Append(new ConditionRemoved(c.Id, ac.Kind));
                }
            }

            foreach (var ac in endingCreature.Conditions.Where(ac => ac.Duration == ConditionDuration.EndOfTargetNextTurn).ToList())
            {
                endingCreature.Conditions.Remove(ac);
                Log.Append(new ConditionRemoved(endingCreature.Id, ac.Kind));
            }

            foreach (var ac in endingCreature.Conditions.Where(ac => ac.Duration == ConditionDuration.Rounds).ToList())
            {
                ac.RoundsLeft--;
                if (ac.RoundsLeft <= 0)
                {
                    endingCreature.Conditions.Remove(ac);
                    Log.Append(new ConditionRemoved(endingCreature.Id, ac.Kind));
                }
            }

            foreach (var c in _creatures)
            {
                foreach (var grapple in c.Conditions.Where(ac => ac.Kind == Condition.Grappled).ToList())
                {
                    var source = Get(grapple.SourceId);
                    if (source == null || source.IsDead || GridPos.Cells(source.Position, c.Position) != 1)
                    {
                        c.Conditions.Remove(grapple);
                        Log.Append(new ConditionRemoved(c.Id, Condition.Grappled));
                    }
                }
            }
        }
    }
}
