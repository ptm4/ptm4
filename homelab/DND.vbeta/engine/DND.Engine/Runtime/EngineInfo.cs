namespace DND.Engine
{
    /// <summary>
    /// Placeholder so the package compiles in both Unity and dotnet. Plan 03 replaces this
    /// with the real domain model. Keep everything in this assembly free of UnityEngine.
    /// </summary>
    public static class EngineInfo
    {
        public const string Version = "0.1.0";

        /// <summary>Ruleset tags every content entry must carry (D14).</summary>
        public static class Ruleset
        {
            public const string Srd52 = "2024";
            public const string Srd51 = "2014";
        }
    }
}
