using DND.Engine.Core;

namespace DND.Engine.Rules
{
    /// <summary>Outcome of any d20 Test (check, save, attack roll).</summary>
    public readonly struct D20Result
    {
        public readonly int Natural;   // die kept after advantage/disadvantage
        public readonly int Alt;       // the other die (0 if none)
        public readonly int Modifier;
        public readonly int Total;
        public readonly RollMode Mode;
        public bool IsNat20 => Natural == 20;
        public bool IsNat1 => Natural == 1;

        public D20Result(int natural, int alt, int modifier, RollMode mode)
        {
            Natural = natural; Alt = alt; Modifier = modifier; Mode = mode; Total = natural + modifier;
        }

        public override string ToString() => Alt == 0 ? $"d20({Natural}){Modifier:+0;-0}={Total}" : $"d20({Natural}|{Alt}){Modifier:+0;-0}={Total}";
    }

    public static class D20Test
    {
        public static D20Result Roll(IRng rng, int modifier, RollMode mode = RollMode.Normal)
        {
            var kept = Dice.D20(rng, mode, out var first, out var second);
            var alt = mode == RollMode.Normal ? 0 : (kept == first ? second : first);
            return new D20Result(kept, alt, modifier, mode);
        }

        /// <summary>SRD: an attack roll hits if the total meets or exceeds AC; nat 20 always hits, nat 1 always misses.</summary>
        public static bool AttackHits(D20Result roll, int armorClass)
        {
            if (roll.IsNat20) return true;
            if (roll.IsNat1) return false;
            return roll.Total >= armorClass;
        }

        /// <summary>SRD: a check or save succeeds if the total meets or exceeds the DC (no auto success/failure on checks in 2024 core; saves same).</summary>
        public static bool MeetsDc(D20Result roll, int dc) => roll.Total >= dc;
    }
}
