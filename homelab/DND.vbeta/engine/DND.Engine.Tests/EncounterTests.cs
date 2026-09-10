using System.Linq;
using DND.Engine.Combat;
using DND.Engine.Core;
using DND.Engine.Events;
using DND.Engine.Intents;
using DND.Engine.Model;
using Xunit;

namespace DND.Engine.Tests
{
    public class EncounterTests
    {
        private static CreatureTemplate Fighter() => new CreatureTemplate
        {
            Id = "fighter", Name = "Fighter", Abilities = new AbilityScores(16, 12, 14, 10, 10, 10),
            MaxHp = 13, ArmorClass = 18, SpeedFeet = 30,
            Attacks = { new AttackTemplate { Name = "Longsword", AttackBonus = 5, Damage = DiceRoll.Parse("1d8+3") } },
        };

        private static CreatureTemplate Goblin() => new CreatureTemplate
        {
            Id = "goblin", Name = "Goblin", Abilities = new AbilityScores(8, 14, 10, 10, 8, 8),
            MaxHp = 7, ArmorClass = 15, SpeedFeet = 30,
            Attacks = { new AttackTemplate { Name = "Scimitar", AttackBonus = 4, Damage = DiceRoll.Parse("1d6+2") } },
        };

        private static Encounter Build(ulong seed)
        {
            var e = new Encounter(new SeededRng(seed));
            e.Add(new Creature("F", Fighter(), Side.Party, new GridPos(0, 0, 0)));
            e.Add(new Creature("G1", Goblin(), Side.Enemy, new GridPos(3, 0, 0)));
            e.Add(new Creature("G2", Goblin(), Side.Enemy, new GridPos(4, 0, 1)));
            return e;
        }

        [Fact]
        public void Start_RollsInitiative_OrdersDescending_TieBreaksByDex()
        {
            var e = Build(1);
            e.Start();
            var inits = e.Order.Select(c => c.Initiative).ToList();
            Assert.Equal(inits.OrderByDescending(x => x), inits);
            Assert.IsType<InitiativeRolled>(e.Log.Events[0]);
            Assert.IsType<RoundStarted>(e.Log.Events[1]);
            Assert.IsType<TurnStarted>(e.Log.Events[2]);
            Assert.Equal(1, e.Round);
            // Tie-break rule: equal initiative -> higher Dex first.
            var tied = e.Order.Zip(e.Order.Skip(1), (a, b) => (a, b)).Where(p => p.a.Initiative == p.b.Initiative);
            foreach (var (a, b) in tied) Assert.True(a.Template.Abilities.Dex >= b.Template.Abilities.Dex);
        }

        [Fact]
        public void OutOfTurn_IsRejected_WithRuleName()
        {
            var e = Build(2);
            e.Start();
            var notCurrent = e.Creatures.First(c => c != e.Current);
            var r = e.Handle(new EndTurnIntent(notCurrent.Id));
            Assert.False(r.Accepted);
            Assert.StartsWith("turn-order:", r.Reason);
        }

        [Fact]
        public void Movement_SpendsBudget_AndRejectsWhenExhausted()
        {
            var e = Build(3);
            e.Start();
            var c = e.Current!;
            var pos = c.Position;
            var budget = e.MovementLeftFeet;
            var steps = 0;
            while (true)
            {
                var next = pos.Offset(0, 0, steps % 2 == 0 ? 1 : -1).Offset(1, 0, 0); // zig-zag diagonals
                if (e.OccupantAt(next) != null) next = pos.Offset(0, 0, 1);
                var r = e.Handle(new MoveIntent(c.Id, next));
                if (!r.Accepted) { Assert.StartsWith("movement:", r.Reason); break; }
                pos = next; steps++;
            }
            Assert.Equal(budget / 5, steps);
            Assert.Equal(0, e.MovementLeftFeet);
            Assert.Equal(budget / 5, e.Log.Events.OfType<Moved>().Count());
        }

