using LibreHardwareMonitor.Hardware;
namespace PTMonitor.SensorHost;

internal static class SensorTests {
    public static void Run() {
        var child = new FakeNode("/gpu/0/child", "GpuNvidia",
            [new("/gpu/0/child/temp", "GPU Core", SensorType.Temperature, 64), new("/gpu/0/child/invalid", "Invalid", SensorType.Power, float.NaN)]);
        var root = new FakeNode("/gpu/0", "GpuNvidia",
            [new("/gpu/0/memory", "GPU Memory Used", SensorType.Data, 1.5f, 1, 2)],
            [child, new FakeNode("/bad", "Controller", [], fail: true)]);
        var readings = new List<SensorReading>();
        var errors = new List<string>();
        SensorCollector.Collect(root, root.Id, readings, errors);
        Check(readings.Count == 2, "Absent or non-finite readings are omitted.");
        Check(readings[0].Value == 1536 && readings[0].Min == 1024 && readings[0].Max == 2048 && readings[0].Unit == "MiB", "GiB normalization includes min/max.");
        Check(readings[1].HardwareId == "/gpu/0/child" && readings[1].RootHardwareId == "/gpu/0", "Sub-hardware retains physical-device identity.");
        Check(errors.Count == 1 && child.Updates == 1, "One failing hardware branch does not drop healthy readings.");
        Check(SensorCollector.UnitFor(SensorType.SmallData) == ("MiB", 1d), "SmallData must not be multiplied.");
        Check(readings.All(r => r.Source.Contains("0.9.6")), "Every reading carries provenance.");
        readings.Clear();
        SensorCollector.Collect(new FakeNode("/cpu", "Cpu", [new("/cpu/temp", "CPU Package", SensorType.Temperature, 0), new("/cpu/vid", "CPU VID", SensorType.Voltage, 1.55f)]), "/cpu", readings, errors, false);
        Check(readings.Count == 0, "Unprivileged CPU register fallback values are not readings.");
        Console.WriteLine("PASS: 7 sensor-host checks (mock hardware, identity, units, unavailable data, isolation, provenance, permissions).");
    }
    private static void Check(bool condition, string message) {
        if (!condition) throw new InvalidOperationException(message);
    }
    private sealed class FakeNode(string id, string type, RawSensor[] sensors, IHardwareNode[]? children = null, bool fail = false) : IHardwareNode {
        public string Id => id;
        public string Name => id;
        public string Type => type;
        public IEnumerable<RawSensor> Sensors => sensors;
        public IEnumerable<IHardwareNode> Children => children ?? [];
        public int Updates { get; private set; }
        public void Update() { Updates++; if (fail) throw new InvalidOperationException("Mock hardware is unavailable."); }
    }
}
