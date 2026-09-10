using System;

namespace DND.Engine.Core
{
    /// <summary>Deterministic random source. Every rule that rolls takes one of these.</summary>
    public interface IRng
    {
        /// <summary>Uniform integer in [1, sides].</summary>
        int Roll(int sides);
        /// <summary>Uniform integer in [0, maxExclusive).</summary>
        int Next(int maxExclusive);
    }

    /// <summary>
    /// xorshift64* generator: platform-independent (System.Random differs across runtimes),
    /// tiny, and good enough for dice. Same seed, same sequence, everywhere.
    /// </summary>
    public sealed class SeededRng : IRng
    {
        private ulong _state;

        public SeededRng(ulong seed)
        {
            _state = seed == 0 ? 0x9E3779B97F4A7C15UL : seed;
        }

        public ulong NextRaw()
        {
            var x = _state;
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            _state = x;
            return x * 0x2545F4914F6CDD1DUL;
        }

        public int Next(int maxExclusive)
        {
            if (maxExclusive <= 0) throw new ArgumentOutOfRangeException(nameof(maxExclusive));
            return (int)(NextRaw() % (ulong)maxExclusive);
        }

        public int Roll(int sides) => Next(sides) + 1;
    }
}