        [Fact]
        public void Attack_RequiresReach_UsesOneAction_AppliesDamage()
        {
            var e = Build(4);
            e.Start();
            // Put the fighter in control regardless of initiative by cycling to it.
            while (e.Current!.Id != "F") e.Handle(new EndTurnIntent(e.Current.Id));
            var far = e.Handle(new AttackIntent("F", "G1"));
            Assert.False(far.Accepted);
            Assert.StartsWith("reach:", far.Reason);

            // Walk adjacent.
            e.Handle(new MoveIntent("F", new GridPos(1, 0, 0)));
            e.Handle(new MoveIntent("F", new GridPos(2, 0, 0)));
            var ok = e.Handle(new AttackIntent("F", "G1"));
            Assert.True(ok.Accepted, ok.Reason);
            Assert.Single(e.Log.Events.OfType<AttackRolled>());
            var second = e.Handle(new AttackIntent("F", "G1"));
            Assert.False(second.Accepted);
            Assert.StartsWith("action-economy:", second.Reason);

            var atk = e.Log.Events.OfType<AttackRolled>().Single();
            var dmg = e.Log.Events.OfType<DamageDealt>().SingleOrDefault();
            if (atk.Hit)
            {
                Assert.NotNull(dmg);
                Assert.Equal(7 - dmg!.Amount < 0 ? 0 : 7 - dmg.Amount, e.Get("G1")!.Hp);
                if (atk.Critical) Assert.Equal(2, dmg.Dice.Count);
            }
            else Assert.Null(dmg);
        }

        [Fact]
        public void Death_SkipsTurn_AndEndsEncounter()
        {
            var e = Build(5);
            e.Start();
            // G1 dies out of band (e.g. a trap). It must never hold a turn again, and cannot be targeted.
            e.Get("G1")!.ApplyDamage(100);
            for (var i = 0; i < 6 && e.Current!.Id != "F"; i++)
            {
                var r0 = e.Handle(new EndTurnIntent(e.Current.Id));
                Assert.True(r0.Accepted, r0.Reason);
                Assert.NotEqual("G1", e.Current!.Id);
            }
            Assert.Equal("F", e.Current!.Id);
            var r = e.Handle(new AttackIntent("F", "G1"));
            Assert.False(r.Accepted);
            Assert.StartsWith("target:", r.Reason);
            Assert.False(e.Finished);

            // Last enemy dies out of band: the next intent ends the encounter instead of acting.
            e.Get("G2")!.ApplyDamage(100);
            e.Handle(new EndTurnIntent("F"));
            var after = e.Handle(new EndTurnIntent(e.Current!.Id));
            Assert.True(e.Finished);
            Assert.False(after.Accepted);
            Assert.Contains(e.Log.Events, ev => ev is EncounterEnded);
        }

        [Fact]
        public void TempHp_AbsorbsFirst()
        {
            var c = new Creature("x", Goblin(), Side.Enemy, new GridPos(0, 0, 0)) { TempHp = 5 };
            Assert.Equal(1, c.ApplyDamage(6));
            Assert.Equal(0, c.TempHp);
            Assert.Equal(6, c.Hp);
        }

        [Fact]
        public void Replay_SameSeedSameIntents_SameEventLog()
        {
            string Run(ulong seed)
            {
                var e = Build(seed);
                e.Start();
                // A scripted fight: every creature steps toward x=2 then attacks whoever is adjacent, else ends turn.
                for (var turn = 0; turn < 40 && !e.Finished; turn++)
                {
                    var c = e.Current!;
                    var target = e.Creatures.FirstOrDefault(o => o.Side != c.Side && !o.IsDead && o.Position.IsAdjacent(c.Position));
                    if (target == null)
                    {
                        var dir = c.Side == Side.Party ? 1 : -1;
                        e.Handle(new MoveIntent(c.Id, c.Position.Offset(dir, 0, 0)));
                        target = e.Creatures.FirstOrDefault(o => o.Side != c.Side && !o.IsDead && o.Position.IsAdjacent(c.Position));
                    }
                    if (target != null) e.Handle(new AttackIntent(c.Id, target.Id));
                    e.Handle(new EndTurnIntent(c.Id));
                }
                return e.Log.Fingerprint();
            }
            Assert.Equal(Run(99), Run(99));
            Assert.NotEqual(Run(99), Run(100));
        }
    }
}
