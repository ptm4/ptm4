using System.Collections.Generic;
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
        public int AttackBonus;
        public DiceRoll Damage;
        public string DamageType = "slashing";
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
        public readonly HashSet<string> Conditions = new HashSet<string>();

        public Creature(string id, CreatureTemplate template, Side side, GridPos position)
        {
            Id = id; Template = template; Side = side; Position = position;
            Hp = template.MaxHp;
        }

        public string Name => Template.Name;
        public int ArmorClass => Template.ArmorClass;
        public int SpeedFeet => Template.SpeedFeet;
        public bool IsDead => Hp <= 0;
        public int DexMod => Template.Abilities.Mod(Ability.Dex);
        public int StrMod => Template.Abilities.Mod(Ability.Str);
        public int SkillMod(Ability ability, string skill) => Template.Abilities.Mod(ability) + (Template.SkillProficiencies.Contains(skill) ? Template.ProficiencyBonus : 0);

        /// <summary>Applies damage: temp HP absorbs first (SRD), HP floors at 0. Returns HP actually lost.</summary>
        public int ApplyDamage(int amount)
        {
            if (amount <= 0) return 0;
            var fromTemp = System.Math.Min(TempHp, amount);
            TempHp -= fromTemp;
            var toHp = System.Math.Min(Hp, amount - fromTemp);
            Hp -= toHp;
            return toHp;
        }
    }
}
