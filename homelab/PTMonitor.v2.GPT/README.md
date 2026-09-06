# PTMonitor v2 — workstation sidecar

A local Windows 11 monitor with a 312 × 452 acrylic dashboard, a 580 × 720
workstation inspector and a genuinely live notification-area icon. Built from an
independent copy of PTMonitor; `../PTMonitor-widget` is not modified.

## Use

- Drag the header onto your side monitor. The card stays on top without taking
  focus when readings change. **↗** opens the inspector; **−** hides to the tray.
- The tray's three bars are **CPU / RAM / GPU**. Hover for numeric readings;
  left-click shows/hides the dashboard. A warm/red outline indicates an active
  disk-capacity or thermal warning/critical condition. Missing GPU data is a dash,
  not a zero reading. Icons are rasterized at 64 px for high-DPI displays.
- Right-click the tray for readings, settings, refresh, corner snapping,
  interaction recovery, startup behavior and quit. Windows decides whether an
  icon is visible or in overflow. Under **Settings → Personalization → Taskbar →
  Other system tray icons**, enable PTMonitor v2 to keep it visible.
- Settings separate background tint from whole-card opacity (25–100%).
  Click-through passes pointer events to whatever is behind the dashboard.
  **Recover interaction** in the tray always turns it off; launching v2 again
  also recovers interaction in the existing instance.
- Overview has 60-second charts, temperatures, clocks, power, VRAM, physical-disk
  temperatures where available, all local fixed volumes and network/disk I/O.
  Sensors exposes raw names, units, identity, provenance and session min/max.
  Activity has top CPU/memory processes, the alert timeline and collection health.

## Truthful hardware access

Standard access is the default: **no automatic UAC prompt**. GPU vendor APIs often
provide useful temperature, fan, power and VRAM data without administrator rights.
CPU package temperature, SMART, motherboard fans and controller readings depend
on hardware, privileges and Windows driver policy. Unavailable readings are `—`;
zero fan speed is preserved when a supported fan has genuinely stopped.

**Restart as administrator…** requires an explicit in-app confirmation and then
the Windows approval prompt. It elevates this instance of PTMonitor and its
stdio-connected helper for the session, not the normal startup registration.
Motherboard discovery is a separate switch and requires elevated access. Libre
Hardware Monitor may load a hardware-access **kernel driver** in this mode; it is
not a guaranteed route to every sensor. PTMonitor does not change Windows security
settings, install a permanent user-mode monitoring service, or bypass blocked drivers.

The GPU summary selects one stable hardware identity, preferring a discrete NVIDIA
then AMD adapter. Every summary sensor comes from that same device. If there is no
sensor GPU identity, Windows PDH supplies the busiest GPU engine across adapters;
it never sums unrelated engines into a misleading utilization number. All detected
GPU sensors remain available in the Sensors view. CPU clock uses averaged sensor
core clocks when available and the OS-reported clock as fallback (not necessarily
the instantaneous boost clock).

Volumes are ordered by the Windows system volume, then fullest first. Their
temperature is joined through native volume extents and LHM's physical disk number,
not through guessed drive labels. Multi-disk volumes show the hottest matching
component. Fixed local volumes only: removable media and mapped network shares are
excluded to keep slow/offline remote drives out of the collection path.

## Lightweight architecture

| Component | Cadence / storage |
|---|---|
| Rust sampling service | CPU, memory, uptime, native adapter counters and PDH every 1 second |
| Process ranking | CPU + working-set refresh every 3 seconds; CPU normalized to the whole machine |
| Local disk discovery/capacity | Separate worker, cached 20 seconds; manual refresh requests this cache |
| Bundled .NET 8 sensor host | One-second normalized JSON-lines frames over redirected stdin/stdout |
| UI and live tray | Consume the same native snapshot; neither launches collectors |
| History and alerts | Last 60 seconds of chart samples and up to 100 alert transitions in memory only |

There is **no monitoring HTTP server, TCP listener, browser telemetry polling,
database, cloud upload, recurring PowerShell process or separately installed sensor
application**. Build/test scripts use PowerShell; the installed app does not.
GetIfTable2 is used directly for adapter counters because sysinfo filters some VPN
interfaces. Hotplug/counter resets establish new baselines, and automatic adapter
selection uses hysteresis so idle periods do not switch labels every second.

