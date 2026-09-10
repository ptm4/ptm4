using System;
using System.Collections.Generic;

namespace DND.Engine.Core
{
    public enum RollMode { Normal, Advantage, Disadvantage }

    /// <summary>A dice expression like 2d6+3, rolled with an IRng and remembered die by die.</summary>
    public readonly struct DiceRoll
    {
        public readonly int Count;
        public readonly int Sides;
        public readonly int Bonus;

        public DiceRoll(int count, int sides, int bonus = 0)
        {
            if (count < 0 || sides < 1) throw new ArgumentException("bad dice expression");
            Count = count; Sides = sides; Bonus = bonus;
        }

        public DiceRoll WithBonus(int bonus) => new DiceRoll(Count, Sides, bonus);
        public DiceRoll Doubled() => new DiceRoll(Count * 2, Sides, Bonus);
        public int Average => (int)Math.Floor(Count * (Sides + 1) / 2.0 + Bonus);

        public DiceResult Roll(IRng rng)
        {
            var dice = new int[Count];
            var sum = 0;
            for (var i = 0; i < Count; i++) { dice[i] = rng.Roll(Sides); sum += dice[i]; }
            return new DiceResult(this, dice, sum + Bonus);
        }

        /// <summary>Parses "1d8", "2d6+3", "d20-1", "4" (a constant).</summary>
        public static DiceRoll Parse(string text)
        {
            var s = text.Replace(" ", "").ToLowerInvariant();
            var d = s.IndexOf('d');
            if (d < 0) return new DiceRoll(0, 1, int.Parse(s));
            var count = d == 0 ? 1 : int.Parse(s.Substring(0, d));
            var rest = s.Substring(d + 1);
            var plus = rest.IndexOfAny(new[] { '+', '-' });
            if (plus < 0) return new DiceRoll(count, int.Parse(rest));
            return new DiceRoll(count, int.Parse(rest.Substring(0, plus)), int.Parse(rest.Substring(plus)));
        }

        public override string ToString() => Count == 0 ? Bonus.ToString() : $"{Count}d{Sides}{(Bonus >= 0 ? "+" : "")}{Bonus}";
    }

    public readonly struct DiceResult
    {
        public readonly DiceRoll Expression;
        public readonly IReadOnlyList<int> Dice;
        public readonly int Total;

        public DiceResult(DiceRoll expression, int[] dice, int total)
        {
            Expression = expression; Dice = dice; Total = total;
        }
    }

    public static class Dice
    {
        /// <summary>The d20 Test roll: returns the natural die kept after advantage/disadvantage.</summary>
        public static int D20(IRng rng, RollMode mode, out int first, out int second)
        {
            first = rng.Roll(20);
            second = mode == RollMode.Normal ? 0 : rng.Roll(20);
            return mode switch
            {
                RollMode.Advantage => Math.Max(first, second),
                RollMode.Disadvantage => Math.Min(first, second),
                _ => first,
            };
        }
    }
}
