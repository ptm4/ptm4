using System;

namespace DND.Engine.Core
{
    /// <summary>A 5-ft cell on a 3D grid. Y is elevation in 5-ft steps (voxel terraces).</summary>
    public readonly struct GridPos : IEquatable<GridPos>
    {
        public readonly int X, Y, Z;
        public GridPos(int x, int y, int z) { X = x; Y = y; Z = z; }

        public const int FeetPerCell = 5;

        /// <summary>Chebyshev distance in cells: the 5-5-5 diagonal rule (D31/03b decision, 2024 default).</summary>
        public static int Cells(GridPos a, GridPos b) =>
            Math.Max(Math.Max(Math.Abs(a.X - b.X), Math.Abs(a.Y - b.Y)), Math.Abs(a.Z - b.Z));

        public static int Feet(GridPos a, GridPos b) => Cells(a, b) * FeetPerCell;

        public bool IsAdjacent(GridPos other) => Cells(this, other) == 1;

        public GridPos Offset(int dx, int dy, int dz) => new GridPos(X + dx, Y + dy, Z + dz);

        public bool Equals(GridPos o) => X == o.X && Y == o.Y && Z == o.Z;
        public override bool Equals(object obj) => obj is GridPos o && Equals(o);
        public override int GetHashCode() => unchecked(X * 73856093 ^ Y * 19349663 ^ Z * 83492791);
        public static bool operator ==(GridPos a, GridPos b) => a.Equals(b);
        public static bool operator !=(GridPos a, GridPos b) => !a.Equals(b);
        public override string ToString() => $"({X},{Y},{Z})";
    }
}
