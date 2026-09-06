# PTMonitor 2

A lightweight system-monitor widget for Windows 11: one small native `ptmonitor2.exe`, no webview,
no runtime, no child processes. Written in Rust on the `windows` crate — a Win32 popup window whose
pixels come from a DirectComposition swap chain, drawn with Direct2D and DirectWrite.

It shows CPU, RAM, GPU (utilization, VRAM, temperature, power on NVIDIA), one row per fixed volume,
network throughput, and system uptime, with 2-minute sparklines on the rate metrics, in a dark
Fluent-style card with real Acrylic behind it.

This folder is the v2 rewrite of `../PTMonitor-widget` (Tauri 2 + WebView2), which is kept untouched
as the legacy reference. Both can run side by side: v2 has its own settings folder
(`%LOCALAPPDATA%\PTMonitor2`), Run-key value (`PTMonitor2`), window class, and single-instance mutex.

## Why a rewrite

Measured on the legacy build after 23.5 h of uptime, and on v2 after the rewrite (same machine,
Ryzen 7 5800X + RTX 4070 Ti, Windows 11 26200):

| | Legacy PTMonitor (Tauri) | PTMonitor 2 |
|---|---|---|
| Processes | 7 (exe + 6 WebView2) + a `powershell.exe` every 4 s | 1 |
| Private memory | ≈ 190 MB | 29–31 MB (WARP renderer, default) · 79 MB with the hardware renderer |
| CPU, widget visible (2 s cadence, 180 s) | ≈ 26% of one core (20% was the PowerShell GPU probe, 6% WebView2 compositing) | 0.16% of one core |
| CPU, widget hidden (120 s) | unchanged (nothing paused) | 0.00% (sampler parked, no timers) |
| CPU, hidden by game mode (120 s) | n/a | 0.013% (one shell query every 2 s) |
| Threads | 25 + WebView2 | 15 visible, 9–12 hidden |
| GPU use by the widget | compositor work every tick | none (software rasterizer, DWM composes the frame) |

Numbers from `tools/tests/measure_run.ps1` on 2026-09-06 (`dwm.exe` showed no measurable delta);
see *Measuring* below to reproduce.

## Build

```
cargo build --release --offline
```

Requirements: the Rust MSVC toolchain and a Windows SDK with `rc.exe` (for the icon and the
per-monitor-DPI manifest). Everything else is in the cargo cache. Output:
`target\release\ptmonitor2.exe` (≈ 300 KB). Drop `--offline` if a crate is missing locally.

Unit tests (formatting, sparkline rings, dirty tracking, layout heights, config load/migrate/save,
hotkey parsing): `cargo test --offline`.

## Run

Launch `ptmonitor2.exe`. First run: the card appears bottom-right on the primary monitor, or at the
position imported from the legacy settings file if one exists. A tray icon appears; the card takes
no keyboard focus and never steals activation from your apps.

- **Move**: drag the card anywhere (the OS move loop; no Snap Layouts).
- **Settings**: right-click the card, right-click the tray icon, or click the gear that appears when
  you hover the header. One native menu:
  `Show/Hide` · Layer (always on top / normal / pinned to desktop) · Backdrop (auto, acrylic,
  mica, blur, none) · Opacity (100/75/50/25%) · Click-through · Sparklines · Pause in fullscreen
  games · Launch on startup · Start hidden · Open settings.json · Reload settings · About · Quit.
- **Hotkey**: `Ctrl+Alt+P` toggles the widget (configurable; shown greyed in the menu if another
  app owns the combo).
- **Tray**: left-click toggles; the tooltip shows live CPU/GPU/RAM/network.
- **Game mode** (default on): when a fullscreen app owns the screen the widget hides itself and
  sampling pauses; it comes back within 2 s of leaving fullscreen.
- **Hidden** (tray, hotkey, or game mode) means the sampler thread is parked — no timers, no
  wakeups.
- Launching the exe again while it runs just reveals the existing instance.

## Settings

`%LOCALAPPDATA%\PTMonitor2\settings.json` — written atomically, every key optional, unknown keys
ignored, previous file kept as `settings.json.bak`, an unreadable file is set aside as
`settings.json.bak-<stamp>` and defaults are used.

```json
{
  "schema": 2,
  "window": { "placed": true, "x": 2575, "y": 886, "monitor": "DISPLAY1", "dpi": 96 },
  "opacity": 0.75,
  "layer": "topmost",
  "backdrop": "auto",
  "click_through": false,
  "start_hidden": false,
  "autostart": false,
  "hotkey": "Ctrl+Alt+P",
  "game_mode": true,
  "sparklines": true,
  "interval_ms": 2000,
  "disks": null,
  "net_adapters": null,
  "gpu_source": "auto",
  "uptime": "system",
  "renderer": "warp",
  "migrated_from_v1": "2026-09-06T00:29:51"
}
```

| Key | Values | Notes |
|---|---|---|
| `window` | physical px + monitor device name + DPI | saved when a drag ends; restored on the same monitor (rescaled if its DPI changed) and clamped on-screen, so an unplugged monitor never strands the widget |
| `opacity` | 1.0, 0.75, 0.5, 0.25 | applied as a DirectComposition property, no redraw |
| `layer` | `topmost`, `normal`, `desktop` | `desktop` keeps the card under other windows (Win+D still hides it, like any window) |
| `backdrop` | `auto`, `acrylic`, `mica`, `blur`, `none` | `auto` = Acrylic when the OS supports it and transparency effects are on, else flat glass |
| `hotkey` | `[Ctrl+][Alt+][Shift+][Win+]<A-Z, 0-9, F1-F24>`, `""` disables | must include a modifier |
| `game_mode` | bool | hide + pause while `SHQueryUserNotificationState` reports a fullscreen app |
| `interval_ms` | 1000–10000 | sampling cadence; sparklines always span ~2 minutes |
| `disks` | `null` or `["C", "E"]` | `null` = every fixed volume ≥ 1 GB |
| `net_adapters` | `null` or interface aliases | `null` = every connected hardware adapter (loopback, tunnels, vEthernet excluded) |
| `gpu_source` | `auto`, `nvml`, `pdh`, `off` | `auto` = NVML when `nvml.dll` loads, else the GPU Engine performance counters |
| `uptime` | `system`, `app` | footer shows time since boot, or since the widget started |
| `renderer` | `warp`, `hardware` | `warp` (default) never loads the GPU driver: 30 MB and 15 threads vs 79 MB and 59 threads measured with `hardware` |

