using DND.Engine.Core;
using DND.Engine.Rules;
using Xunit;

namespace DND.Engine.Tests
{
    public class CoreTests
    {
        [Fact]
        public void SeededRng_IsDeterministic_AndInRange()
        {
            var a = new SeededRng(42);
            var b = new SeededRng(42);
            for (var i = 0; i < 1000; i++)
            {
                var ra = a.Roll(20);
                var rb = b.Roll(20);
                Assert.Equal(ra, rb);
                Assert.InRange(ra, 1, 20);
            }
        }

        [Theory]
        [InlineData(1, -5)] [InlineData(8, -1)] [InlineData(9, -1)] [InlineData(10, 0)]
        [InlineData(11, 0)] [InlineData(12, 1)] [InlineData(20, 5)] [InlineData(30, 10)]
        public void AbilityModifier_MatchesSrdTable(int score, int expected)
            => Assert.Equal(expected, AbilityMath.Modifier(score));

        [Theory]
        [InlineData(1, 2)] [InlineData(4, 2)] [InlineData(5, 3)] [InlineData(9, 4)] [InlineData(17, 6)] [InlineData(20, 6)]
        public void ProficiencyBonus_MatchesSrdTable(int level, int expected)
            => Assert.Equal(expected, AbilityMath.ProficiencyBonusForLevel(level));

        [Theory]
        [InlineData("1d8", 1, 8, 0)] [InlineData("2d6+3", 2, 6, 3)] [InlineData("d20-1", 1, 20, -1)] [InlineData("4", 0, 1, 4)]
        public void DiceRoll_Parses(string text, int count, int sides, int bonus)
        {
            var d = DiceRoll.Parse(text);
            Assert.Equal(count, d.Count); Assert.Equal(sides, d.Sides); Assert.Equal(bonus, d.Bonus);
        }

        [Fact]
        public void D20_Advantage_KeepsHigher_Disadvantage_KeepsLower()
        {
            var rng = new SeededRng(7);
            for (var i = 0; i < 200; i++)
            {
                var adv = Dice.D20(rng, RollMode.Advantage, out var a1, out var a2);
                Assert.Equal(System.Math.Max(a1, a2), adv);
                var dis = Dice.D20(rng, RollMode.Disadvantage, out var d1, out var d2);
                Assert.Equal(System.Math.Min(d1, d2), dis);
            }
        }

        [Fact]
        public void AttackHits_Nat20AlwaysHits_Nat1AlwaysMisses()
        {
            Assert.True(D20Test.AttackHits(new D20Result(20, 0, -10, RollMode.Normal), 30));
            Assert.False(D20Test.AttackHits(new D20Result(1, 0, +30, RollMode.Normal), 5));
            Assert.True(D20Test.AttackHits(new D20Result(10, 0, 5, RollMode.Normal), 15));
            Assert.False(D20Test.AttackHits(new D20Result(10, 0, 4, RollMode.Normal), 15));
        }

        [Fact]
        public void GridPos_FiveFiveFiveDiagonals()
        {
            var a = new GridPos(0, 0, 0);
            Assert.Equal(5, GridPos.Feet(a, new GridPos(1, 0, 1)));   // diagonal costs 5 (D31 default rule)
            Assert.Equal(15, GridPos.Feet(a, new GridPos(3, 0, 2)));
            Assert.Equal(10, GridPos.Feet(a, new GridPos(0, 2, 0)));  // elevation counts
            Assert.True(a.IsAdjacent(new GridPos(-1, 0, 1)));
        }
    }
}
