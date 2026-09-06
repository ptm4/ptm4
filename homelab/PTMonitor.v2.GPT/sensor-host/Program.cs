using System.Diagnostics;
using System.Security.Principal;
using System.Text.Json;
using LibreHardwareMonitor.Hardware;
using PTMonitor.SensorHost;

if (args.Contains("--self-test")) {
    SensorTests.Run();
    return;
}
if (!args.Contains("--stdio")) {
    Console.Error.WriteLine("PTMonitor sensor helper. Use --stdio; this program has no network API.");
    Environment.ExitCode = 2;
    return;
}
var advanced = args.Contains("--advanced");
var once = args.Contains("--once"); // Explicit command-line diagnostic; no daemon is started.
var elevated = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
var json = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
using var shutdown = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; shutdown.Cancel(); };
Process? parent = null;
var parentIndex = Array.IndexOf(args, "--parent-pid");
if (parentIndex >= 0) {
    if (parentIndex + 1 >= args.Length || !int.TryParse(args[parentIndex + 1], out var parentId)) {
        Console.Error.WriteLine("Invalid parent process ID.");
        Environment.ExitCode = 2;
        return;
    }
    try { parent = Process.GetProcessById(parentId); }
    catch (ArgumentException) { return; }
    var lastParentPing = Environment.TickCount64;
    // If the GUI exits abruptly, terminate even if a vendor API is stuck in native code.
    _ = Task.Run(async () => {
        try { await parent.WaitForExitAsync(); }
        finally { Environment.Exit(0); }
    });
    _ = Task.Run(async () => {
        while (await Console.In.ReadLineAsync() is { } line) {
            if (line == "quit") break;
            if (line == "ping") Interlocked.Exchange(ref lastParentPing, Environment.TickCount64);
        }
        shutdown.Cancel();
        await Task.Delay(1500);
        Environment.Exit(0); // Bounds disposal of vendor libraries with foreground threads.
    });
    _ = Task.Run(async () => {
        using var watchdog = new PeriodicTimer(TimeSpan.FromSeconds(2));
        while (await watchdog.WaitForNextTickAsync()) {
            if (Environment.TickCount64 - Interlocked.Read(ref lastParentPing) > 15000) {
                shutdown.Cancel();
                await Task.Delay(2000);
                Environment.Exit(2); // Also bounds a hung native vendor call.
            }
        }
    });
}
var computer = new Computer {
    IsCpuEnabled = true,
    IsGpuEnabled = true,
    IsMemoryEnabled = false,
    IsStorageEnabled = true,
    IsNetworkEnabled = false,
    IsMotherboardEnabled = advanced && elevated,
    IsControllerEnabled = advanced && elevated,
};
try {
    computer.Open();
    using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
    do {
        var errors = new List<string>();
        var sensors = new List<SensorReading>();
        foreach (var hardware in computer.Hardware) {
            SensorCollector.Collect(new LibreNode(hardware), hardware.Identifier.ToString(), sensors, errors, elevated);
        }
        var detail = elevated
            ? "Elevated hardware access. Firmware or Windows driver protections may still restrict sensors."
            : "Standard access. CPU package temperature and motherboard fans may require advanced access.";
        if (advanced && !elevated) detail += " Advanced access was requested, but this process is not elevated.";
        if (!sensors.Any(s => s.HardwareType == "Storage" && s.SensorType == "Temperature"))
            detail += " Storage temperature is unavailable at this access level or on this hardware.";
        if (errors.Count > 0) detail += " " + string.Join("; ", errors.Take(5));
        var envelope = new Envelope(1, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            sensors, sensors.Count == 0 ? "unavailable" : errors.Count > 0 ? "partial" : "online", detail,
            elevated, "LibreHardwareMonitor 0.9.6");
        Console.WriteLine(JsonSerializer.Serialize(envelope, json));
        Console.Out.Flush();
        if (once) break;
    } while (await timer.WaitForNextTickAsync(shutdown.Token));
}
catch (OperationCanceledException) when (shutdown.IsCancellationRequested) { }
catch (Exception error) {
    Console.WriteLine(JsonSerializer.Serialize(new Envelope(1, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        [], "error", error.Message, elevated, "LibreHardwareMonitor 0.9.6"), json));
    Console.Out.Flush();
    Environment.ExitCode = 1;
}
finally {
    // Some vendor libraries leave foreground threads or block while disposing.
    // Bound every exit path, including the standalone --once diagnostic.
    _ = Task.Run(async () => { await Task.Delay(1500); Environment.Exit(Environment.ExitCode); });
    computer.Close();
    parent?.Dispose();
    Environment.Exit(Environment.ExitCode);
}

internal sealed record Envelope(int ProtocolVersion, long TimestampMs, List<SensorReading> Sensors,
    string Status, string? Detail, bool Elevated, string Provider);