Advanced keys (`hotkey`, `interval_ms`, `disks`, `net_adapters`, `gpu_source`, `uptime`, `renderer`)
are edited in the file: *Open settings.json* then *Reload settings* from the menu.

### Migration from the legacy widget

If `%LOCALAPPDATA%\PTMonitor\settings.json` exists and no v2 file does, v2 imports position,
opacity, start-hidden and click-through once, records `migrated_from_v1`, and never touches the
legacy file. **Launch on startup is deliberately imported as off**: the legacy widget's own Run entry
may still be active. To retire the legacy widget, turn off *Launch on Startup* in its tray menu,
then turn on *Launch on startup* in PTMonitor 2.

## Measuring

`tools/measure.ps1 -Minutes 5` samples a running `ptmonitor2` process: private bytes at start and
end, CPU as a share of one core, own-PID GPU engine use, threads, handles, child processes, and the
`dwm.exe` CPU delta (the Acrylic blur runs inside DWM, not in this process). Run it once visible,
once hidden (hotkey), and once with a fullscreen game in front.

Budget: ≤ 30 MB private, ≤ 0.3% of one core visible at a 2 s cadence, ≈ 0% hidden, zero child
processes. Recorded results are in the table at the top.

## Architecture

```
src/main.rs            entry: DPI awareness, single instance, config load, run
src/app.rs             UI-thread state machine: window messages, tray/menu commands, hide/show,
                       game mode, power events, DPI/monitor changes, high-contrast mode
src/win/window.rs      Win32 popup (WS_EX_NOREDIRECTIONBITMAP | TOOLWINDOW | NOACTIVATE), layers,
                       click-through, message loop
src/win/monitors.rs    monitor enumeration, DPI, work-area clamp, first-run placement
src/gfx/device.rs      D3D11 (WARP or hardware) → DXGI composition swap chain → DirectComposition
                       → Direct2D device context; dirty-only Present
src/gfx/text.rs        DirectWrite: Segoe UI Variable optical sizes, tabular figures, tracking
src/gfx/paint.rs       the card: bands, rows, bars, sparklines, status dot, hover gear
src/gfx/backdrop.rs    DWM rounded corners, Acrylic/Mica, SetWindowCompositionAttribute fallback
src/model.rs           Snapshot → ViewModel, formatting rules, rings, thresholds, dirty tracking
src/sample/*.rs        sampler thread (event-driven, pausable): GetSystemTimes, GlobalMemoryStatusEx,
                       GetDiskFreeSpaceExW, GetIfTable2, NVML via LoadLibrary, PDH fallback
src/tray.rs, menu.rs   Shell_NotifyIcon v4 + TaskbarCreated; the settings menu
src/config.rs          settings v2, validation, atomic save, v1 import
src/autostart.rs       HKCU Run value `PTMonitor2` (quoted path, self-healing)
src/hotkey.rs          RegisterHotKey parsing/registration
src/bin/make_icon.rs   generates assets/icon.ico (+ previews, icon.svg) with Direct2D + WIC
examples/spike*.rs     the de-risking spikes, kept runnable
tools/                 measure.ps1 and the PowerShell test drivers
```

Design rules: the sampler thread never touches a window (it posts `WM_APP_SNAPSHOT`); the UI
thread borrows the app state per message and performs anything modal or re-entrant (menus,
DestroyWindow, message boxes) only after releasing the borrow; a frame is drawn only when a
displayed value changed; nothing animates.

Test hooks (environment variables): `PTM2_POS=x,y` overrides the start position, `PTM2_HIDE_AFTER=<s>`
hides after N seconds, `PTM2_WARP=1|0` forces the renderer. Scripts can also post
`WM_APP+4` with a menu command id to the main window.

## Icon

`assets/icon.ico` (16–256 px) is generated by `cargo run --release --bin make_icon` from the same
geometry as the card: a dark Fluent tile with a blue-to-violet pulse ending in the status-dot green,
hand-tuned per size. The legacy cogwheel is kept under `assets/legacy/` for reference.

## Troubleshooting

- **No GPU row values / `—`**: `nvml.dll` (NVIDIA driver) could not be loaded and the performance
  counters were unavailable. Set `"gpu_source": "pdh"` to force the counters.
- **Flat card instead of Acrylic**: Windows *Transparency effects* is off, or the build is older
  than 22523. `About` shows which backdrop is in effect.
- **Hotkey does nothing**: another app registered the same combination first; the menu shows it
  greyed. Change `hotkey` in settings.json and *Reload settings*.
- **Widget vanished**: it may be hidden by game mode (a fullscreen app is in front) or by you; click
  the tray icon or press the hotkey. If a monitor was unplugged it is moved back on-screen
  automatically.
- **Log**: `%LOCALAPPDATA%\PTMonitor2\ptmonitor2.log` (lifecycle and errors only).

Known non-goals: virtual-desktop pinning, the Windows "Make text bigger" slider, Remote Desktop
sessions (untested; falls back to WARP anyway).
