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

        public IReadOnlyList<Creature> Creatures => _creatures;
        public IReadOnlyList<Creature> Order { get; private set; } = Array.Empty<Creature>();
        public int Round { get; private set; }
        public int TurnIndex { get; private set; } = -1;
        public bool Started => Round > 0;
        public bool Finished { get; private set; }

        // Per-turn economy
        public int MovementLeftFeet { get; private set; }
        public bool ActionAvailable { get; private set; }
        public bool BonusActionAvailable { get; private set; }

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
                _ => RuleResult.Reject("intent", $"unsupported intent {intent.GetType().Name}"),
            };
        }

        private RuleResult HandleMove(Creature actor, MoveIntent m)
        {
            var cells = GridPos.Cells(actor.Position, m.To);
            if (cells == 0) return RuleResult.Reject("movement", "already there");
            if (cells != 1) return RuleResult.Reject("movement", "v0.1 moves one cell per intent; send a path as single steps");
            if (Field.IsBlocked(m.To)) return RuleResult.Reject("movement", $"{m.To} is blocked");
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
