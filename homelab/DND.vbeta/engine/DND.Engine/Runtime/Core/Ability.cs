using System;

namespace DND.Engine.Core
{
    public enum Ability { Str, Dex, Con, Int, Wis, Cha }

    public static class AbilityMath
    {
        /// <summary>SRD: modifier = floor((score - 10) / 2).</summary>
        public static int Modifier(int score) => (int)Math.Floor((score - 10) / 2.0);

        /// <summary>SRD 2024 proficiency bonus by character level or monster CR-derived level.</summary>
        public static int ProficiencyBonusForLevel(int level) => 2 + (Math.Max(1, Math.Min(20, level)) - 1) / 4;
    }

    /// <summary>The six scores. Immutable; use With() to derive.</summary>
    public readonly struct AbilityScores
    {
        public readonly int Str, Dex, Con, Int, Wis, Cha;

        public AbilityScores(int str, int dex, int con, int @int, int wis, int cha)
        {
            Str = str; Dex = dex; Con = con; Int = @int; Wis = wis; Cha = cha;
        }

        public int this[Ability a] => a switch
        {
            Ability.Str => Str, Ability.Dex => Dex, Ability.Con => Con,
            Ability.Int => Int, Ability.Wis => Wis, _ => Cha,
        };

        public int Mod(Ability a) => AbilityMath.Modifier(this[a]);
    }
}
