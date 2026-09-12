using System.Linq;
using DND.Engine.Combat;
using DND.Engine.Core;
using DND.Engine.Events;
using DND.Engine.Intents;
using DND.Engine.Model;
using Xunit;

namespace DND.Engine.Tests
{
    public class ObjectInteractionTests
    {
        private static CreatureTemplate Fighter() => new CreatureTemplate
        {
            Id = "fighter", Name = "Fighter", Abilities = new AbilityScores(16, 12, 14, 10, 10, 10),
            MaxHp = 13, ArmorClass = 18, SpeedFeet = 30,
            SkillProficiencies = { "athletics" },
            Attacks = {
                new AttackTemplate { Name = "Longsword", AttackBonus = 5, Damage = DiceRoll.Parse("1d8+3"), DamageType = "slashing" },
                new AttackTemplate { Name = "Poisoned Dagger", AttackBonus = 5, Damage = DiceRoll.Parse("1d4+3"), DamageType = "poison" },
            },
        };

        private static CreatureTemplate Rogue() => new CreatureTemplate
        {
            Id = "rogue", Name = "Rogue", Abilities = new AbilityScores(10, 16, 12, 12, 10, 10),
            MaxHp = 9, ArmorClass = 14, SpeedFeet = 30,
            SkillProficiencies = { "sleight of hand" },
            ToolProficiencies = { "thieves' tools" },
            Attacks = { new AttackTemplate { Name = "Shortsword", AttackBonus = 5, Damage = DiceRoll.Parse("1d6+3"), DamageType = "piercing" } },
        };

        private static CreatureTemplate Goblin() => new CreatureTemplate
        {
            Id = "goblin", Name = "Goblin", Abilities = new AbilityScores(8, 14, 10, 10, 8, 8),
            MaxHp = 7, ArmorClass = 15, SpeedFeet = 30,
            Attacks = { new AttackTemplate { Name = "Scimitar", AttackBonus = 4, Damage = DiceRoll.Parse("1d6+2"), DamageType = "slashing" } },
        };

        // Door, Wood, Medium, resilient -> AC 15, HP 18.
        private static ObjectTemplate WoodenDoor() => new ObjectTemplate
        {
            Id = "door", Name = "Wooden Door", Kind = ObjectKind.Door, Material = ObjectMaterial.Wood, Size = ObjectSize.Medium, Fragile = false,
        };

        // Chest, Iron, Small, resilient -> AC 19, HP 10.
        private static ObjectTemplate IronChest(int lockDc) => new ObjectTemplate
        {
            Id = "chest", Name = "Iron Chest", Kind = ObjectKind.Chest, Material = ObjectMaterial.Iron, Size = ObjectSize.Small, Fragile = false, LockDc = lockDc,
        };

        /// <summary>A two-creature party-vs-enemy encounter (so it never ends) with `actorTemplate` adjacent
        /// to (1,0,0) at `actorPos`, and the given `actorId` guaranteed to hold the current turn on return.</summary>
        private static Encounter Build(ulong seed, GridPos actorPos, CreatureTemplate actorTemplate, string actorId = "F")
        {
            var e = new Encounter(new SeededRng(seed));
            e.Add(new Creature(actorId, actorTemplate, Side.Party, actorPos));
            e.Add(new Creature("E", Goblin(), Side.Enemy, new GridPos(20, 0, 0)));
            e.Start();
            while (e.Current!.Id != actorId) e.Handle(new EndTurnIntent(e.Current.Id));
            return e;
        }

        [Fact]
        public void Open_ClosedDoor_UsesFreeInteraction_ThenActionStillAvailable()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.True(r.Accepted, r.Reason);
            Assert.False(e.FreeInteractionAvailable);
            Assert.True(e.ActionAvailable);
            var last = e.Log.Events.OfType<ObjectStateChanged>().Last();
            Assert.Equal("free", last.Cost);
            Assert.Equal("F opens door (free)", last.Describe());
        }

