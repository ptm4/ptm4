using System.Collections.Generic;
using DND.Engine.Core;
using DND.Engine.Model;
using DND.Engine.Rules;

namespace DND.Engine.Events
{
    /// <summary>Immutable fact appended to the log. Sequence is assigned by the log.</summary>
    public abstract class GameEvent
    {
        public int Sequence { get; internal set; }
        public abstract string Describe();
    }

    public sealed class InitiativeRolled : GameEvent
    {
        public readonly IReadOnlyList<(string creatureId, int initiative)> Order;
        public InitiativeRolled(IReadOnlyList<(string, int)> order) { Order = order; }
        public override string Describe() => "Initiative: " + string.Join(", ", System.Linq.Enumerable.Select(Order, o => $"{o.creatureId} {o.initiative}"));
    }

    public sealed class RoundStarted : GameEvent
    {
        public readonly int Round;
        public RoundStarted(int round) { Round = round; }
        public override string Describe() => $"Round {Round}";
    }

    public sealed class TurnStarted : GameEvent
    {
        public readonly string CreatureId;
        public readonly int MovementFeet;
        public TurnStarted(string id, int movementFeet) { CreatureId = id; MovementFeet = movementFeet; }
        public override string Describe() => $"{CreatureId}'s turn";
    }

    public sealed class Moved : GameEvent
    {
        public readonly string CreatureId;
        public readonly GridPos From, To;
        public readonly int CostFeet, RemainingFeet;
        public Moved(string id, GridPos from, GridPos to, int costFeet, int remainingFeet) { CreatureId = id; From = from; To = to; CostFeet = costFeet; RemainingFeet = remainingFeet; }
        public override string Describe() => $"{CreatureId} moves {From}->{To} ({CostFeet} ft, {RemainingFeet} left)";
    }

    public sealed class AttackRolled : GameEvent
    {
        public readonly string AttackerId, TargetId, AttackName;
        public readonly D20Result Roll;
        public readonly int TargetAc;
        public readonly bool Hit, Critical;
        public AttackRolled(string a, string t, string name, D20Result roll, int ac, bool hit, bool crit) { AttackerId = a; TargetId = t; AttackName = name; Roll = roll; TargetAc = ac; Hit = hit; Critical = crit; }
        public override string Describe() => $"{AttackerId} {AttackName} vs {TargetId}: {Roll} vs AC {TargetAc} => {(Critical ? "CRIT" : Hit ? "hit" : "miss")}";
    }

    public sealed class DamageDealt : GameEvent
    {
        public readonly string SourceId, TargetId, DamageType;
        public readonly int Amount, HpAfter;
        public readonly IReadOnlyList<int> Dice;
        public DamageDealt(string s, string t, int amount, string type, IReadOnlyList<int> dice, int hpAfter) { SourceId = s; TargetId = t; Amount = amount; DamageType = type; Dice = dice; HpAfter = hpAfter; }
        public override string Describe() => $"{TargetId} takes {Amount} {DamageType} (HP {HpAfter})";
    }

    public sealed class CreatureDied : GameEvent
    {
        public readonly string CreatureId;
        public CreatureDied(string id) { CreatureId = id; }
        public override string Describe() => $"{CreatureId} dies";
    }

    public sealed class TurnEnded : GameEvent
    {
        public readonly string CreatureId;
        public TurnEnded(string id) { CreatureId = id; }
        public override string Describe() => $"{CreatureId} ends turn";
    }

    public sealed class EncounterEnded : GameEvent
    {
        public readonly string Outcome;
        public EncounterEnded(string outcome) { Outcome = outcome; }
        public override string Describe() => $"Encounter over: {Outcome}";
    }

    public sealed class ObjectStateChanged : GameEvent
    {
        public readonly string ObjectId;
        public readonly ObjectState From, To;
        public readonly string ById, Cost;
        public ObjectStateChanged(string objectId, ObjectState from, ObjectState to, string byId, string cost) { ObjectId = objectId; From = from; To = to; ById = byId; Cost = cost; }
        public override string Describe()
        {
            var verb = To == ObjectState.Open ? "opens"
                : To == ObjectState.Broken ? "breaks"
                : (From == ObjectState.Locked && To == ObjectState.Closed) ? "unlocks"
                : "closes";
            return $"{ById} {verb} {ObjectId} ({Cost})";
        }
    }

