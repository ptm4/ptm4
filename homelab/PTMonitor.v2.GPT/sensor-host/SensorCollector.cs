using LibreHardwareMonitor.Hardware;

namespace PTMonitor.SensorHost;

internal sealed record RawSensor(string Id, string Name, SensorType Type, float? Value, float? Min = null, float? Max = null);
internal sealed record SensorReading(string Id, string Name, string Hardware, string HardwareId,
    string RootHardwareId, uint? PhysicalDiskNumber, string HardwareType, string SensorType, string Unit, string Source,
    double Value, double? Min, double? Max);
internal interface IHardwareNode {
    string Id { get; }
    string Name { get; }
    string Type { get; }
    uint? PhysicalDiskNumber => null;
    IEnumerable<RawSensor> Sensors { get; }
    IEnumerable<IHardwareNode> Children { get; }
    void Update();
}
internal sealed class LibreNode(IHardware hardware) : IHardwareNode {
    public string Id => hardware.Identifier.ToString();
    public string Name => hardware.Name;
    public string Type => hardware.HardwareType.ToString();
    public uint? PhysicalDiskNumber => hardware is LibreHardwareMonitor.Hardware.Storage.StorageDevice storage
        ? Convert.ToUInt32(storage.Storage.DriveNumber) : null;
    public IEnumerable<RawSensor> Sensors => hardware.Sensors.Select(s => {
        // PTMonitor owns the rolling history; disable the library's separate 24h history.
        s.ValuesTimeWindow = TimeSpan.Zero;
        return new RawSensor(s.Identifier.ToString(), s.Name, s.SensorType, s.Value, s.Min, s.Max);
    });
    public IEnumerable<IHardwareNode> Children => hardware.SubHardware.Select(child => new LibreNode(child));
    public void Update() => hardware.Update();
}
internal static class SensorCollector {
    public static void Collect(IHardwareNode hardware, string rootId, List<SensorReading> output, List<string> errors, bool cpuRegisterAccess = true) {
        try {
            hardware.Update();
            foreach (var sensor in hardware.Sensors) {
                if (sensor.Value is not { } value || !float.IsFinite(value)) continue;
                // LHM can synthesize zero temperatures/clocks and plausible voltages from
                // failed CPU register reads. Do not present those as measured hardware data.
                if (hardware.Type == "Cpu" && !cpuRegisterAccess && sensor.Type != SensorType.Load) continue;
                if (hardware.Type is "Cpu" or "Storage" && sensor.Type == SensorType.Temperature && value <= 0) continue;
                var (unit, factor) = UnitFor(sensor.Type);
                output.Add(new SensorReading(sensor.Id, sensor.Name, hardware.Name, hardware.Id,
                    rootId, hardware.PhysicalDiskNumber, hardware.Type, sensor.Type.ToString(), unit, "LibreHardwareMonitor 0.9.6",
                    value * factor, Finite(sensor.Min, factor), Finite(sensor.Max, factor)));
            }
        }
        catch (Exception error) { errors.Add($"{hardware.Name}: {error.Message}"); }
        // Failure of one hardware branch does not suppress the rest of the workstation.
        foreach (var child in hardware.Children) Collect(child, rootId, output, errors, cpuRegisterAccess);
    }
    private static double? Finite(float? value, double factor) => value is { } v && float.IsFinite(v) ? v * factor : null;
    internal static (string Unit, double Factor) UnitFor(SensorType type) => type switch {
        SensorType.Temperature => ("°C", 1),
        SensorType.Fan => ("RPM", 1),
        SensorType.Power => ("W", 1),
        SensorType.Clock => ("MHz", 1),
        SensorType.Load or SensorType.Control or SensorType.Level or SensorType.Humidity => ("%", 1),
        SensorType.Voltage => ("V", 1),
        SensorType.Current => ("A", 1),
        SensorType.Frequency => ("Hz", 1),
        SensorType.Flow => ("L/h", 1),
        SensorType.Data => ("MiB", 1024), // LHM Data = GiB (2^30 bytes).
        SensorType.SmallData => ("MiB", 1), // LHM SmallData = MiB (2^20 bytes).
        SensorType.Throughput => ("B/s", 1),
        SensorType.TimeSpan => ("s", 1),
        SensorType.Timing => ("ns", 1),
        SensorType.Energy => ("mWh", 1),
        SensorType.Noise => ("dBA", 1),
        SensorType.Conductivity => ("µS/cm", 1),
        _ => ("", 1),
    };
}
