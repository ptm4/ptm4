using DND.Engine.Core;

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
