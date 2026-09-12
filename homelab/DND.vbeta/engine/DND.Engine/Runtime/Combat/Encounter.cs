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
    /// <summary>Static obstacles for v0.1: which cells block movement.</summary>
    public interface IBattlefield
    {
        bool IsBlocked(GridPos cell);
    }

    public sealed class OpenField : IBattlefield
    {
        public bool IsBlocked(GridPos cell) => false;
    }

    /// <summary>
    /// The combat state machine: initiative, turns, action economy, and the rules that decide
    /// whether an intent becomes events. v0.1 covers move + melee attack + end turn (03b grows it).
    /// </summary>
    public sealed class Encounter
    {
        public readonly EventLog Log = new EventLog();
        public readonly IRng Rng;
        public readonly IBattlefield Field;
        private readonly Dictionary<string, Creature> _byId = new Dictionary<string, Creature>();
        private readonly List<Creature> _creatures = new List<Creature>();
        private readonly Dictionary<string, WorldObject> _objects = new Dictionary<string, WorldObject>();

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

        /// <summary>True if an object occupying the cell blocks sight (terrain LoS is 03b).</summary>
        public bool BlocksSight(GridPos cell) => ObjectAt(cell)?.BlocksSight ?? false;

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

            return intent switch
            {
                MoveIntent m => HandleMove(actor, m),
                AttackIntent a => HandleAttack(actor, a),
                EndTurnIntent => HandleEndTurn(actor),
                InteractIntent i => HandleInteract(actor, i),
                AttackObjectIntent ao => HandleAttackObject(actor, ao),
                _ => RuleResult.Reject("intent", $"unsupported intent {intent.GetType().Name}"),
            };
        }

        private RuleResult HandleMove(Creature actor, MoveIntent m)
        {
            var cells = GridPos.Cells(actor.Position, m.To);
            if (cells == 0) return RuleResult.Reject("movement", "already there");
            if (cells != 1) return RuleResult.Reject("movement", "v0.1 moves one cell per intent; send a path as single steps");
            if (IsBlocked(m.To)) return RuleResult.Reject("movement", $"{m.To} is blocked");
            if (OccupantAt(m.To) != null) return RuleResult.Reject("movement", $"{m.To} is occupied");
            var cost = GridPos.Feet(actor.Position, m.To);
            if (cost > MovementLeftFeet) return RuleResult.Reject("movement", $"needs {cost} ft, {MovementLeftFeet} ft left");
            var from = actor.Position;
            actor.Position = m.To;
            MovementLeftFeet -= cost;
            Log.Append(new Moved(actor.Id, from, m.To, cost, MovementLeftFeet));
            return RuleResult.Ok();
        }

        private RuleResult HandleAttack(Creature actor, AttackIntent a)
        {
            if (!ActionAvailable) return RuleResult.Reject("action-economy", "action already used this turn");
            var target = Get(a.TargetId);
            if (target == null) return RuleResult.Reject("target", $"unknown creature {a.TargetId}");
            if (target.IsDead) return RuleResult.Reject("target", $"{target.Id} is already dead");
            if (a.AttackIndex < 0 || a.AttackIndex >= actor.Template.Attacks.Count) return RuleResult.Reject("attack", "no such attack");
            var atk = actor.Template.Attacks[a.AttackIndex];
            var feet = GridPos.Feet(actor.Position, target.Position);
            if (feet > atk.ReachFeet) return RuleResult.Reject("reach", $"{target.Id} is {feet} ft away, reach is {atk.ReachFeet} ft");

            ActionAvailable = false;
            var roll = D20Test.Roll(Rng, atk.AttackBonus);
            var hit = D20Test.AttackHits(roll, target.ArmorClass);
            var crit = roll.IsNat20;
            Log.Append(new AttackRolled(actor.Id, target.Id, atk.Name, roll, target.ArmorClass, hit, crit));
            if (hit)
            {
                var dmg = (crit ? atk.Damage.Doubled() : atk.Damage).Roll(Rng);
                var amount = Math.Max(0, dmg.Total);
                target.ApplyDamage(amount);
                Log.Append(new DamageDealt(actor.Id, target.Id, amount, atk.DamageType, dmg.Dice, target.Hp));
                if (target.IsDead)
                {
                    Log.Append(new CreatureDied(target.Id));
                    CheckEnd();
                }
            }
            return RuleResult.Ok();
        }

        private RuleResult HandleEndTurn(Creature actor)
        {
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
            var roll = D20Test.Roll(Rng, actor.SkillMod(Ability.Str, "athletics"));
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
            var roll = D20Test.Roll(Rng, actor.SkillMod(Ability.Dex, "sleight of hand"));
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
            if (ao.AttackIndex < 0 || ao.AttackIndex >= actor.Template.Attacks.Count) return RuleResult.Reject("attack", "no such attack");
            var atk = actor.Template.Attacks[ao.AttackIndex];
            var feet = GridPos.Feet(actor.Position, obj.Cell);
            if (feet > atk.ReachFeet) return RuleResult.Reject("reach", $"{obj.Id} is {feet} ft away, reach is {atk.ReachFeet} ft");

            ActionAvailable = false;
            var roll = D20Test.Roll(Rng, atk.AttackBonus);
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
            Log.Append(new TurnStarted(c.Id, MovementLeftFeet));
        }

        private void CheckEnd()
        {
            var party = _creatures.Any(c => c.Side == Side.Party && !c.IsDead);
            var enemy = _creatures.Any(c => c.Side == Side.Enemy && !c.IsDead);
            if (party && enemy) return;
            Finished = true;
            Log.Append(new EncounterEnded(party ? "party-wins" : enemy ? "enemies-win" : "mutual-destruction"));
        }
    }
}
