using DND.Engine.Core;

namespace DND.Engine.Model
{
    public enum ObjectKind { Door, Chest, Lever, Other }
    public enum ObjectMaterial { Cloth, Crystal, Wood, Stone, Iron, Mithral, Adamantine }
    public enum ObjectSize { Tiny, Small, Medium, Large }
    public enum ObjectState { Open, Closed, Locked, Broken }
    /// <summary>What a creature does to an object (InteractIntent.Kind). Lives in Model so Events can name it without depending on Intents.</summary>
    public enum Interaction { Open, Close, ForceOpen, PickLock }

    public sealed class ObjectTemplate
    {
        public string Id = "";
        public string Name = "";
        public string Ruleset = "2024";
        public ObjectKind Kind = ObjectKind.Other;
        public ObjectMaterial Material = ObjectMaterial.Wood;
        public ObjectSize Size = ObjectSize.Medium;
        public bool Fragile;                    // false = resilient
        public int? LockDc;                     // null = no lock. Applies to PickLock and ForceOpen when Locked.
        public int? StuckDc;                    // null = not stuck. Applies to ForceOpen when Closed (not locked).
        public bool BlocksMovementWhenClosed = true;
        public bool BlocksSightWhenClosed = true;
        public int ArmorClass => Material switch { ObjectMaterial.Cloth => 11, ObjectMaterial.Crystal => 13, ObjectMaterial.Wood => 15, ObjectMaterial.Stone => 17, ObjectMaterial.Iron => 19, ObjectMaterial.Mithral => 21, _ => 23 };
        public int MaxHp => (Size, Fragile) switch { (ObjectSize.Tiny, true) => 2, (ObjectSize.Tiny, false) => 5, (ObjectSize.Small, true) => 3, (ObjectSize.Small, false) => 10, (ObjectSize.Medium, true) => 4, (ObjectSize.Medium, false) => 18, (ObjectSize.Large, true) => 5, _ => 27 };
    }

    public sealed class WorldObject
    {
        public readonly string Id;
        public readonly ObjectTemplate Template;
        public GridPos Cell;
        public ObjectState State;
        public int Hp;
        public WorldObject(string id, ObjectTemplate template, GridPos cell, ObjectState initial) { Id = id; Template = template; Cell = cell; State = initial; Hp = template.MaxHp; }
        public bool IsBroken => State == ObjectState.Broken;
        public bool BlocksMovement => !IsBroken && State != ObjectState.Open && Template.BlocksMovementWhenClosed;
        public bool BlocksSight => !IsBroken && State != ObjectState.Open && Template.BlocksSightWhenClosed;
    }
}