    public sealed class ObjectCheckRolled : GameEvent
    {
        public readonly string ActorId, ObjectId, Skill;
        public readonly Interaction Kind;
        public readonly D20Result Roll;
        public readonly int Dc;
        public readonly bool Success;
        public ObjectCheckRolled(string actorId, string objectId, Interaction kind, string skill, D20Result roll, int dc, bool success) { ActorId = actorId; ObjectId = objectId; Kind = kind; Skill = skill; Roll = roll; Dc = dc; Success = success; }
        public override string Describe() => $"{ActorId} {Kind} {ObjectId}: {Skill} {Roll} vs DC {Dc} => {(Success ? "success" : "failure")}";
    }

    public sealed class ObjectDamaged : GameEvent
    {
        public readonly string SourceId, ObjectId, DamageType;
        public readonly int Amount, HpAfter;
        public ObjectDamaged(string sourceId, string objectId, int amount, string damageType, int hpAfter) { SourceId = sourceId; ObjectId = objectId; Amount = amount; DamageType = damageType; HpAfter = hpAfter; }
        public override string Describe() => $"{ObjectId} takes {Amount} {DamageType} (HP {HpAfter})";
    }

    public sealed class ConditionApplied : GameEvent
    {
        public readonly string TargetId, SourceId;
        public readonly Condition Kind;
        public readonly ConditionDuration Duration;
        public ConditionApplied(string targetId, Condition kind, string sourceId, ConditionDuration duration) { TargetId = targetId; Kind = kind; SourceId = sourceId; Duration = duration; }
        public override string Describe() => $"{TargetId} is {Kind}";
    }

    public sealed class ConditionRemoved : GameEvent
    {
        public readonly string TargetId;
        public readonly Condition Kind;
        public ConditionRemoved(string targetId, Condition kind) { TargetId = targetId; Kind = kind; }
        public override string Describe() => $"{TargetId} is no longer {Kind}";
    }

    public sealed class ActionTaken : GameEvent
    {
        public readonly string ActorId, Name;
        public ActionTaken(string actorId, string name) { ActorId = actorId; Name = name; }
        public override string Describe() => $"{ActorId} takes the {Name} action";
    }

    public sealed class OpportunityAttack : GameEvent
    {
        public readonly string ReactorId, ActorId;
        public OpportunityAttack(string reactorId, string actorId) { ReactorId = reactorId; ActorId = actorId; }
        public override string Describe() => $"{ReactorId} takes an opportunity attack against {ActorId}";
    }

    public sealed class DeathSaveRolled : GameEvent
    {
        public readonly string CreatureId;
        public readonly D20Result Roll;
        public readonly int Successes, Failures;
        public DeathSaveRolled(string creatureId, D20Result roll, int successes, int failures) { CreatureId = creatureId; Roll = roll; Successes = successes; Failures = failures; }
        public override string Describe() => $"{CreatureId} death save {Roll}: {Successes} successes / {Failures} failures";
    }

    public sealed class Stabilized : GameEvent
    {
        public readonly string CreatureId;
        public Stabilized(string creatureId) { CreatureId = creatureId; }
        public override string Describe() => $"{CreatureId} is stable";
    }

    public sealed class ObjectAttackRolled : GameEvent
    {
        public readonly string AttackerId, ObjectId, AttackName;
        public readonly D20Result Roll;
        public readonly int Ac;
        public readonly bool Hit, Critical;
        public ObjectAttackRolled(string attackerId, string objectId, string attackName, D20Result roll, int ac, bool hit, bool crit) { AttackerId = attackerId; ObjectId = objectId; AttackName = attackName; Roll = roll; Ac = ac; Hit = hit; Critical = crit; }
        public override string Describe() => $"{AttackerId} {AttackName} vs {ObjectId}: {Roll} vs AC {Ac} => {(Critical ? "CRIT" : Hit ? "hit" : "miss")}";
    }

    /// <summary>Append-only, sequence-numbered. This is the save file and the wire format.</summary>
    public sealed class EventLog
    {
        private readonly List<GameEvent> _events = new List<GameEvent>();
        public IReadOnlyList<GameEvent> Events => _events;
        public int Count => _events.Count;

        public event System.Action<GameEvent>? Appended;

        public T Append<T>(T e) where T : GameEvent
        {
            e.Sequence = _events.Count;
            _events.Add(e);
            Appended?.Invoke(e);
            return e;
        }

        /// <summary>Stable text fingerprint for replay/determinism tests and network sanity checks.</summary>
        public string Fingerprint()
        {
            var sb = new System.Text.StringBuilder();
            foreach (var e in _events) sb.Append(e.Sequence).Append(':').Append(e.Describe()).Append('\n');
            return sb.ToString();
        }
    }
}
