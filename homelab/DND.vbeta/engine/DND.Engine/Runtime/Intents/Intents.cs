using DND.Engine.Core;
using DND.Engine.Model;

namespace DND.Engine.Intents
{
    /// <summary>Something a player or the AI wants to do. Validated by the engine, never trusted.</summary>
    public abstract class Intent
    {
        public readonly string ActorId;
        protected Intent(string actorId) { ActorId = actorId; }
    }

    public sealed class MoveIntent : Intent
    {
        public readonly GridPos To;
        public MoveIntent(string actorId, GridPos to) : base(actorId) { To = to; }
    }

    public sealed class AttackIntent : Intent
    {
        public readonly string TargetId;
        public readonly int AttackIndex;
        public AttackIntent(string actorId, string targetId, int attackIndex = 0) : base(actorId) { TargetId = targetId; AttackIndex = attackIndex; }
    }

    public sealed class EndTurnIntent : Intent
    {
        public EndTurnIntent(string actorId) : base(actorId) { }
    }

    public sealed class InteractIntent : Intent { public readonly string ObjectId; public readonly Interaction Kind; public InteractIntent(string actorId, string objectId, Interaction kind) : base(actorId) { ObjectId = objectId; Kind = kind; } }
    public sealed class AttackObjectIntent : Intent { public readonly string ObjectId; public readonly int AttackIndex; public AttackObjectIntent(string actorId, string objectId, int attackIndex = 0) : base(actorId) { ObjectId = objectId; AttackIndex = attackIndex; } }

    /// <summary>SRD "Dash": action; gain extra movement equal to speed this turn.</summary>
    public sealed class DashIntent : Intent { public DashIntent(string actorId) : base(actorId) { } }
    /// <summary>SRD "Disengage": action; movement doesn't provoke opportunity attacks this turn.</summary>
    public sealed class DisengageIntent : Intent { public DisengageIntent(string actorId) : base(actorId) { } }
    /// <summary>SRD "Dodge": action; until your next turn, attacks against you have disadvantage (advantage on Dex saves is 03c).</summary>
    public sealed class DodgeIntent : Intent { public DodgeIntent(string actorId) : base(actorId) { } }
    /// <summary>Only legal for a Dying creature at the start of its turn if the engine's auto-roll hasn't already happened.</summary>
    public sealed class DeathSaveIntent : Intent { public DeathSaveIntent(string actorId) : base(actorId) { } }
    /// <summary>SRD "Being Prone": costs half the creature's speed in movement; ends the Prone condition.</summary>
    public sealed class StandUpIntent : Intent { public StandUpIntent(string actorId) : base(actorId) { } }

    /// <summary>Accepted (events were appended) or Rejected with the rule that refused it.</summary>
    public readonly struct RuleResult
    {
        public readonly bool Accepted;
        public readonly string Reason;   // empty when accepted; otherwise a rule name + why
        private RuleResult(bool ok, string reason) { Accepted = ok; Reason = reason; }
        public static RuleResult Ok() => new RuleResult(true, "");
        public static RuleResult Reject(string rule, string why) => new RuleResult(false, $"{rule}: {why}");
        public override string ToString() => Accepted ? "accepted" : Reason;
    }
}
