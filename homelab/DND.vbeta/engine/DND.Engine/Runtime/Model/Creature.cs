using System.Collections.Generic;
using System.Linq;
using DND.Engine.Core;

namespace DND.Engine.Model
{
    public enum Side { Party, Enemy, Neutral }

    /// <summary>Data-only description of a creature (what the compendium provides).</summary>
    public sealed class CreatureTemplate
    {
        public string Id = "";
        public string Name = "";
        public string Ruleset = "2024";
        public AbilityScores Abilities;
        public int MaxHp;
        public int ArmorClass;
        public int SpeedFeet = 30;
        public int ProficiencyBonus = 2;
        public List<AttackTemplate> Attacks = new List<AttackTemplate>();
        public HashSet<string> SkillProficiencies = new HashSet<string>();
        public HashSet<string> ToolProficiencies = new HashSet<string>();
    }

    public sealed class AttackTemplate
    {
        public string Name = "";
        public int ReachFeet = 5;
        public int RangeFeet;       // 0 = melee
        public int LongRangeFeet;   // 0 = melee
        public int AttackBonus;
        public DiceRoll Damage;
        public string DamageType = "slashing";
        public bool IsRanged => RangeFeet > 0;
    }

    /// <summary>Live creature in an encounter: template + mutable combat state.</summary>
    public sealed class Creature
    {
        public readonly string Id;
        public readonly CreatureTemplate Template;
        public readonly Side Side;
        public GridPos Position;
        public int Hp;
        public int TempHp;
        public int Initiative;
        public readonly List<ActiveCondition> Conditions = new List<ActiveCondition>();

        // SRD "Death Saving Throws" (Party creatures only; monsters die outright at 0 HP).
        public int DeathSuccesses, DeathFailures;
        public bool IsStable;

        // SRD "Dodge" / "Reactions": per-turn state cleared by Encounter.AdvanceTurn.
        public bool Dodging;
        public bool ReactionAvailable = true;

        public Creature(string id, CreatureTemplate template, Side side, GridPos position)
        {
            Id = id; Template = template; Side = side; Position = position;
            Hp = template.MaxHp;
        }

        public string Name => Template.Name;
        public int ArmorClass => Template.ArmorClass;
        /// <summary>SRD "Exhaustion": speed drops 5 ft per level (floor 0).</summary>
        public int SpeedFeet => System.Math.Max(0, Template.SpeedFeet - 5 * ExhaustionLevel);
        /// <summary>Unconscious also auto-applies whenever the creature is Down and not dead (SRD "Dropping
        /// to 0 Hit Points"), without needing anyone to call ApplyCondition/RemoveCondition for it.</summary>
        public bool Has(Condition c) => c == Condition.Unconscious
            ? (IsDown && !IsDead) || Conditions.Any(ac => ac.Kind == c)
            : Conditions.Any(ac => ac.Kind == c);
        public int ExhaustionLevel => Conditions.Where(ac => ac.Kind == Condition.Exhaustion).Select(ac => ac.Level).DefaultIfEmpty(0).Max();
        /// <summary>SRD "Dropping to 0 Hit Points": monsters die outright; a Party creature is dead only
        /// after 3 death-save failures (instant death also sets DeathFailures to 3).</summary>
        public bool IsDead => Hp <= 0 && (Side != Side.Party || DeathFailures >= 3);
        /// <summary>SRD "Death Saving Throws": a Party creature at 0 HP, not dead, not yet stabilized.</summary>
        public bool IsDying => Side == Side.Party && Hp <= 0 && !IsDead && !IsStable;
        /// <summary>At 0 HP, regardless of side (used for the "unconscious" action-economy gate and party wipe checks).</summary>
        public bool IsDown => Hp <= 0;
        public int DexMod => Template.Abilities.Mod(Ability.Dex);
        public int StrMod => Template.Abilities.Mod(Ability.Str);
        public int SkillMod(Ability ability, string skill) => Template.Abilities.Mod(ability) + (Template.SkillProficiencies.Contains(skill) ? Template.ProficiencyBonus : 0);

        /// <summary>Applies damage: temp HP absorbs first (SRD), HP floors at 0. Returns HP actually lost.</summary>
        public int ApplyDamage(int amount) => ApplyDamage(amount, out _);

        /// <summary>As <see cref="ApplyDamage(int)"/>, and also reports the damage left over after HP hit
        /// 0 (SRD "Instant Death" massive-damage check; 0 if HP did not reach 0).</summary>
        public int ApplyDamage(int amount, out int overkill)
        {
            overkill = 0;
            if (amount <= 0) return 0;
            var fromTemp = System.Math.Min(TempHp, amount);
            TempHp -= fromTemp;
            var remainder = amount - fromTemp;
            var toHp = System.Math.Min(Hp, remainder);
            overkill = remainder - toHp;
            Hp -= toHp;
            return toHp;
        }

        /// <summary>SRD: heals HP up to max and ends the dying/stable state.</summary>
        public void Heal(int amount)
        {
            Hp = System.Math.Min(Template.MaxHp, Hp + amount);
            DeathSuccesses = 0;
            DeathFailures = 0;
            IsStable = false;
        }
    }
}
