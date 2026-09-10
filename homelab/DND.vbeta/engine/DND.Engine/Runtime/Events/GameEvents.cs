using System.Collections.Generic;
using DND.Engine.Core;
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