The helper has bounded frames/queues, protocol validation, a parent heartbeat and
exit watchdog. Rust clears stale sensors, reaps failed children and retries with
backoff. Core monitoring remains available while the helper is missing or restarting.
Meter changes do not animate between samples. Hidden dashboards receive no snapshot
events or chart repaints; the native service/tray keeps running and the last minute
of history is restored on reopening. WebView2 and the bundled .NET runtime still
have a meaningful memory footprint: this is not a native-only, few-megabyte utility.

Alerts have sustained-condition checks and recovery hysteresis. CPU/GPU load stays
visual-only to avoid interrupting games. Windows notifications are **off by default**;
when enabled, memory/disk/thermal transitions are combined with a 60-second global
cooldown. Use the installed application for registered Windows notifications;
Focus Assist/Do Not Disturb and OS policy can suppress them.

## Build and test

Windows x64 build prerequisites:

1. Rust stable with the MSVC target, Visual Studio C++ Build Tools and Windows SDK.
2. Node.js 20+ with npm, and the **.NET 8 SDK** (a runtime alone is insufficient).
3. Microsoft Edge WebView2 Runtime on the target workstation. The NSIS installer
   can bootstrap WebView2 if absent; that prerequisite download is not telemetry.

```powershell
npm ci
npm test
npm run test:native
npm run test:sensors
npm run build
```

The sensor build accepts an explicit portable SDK without installing it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File sensor-host/build.ps1 -DotnetPath C:\SDKs\dotnet8\dotnet.exe
```

For iteration, build the helper first with `npm run build:sensors`, then `npm run dev`.
Quit running development instances before rebuilding the helper: Windows locks
running executables. An optional portable SDK already at
`%LOCALAPPDATA%\PTMonitor-build\dotnet-8\dotnet.exe` is detected automatically.
No SDK is downloaded by the checked-in build script.

`npm run build` publishes and self-tests the real, self-contained helper, then uses
`src-tauri/tauri.bundle.conf.json` to package it as a Tauri **externalBin** together
with its licenses. There are no fake executable placeholders. Generated binaries
are ignored by git. Use the npm build command for releases; plain `cargo build`
does not assemble an installer or the release sidecar layout.

Outputs:

- `src-tauri/target/release/ptmonitor-v2.exe`
- `src-tauri/target/release/PTMonitor.SensorHost.exe` (keep adjacent for a portable run)
- `src-tauri/target/release/bundle/nsis/PTMonitor v2_2.0.0_x64-setup.exe`

The NSIS installer is per-user. Both v1 and v2 can remain installed: v2 uses
`com.ptm.ptmonitor.v2`, version `2.0.0`, startup value `PTMonitorV2`, and its own
`%LOCALAPPDATA%\PTMonitor-v2\settings.json`. Settings are clamped, flushed and
atomically replaced; drag placement is debounced. No v1 settings are read/migrated.
This is an unsigned local build: distributing a trusted release requires your
normal signing process. Do not disable Windows protections to run it.

## Additional validation

```powershell
# Read-only real Windows sampling and supervisor checks (no elevation):
cargo test --manifest-path src-tauri/Cargo.toml native_windows_sampling_smoke -- --ignored --nocapture
powershell -NoProfile -ExecutionPolicy Bypass -File sensor-host/test-runtime.ps1

# Optional browser QA; Playwright and Edge are developer-only dependencies:
node test/browser-check.mjs C:\path\to\playwright\index.mjs
```

The browser harness briefly hosts a **development-only loopback preview**, with
explicit **DEMO DATA** fixtures, and shuts it down afterwards. It checks rendering
at 100/125/150%, long strings, escaping, stale/missing sensors and settings behavior.
Its server and dependencies are not part of the application runtime.

See [VALIDATION.md](VALIDATION.md) for completed checks and the remaining physical
hardware/manual release matrix. Diagnostics include process/hardware/interface names
and MAC addresses; review any copied diagnostic data before sharing it.

License texts and exact sensor dependency versions/source links are in
[sensor-host/THIRD-PARTY-NOTICES.md](sensor-host/THIRD-PARTY-NOTICES.md).
