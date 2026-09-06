# PTMonitor SensorHost — third-party notices

The bundled helper uses unmodified LibreHardwareMonitorLib 0.9.6 from the official
NuGet package. The exact dependency graph and package hashes are pinned in
packages.lock.json. It embeds its .NET 8 runtime and native runtime libraries.

## Sensor libraries

- LibreHardwareMonitorLib 0.9.6 — MPL-2.0, LibreHardwareMonitor and Contributors.
  Corresponding source: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/tree/3d331e3370efb858411f19511373eff65a218701
- DiskInfoToolkit 1.1.2 — MPL-2.0, Florian K.
  Corresponding source: https://github.com/Blacktempel/DiskInfoToolkit/tree/25319eae5781e75bcf141e844ceab2afe94d40ea
- RAMSPDToolkit-NDD 1.4.2 — MPL-2.0, Florian K.
  Corresponding source: https://github.com/Blacktempel/RAMSPDToolkit/tree/3b47b960e0830fef344624ad5e389675d5f0a1ce
- BlackSharp.Core 1.0.7 — MPL-2.0, Florian K.
  Corresponding source: https://github.com/Blacktempel/BlackSharp/tree/c70b735c6cec123ee8a046ac4a0bc6c606f52cf0
- HidSharp 2.6.4 — Apache-2.0, James F. Bellinger / Bleakwind.
  Source: https://github.com/IntergatedCircuits/HidSharp
- Mono.Posix.NETStandard 1.0.0 — Mono project license, Microsoft / Mono contributors.
  Source: https://github.com/mono/mono

## Runtime

.NET runtime 8.0.30 and Microsoft System.* package dependencies are licensed under
MIT and the additional bundled notices. Runtime source:
https://github.com/dotnet/runtime. Specific package versions are in packages.lock.json.

The licenses directory includes the complete MPL-2.0, HidSharp, Mono, .NET runtime
license text, and upstream LHM/.NET third-party notices. This directory and this
notice are included in the Windows installer.

## Local hardware access

Standard access is the default. GPU vendor APIs may expose temperatures, fans and
power without elevation. CPU register readings, storage SMART, motherboard fans
and controllers depend on supported hardware, driver availability, and privileges.
LibreHardwareMonitor may load its hardware-access kernel driver while the
explicitly elevated app is running. PTMonitor never alters Windows security
protections or configures a persistent user-mode monitoring service.
