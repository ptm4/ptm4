# PTMonitor taskbar integration

Live readings rendered inside the Windows 11 taskbar, in space the taskbar
genuinely reserves — not an overlay drawn on top of it.

```
CPU 47%  —      RAM 59%
GPU 38%         44°C
↓ 4 KiB/s       ↑ 6 KiB/s
```

## Components

| Component | Responsibility |
| --- | --- |
| PTMonitor (Rust) | Collects readings, owns settings, formats the six display cells, supervises the host |
| `PTMonitor.TaskbarHost.exe` | Discovers monitors and taskbars, transports state, establishes the attachment, recovers |
| `PTMonitor.TaskbarSurface.dll` | Renders the panel inside Explorer's taskbar and reserves its space |

The surface performs no hardware collection, creates no WebView, and loads no
.NET into Explorer.

## How the attachment works

1. The host resolves `InitializeXamlDiagnosticsEx` from `Windows.UI.Xaml.dll`
   in System32 at runtime — the Windows SDK ships no import library for it.
2. It calls that function with the Explorer PID owning the selected taskbar and
   the absolute path to the surface DLL, using one fixed PTMonitor CLSID. It
   searches `VisualDiagConnection1`…`10000`, continuing past `ERROR_NOT_FOUND`.
   In practice only connection 1 exists per Explorer process.
3. Explorer loads the surface in-process and calls `IObjectWithSite::SetSite`
   with a live `IXamlDiagnostics`.
4. The surface calls `AdviseVisualTreeChange`, and the runtime replays the
   entire visual tree through `IVisualTreeServiceCallback2::OnVisualTreeChange`
   — roughly 420 elements. This, not `HitTest`, is how the tree is discovered;
   `HitTest` is scoped to an always-empty diagnostics adorner layer and returns
   `E_INVALIDARG` for every rectangle.
5. Element handles are turned into real XAML objects with
   `GetIInspectableFromHandle`, after which the ordinary C++/WinRT projections
   provide layout, a `DispatcherTimer` and clean teardown.

### Thread affinity

XAML objects are thread-affine. Touching them from a worker thread fails with
`RPC_E_WRONG_THREAD` (`0x8001010E`). Every tree read and mutation therefore
runs inside `OnVisualTreeChange`, which arrives on the owning element's
dispatcher thread, or on the `DispatcherTimer` that is created there.

`SetSite` must also return promptly: `InitializeXamlDiagnosticsEx` blocks until
it does, so a slow `SetSite` starves the host's own attach timeout.

## Layout adapters

The taskbar's tree on Windows 11 25H2 (build 26200) is:

```
Grid                                  ← the containing grid
├── Taskbar.TaskbarFrame              ← Start + app buttons, paints the taskbar material
│   └── … → TaskbarFrameRepeater      ← the buttons themselves
└── SystemTray.SystemTrayFrame        ← clock and notification area
    └── SystemTrayFrameGrid
        ├── SystemTray.OmniButton (ControlCenterButton)
        └── SystemTray.OmniButton (NotificationCenterButton)
```

**Adapter A — the containing grid already has explicit columns.** Insert one
228-DIP column before the tray column, shift existing children, widen spans
that cross the insertion point, and preserve the task area's star sizing.

**Adapter B — no explicit columns** (what this build actually uses; its
`ColumnDefinitions` collection is empty and both frames sit in column 0, with
the tray right-aligned over a stretched frame). Introduce three columns —
`*`, the reservation, `Auto` — and place the taskbar frame, PTMonitor and the
tray in columns 0, 1 and 2.

Two constraints that runtime testing made necessary:

- **The taskbar frame keeps `Grid.ColumnSpan = 3`.** It paints the full-width
  taskbar material; confining it to column 0 leaves the reserved column with no
  background and the wallpaper showing through.
- **The button repeater is constrained with a right `Margin`, not `MaxWidth`.**
  The repeater centres itself inside the frame, so a `MaxWidth` shrinks it
  symmetrically and visibly shifts the buttons inward. A margin reduces the
  available area while the repeater still stretches into what remains, leaving
  the buttons at their original edge and letting native overflow engage.