        [Fact]
        public void SecondInteraction_SameTurn_ConsumesAction()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            e.Handle(new InteractIntent("F", "door", Interaction.Open));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Close));
            Assert.True(r.Accepted, r.Reason);
            var second = e.Log.Events.OfType<ObjectStateChanged>().Last();
            Assert.Equal("action", second.Cost);
            Assert.False(e.ActionAvailable);
        }

        [Fact]
        public void ThirdInteraction_SameTurn_Rejected_ActionEconomy()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            e.Handle(new InteractIntent("F", "door", Interaction.Open));
            e.Handle(new InteractIntent("F", "door", Interaction.Close));
            var third = e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(third.Accepted);
            Assert.StartsWith("action-economy:", third.Reason);
        }

        [Fact]
        public void Interact_NotAdjacent_Rejected_Reach()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(2, 0, 0), ObjectState.Closed));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(r.Accepted);
            Assert.StartsWith("reach:", r.Reason);
        }

        [Fact]
        public void Close_OccupiedCell_Rejected()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Open));
            e.Add(new Creature("B", Fighter(), Side.Party, new GridPos(1, 0, 0)));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Close));
            Assert.False(r.Accepted);
            Assert.StartsWith("occupied:", r.Reason);
            Assert.Equal(ObjectState.Open, e.GetObject("door")!.State);
        }

        [Fact]
        public void ClosedDoor_BlocksMovement_OpenDoor_DoesNot()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            Assert.True(e.IsBlocked(new GridPos(1, 0, 0)));
            var move1 = e.Handle(new MoveIntent("F", new GridPos(1, 0, 0)));
            Assert.False(move1.Accepted);
            Assert.StartsWith("movement:", move1.Reason);

            e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(e.IsBlocked(new GridPos(1, 0, 0)));
            var move2 = e.Handle(new MoveIntent("F", new GridPos(1, 0, 0)));
            Assert.True(move2.Accepted, move2.Reason);
        }

        [Fact]
        public void ClosedDoor_BlocksSight_OpenDoor_DoesNot()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            Assert.True(e.BlocksSight(new GridPos(1, 0, 0)));
            e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(e.BlocksSight(new GridPos(1, 0, 0)));
        }

        [Fact]
        public void Open_LockedDoor_Rejected_Locked()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            var door = WoodenDoor(); door.LockDc = 15;
            e.AddObject(new WorldObject("door", door, new GridPos(1, 0, 0), ObjectState.Locked));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(r.Accepted);
            Assert.StartsWith("locked:", r.Reason);
        }

        [Fact]
        public void ForceOpen_SpendsAction_EvenOnFailure()
        {
            var found = false;
            for (ulong seed = 1; seed <= 50 && !found; seed++)
            {
                var e = Build(seed, new GridPos(0, 0, 0), Fighter());
                e.AddObject(new WorldObject("chest", IronChest(15), new GridPos(1, 0, 0), ObjectState.Locked));
                var r = e.Handle(new InteractIntent("F", "chest", Interaction.ForceOpen));
                Assert.True(r.Accepted, r.Reason);
                var check = e.Log.Events.OfType<ObjectCheckRolled>().Last();
                if (!check.Success)
                {
                    Assert.False(e.ActionAvailable);
                    Assert.Equal(ObjectState.Locked, e.GetObject("chest")!.State);
                    found = true;
                }
            }
            Assert.True(found, "no failing ForceOpen seed found in range 1..50");
        }

        [Fact]
        public void ForceOpen_Success_OpensAndLogsCheck()
        {
            var found = false;
            for (ulong seed = 1; seed <= 50 && !found; seed++)
            {
                var e = Build(seed, new GridPos(0, 0, 0), Fighter());
                e.AddObject(new WorldObject("chest", IronChest(15), new GridPos(1, 0, 0), ObjectState.Locked));
                e.Handle(new InteractIntent("F", "chest", Interaction.ForceOpen));
                var tail = e.Log.Events.TakeLast(2).ToList();
                if (tail.Count == 2 && tail[0] is ObjectCheckRolled ck && ck.Success && tail[1] is ObjectStateChanged sc && sc.From == ObjectState.Locked && sc.To == ObjectState.Open)
                {
                    Assert.Equal(ObjectState.Open, e.GetObject("chest")!.State);
                    found = true;
                }
            }
            Assert.True(found, "no succeeding ForceOpen seed found in range 1..50");
        }

        [Fact]
        public void PickLock_WithoutTools_Rejected()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("chest", IronChest(15), new GridPos(1, 0, 0), ObjectState.Locked));
            var r = e.Handle(new InteractIntent("F", "chest", Interaction.PickLock));
            Assert.False(r.Accepted);
            Assert.StartsWith("tools:", r.Reason);
        }

        [Fact]
        public void PickLock_Success_UnlocksButStaysClosed()
        {
            var found = false;
            for (ulong seed = 1; seed <= 50 && !found; seed++)
            {
                var e = Build(seed, new GridPos(0, 0, 0), Rogue(), "R");
                e.AddObject(new WorldObject("chest", IronChest(15), new GridPos(1, 0, 0), ObjectState.Locked));
                e.Handle(new InteractIntent("R", "chest", Interaction.PickLock));
                var sc = e.Log.Events.OfType<ObjectStateChanged>().LastOrDefault();
                if (sc != null && sc.From == ObjectState.Locked && sc.To == ObjectState.Closed)
                {
                    Assert.Equal(ObjectState.Closed, e.GetObject("chest")!.State);
                    Assert.Equal("R unlocks chest (action)", sc.Describe());
                    found = true;
                }
            }
            Assert.True(found, "no succeeding PickLock seed found in range 1..50");
        }

        [Fact]
        public void AttackObject_Hit_ReducesHp_PoisonDoesNothing()
        {
            var slashingChecked = false;
            var poisonChecked = false;
            for (ulong seed = 1; seed <= 100 && !(slashingChecked && poisonChecked); seed++)
            {
                if (!slashingChecked)
                {
                    var e = Build(seed, new GridPos(0, 0, 0), Fighter());
                    e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
                    var before = e.GetObject("door")!.Hp;
                    e.Handle(new AttackObjectIntent("F", "door", 0));
                    var atk = e.Log.Events.OfType<ObjectAttackRolled>().Last();
                    if (atk.Hit)
                    {
                        Assert.True(e.GetObject("door")!.Hp < before);
                        slashingChecked = true;
                    }
                }
                if (!poisonChecked)
                {
                    var e2 = Build(seed, new GridPos(0, 0, 0), Fighter());
                    e2.AddObject(new WorldObject("door2", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
                    var before2 = e2.GetObject("door2")!.Hp;
                    e2.Handle(new AttackObjectIntent("F", "door2", 1));
                    var atk2 = e2.Log.Events.OfType<ObjectAttackRolled>().Last();
                    if (atk2.Hit)
                    {
                        var dmg = e2.Log.Events.OfType<ObjectDamaged>().Last();
                        Assert.Equal(0, dmg.Amount);
                        Assert.Equal(before2, e2.GetObject("door2")!.Hp);
                        poisonChecked = true;
                    }
                }
            }
            Assert.True(slashingChecked, "no hitting seed found for the slashing attack in range 1..100");
            Assert.True(poisonChecked, "no hitting seed found for the poison attack in range 1..100");
        }

        [Fact]
        public void AttackObject_ToZero_Breaks_AndStopsBlocking()
        {
            var e = Build(7, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            Assert.True(e.IsBlocked(new GridPos(1, 0, 0)));

            var broke = false;
            for (var i = 0; i < 30 && !broke; i++)
            {
                if (e.Current!.Id == "F" && e.ActionAvailable) e.Handle(new AttackObjectIntent("F", "door", 0));
                e.Handle(new EndTurnIntent(e.Current!.Id));
                if (e.GetObject("door")!.IsBroken) broke = true;
            }
            Assert.True(broke, "door did not break within 30 turns");
            Assert.Equal(0, e.GetObject("door")!.Hp);
            var last = e.Log.Events.OfType<ObjectStateChanged>().Last();
            Assert.Equal(ObjectState.Broken, last.To);
            Assert.Equal("damage", last.Cost);
            Assert.False(e.IsBlocked(new GridPos(1, 0, 0)));
            Assert.False(e.BlocksSight(new GridPos(1, 0, 0)));
            while (e.Current!.Id != "F") e.Handle(new EndTurnIntent(e.Current.Id));
            var r = e.Handle(new InteractIntent("F", "door", Interaction.Open));
            Assert.False(r.Accepted);
            Assert.StartsWith("object:", r.Reason);
        }

        [Fact]
        public void Replay_SameSeedSameIntents_SameFingerprint()
        {
            string Run(ulong seed)
            {
                var e = Build(seed, new GridPos(0, 0, 0), Fighter());
                e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
                e.Handle(new InteractIntent("F", "door", Interaction.Open));
                e.Handle(new MoveIntent("F", new GridPos(1, 0, 0)));
                e.Handle(new InteractIntent("F", "door", Interaction.Close));
                e.Handle(new AttackObjectIntent("F", "door", 0));
                e.Handle(new EndTurnIntent("F"));
                e.Handle(new EndTurnIntent("E"));
                e.Handle(new InteractIntent("F", "door", Interaction.ForceOpen));
                e.Handle(new EndTurnIntent("F"));
                return e.Log.Fingerprint();
            }
            Assert.Equal(Run(11), Run(11));
        }

        [Fact]
        public void FreeInteraction_ResetsEachTurn()
        {
            var e = Build(1, new GridPos(0, 0, 0), Fighter());
            e.AddObject(new WorldObject("door", WoodenDoor(), new GridPos(1, 0, 0), ObjectState.Closed));
            e.Handle(new InteractIntent("F", "door", Interaction.Open));
            var first = e.Log.Events.OfType<ObjectStateChanged>().Last();
            Assert.Equal("free", first.Cost);

            e.Handle(new EndTurnIntent("F"));
            e.Handle(new EndTurnIntent("E"));
            Assert.Equal("F", e.Current!.Id);

            e.Handle(new InteractIntent("F", "door", Interaction.Close));
            var second = e.Log.Events.OfType<ObjectStateChanged>().Last();
            Assert.Equal("free", second.Cost);
        }
    }
}