Reservation changes the available layout width, so buttons overflow through
Windows' own mechanism rather than being clipped.

## Interfaces

### PTMonitor → host (stdin, UTF-8, newline-delimited JSON, ≤ 16 KiB per frame)

Every message carries `protocolVersion: 1` and a `type`.

| Type | Content |
| --- | --- |
| `configure` | `enabled`, `monitorDevicePath`, `widthDip` |
| `snapshot` | `sourceSequence` (decimal **string**, to avoid JSON number precision loss), `cells` (six strings), `tooltip` |
| `heartbeat` | — |
| `shutdown` | — |

### Host → PTMonitor (stdout, same framing)

| Type | Content |
| --- | --- |
| `ready` | Protocol version |
| `action` | `showDashboard`, `openSettings` or `disableTaskbar` |

`action` is an allowlist. No command, path, script or elevation request can
cross this interface; unknown codes are dropped.

### Host ↔ surface (shared memory)

Session-local named shared memory plus a named mutex, both named from the user
SID and Windows session id and restricted to that user and SYSTEM. Both
binaries compile the same versioned POD from `shared/Protocol.h`; a magic,
version and struct-size mismatch is rejected.

Explorer's UI thread only ever takes the mutex with a **zero timeout** — if the
host is mid-write, the tick keeps the current display and tries again. No
blocking I/O and no JSON parsing ever happens inside Explorer.

## Known limitation: panel clicks

The panel registers `PointerPressed` and `RightTapped` handlers, and the whole
chain behind them is proven — a press writes an action code into shared memory,
the host relays `{"type":"action","action":"showDashboard"}` on stdout, and
PTMonitor acts on it. That path was observed working end to end.

It is **not reliable**, however. Windows 11's taskbar hosts its XAML in an
input site that decides which regions receive pointer input, and clicks on the
injected element are usually not routed to it — the handlers simply never fire.
No amount of hit-test configuration on our element changes this, because the
decision is made before input reaches the XAML tree.

The tray menu therefore remains the supported way to reach every action the
panel offers: **Show live taskbar readings**, the width control, **Settings**
and **Show / Hide PTMonitor v2**. Nothing is only reachable by clicking the
panel.

## Recovery

| Condition | Behaviour |
| --- | --- |
| No new snapshot for 3s | Panel stays, readings become dashes, tooltip explains |
| No host heartbeat for 10s | Surface removes itself and restores the reservation |
| Explorer restarts | Surface heartbeat stops; host re-attaches (backoff resets on a new Explorer PID) |
| Selected display disconnected | Selection retained, panel waits — it never migrates to another monitor |
| Width or display changed | Panel is torn down, then re-attached with the new configuration |
| PTMonitor exits (even killed) | stdin reaches EOF, host clears `enabled` and exits; the surface restores the layout |

Attach retries follow 1, 2, 4, 8, 16, 30 seconds, capped at 30, and reset after
60 seconds of stable attachment.

## Building

Requires an already-installed Visual Studio C++ x64 toolchain and a Windows SDK
that includes the C++/WinRT headers. The build script locates both through
`vswhere` and **never downloads or installs a compiler or SDK**.

```powershell
npm run build:taskbar   # builds host, surface and native tests, then runs the tests
npm run test:taskbar    # builds and runs the native tests only
```

Compiler settings are C++20, `/W4 /WX`, `/EHsc`, `/O2`, `/MT`, Unicode. The
build stops on warnings, failed tests or missing outputs.

### Offline use

Nothing here reaches the network — at build time or at run time. There are no
runtime downloads, no symbol-server dependency, no remotely fetched
configuration and no update service. The binaries open no listening sockets and
make no outbound connections. Once built, the feature works with networking
entirely disabled; only the network *readings* go blank, exactly as any other
unavailable sensor does.

## Diagnostics

`probe.exe` (built by `gate_build.bat`) opens the shared channel read-only and
prints what the host is publishing, including host and surface heartbeat ages —
useful for telling "the data stopped" apart from "the panel stopped".
