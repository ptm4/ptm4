# Third-party notices — PTMonitor taskbar integration

The taskbar host (`PTMonitor.TaskbarHost.exe`), the surface DLL
(`PTMonitor.TaskbarSurface.dll`) and their shared headers under
`taskbar-native/` were written specifically for PTMonitor and are released
under the MIT licence in [`LICENSE`](LICENSE). This does not change the
licensing of any other file in the project.

## Reused source

**None.** No third-party source code is copied, vendored or linked into these
binaries. Should that ever change, the file, upstream revision and licence
must be recorded in this section.

## Platform components used

These ship with Windows and are used through their public headers and the
system's own copies; nothing is redistributed with PTMonitor.

| Component | How it is used |
| --- | --- |
| Windows SDK (`xamlOM.h`, `windows.h`, `sddl.h`) | XAML diagnostics interfaces, Win32 display/window enumeration, shared-object security descriptors |
| C++/WinRT projection headers (Windows SDK) | Typed access to live XAML objects, `Windows.Data.Json` for host-side JSON |
| `Windows.UI.Xaml.dll` (System32) | `InitializeXamlDiagnosticsEx`, resolved at runtime via `GetProcAddress` |

## Research references

These were consulted while designing the integration. No code from them is
present in PTMonitor.

| Reference | URL | Notes |
| --- | --- | --- |
| Microsoft — `InitializeXamlDiagnosticsEx` | https://learn.microsoft.com/en-us/windows/win32/api/xamlom/nf-xamlom-initializexamldiagnosticsex | Documents the diagnostics entry point PTMonitor uses to load its surface into Explorer |
| Microsoft — `AutomationPeer.GetBoundingRectangle` | https://learn.microsoft.com/en-us/uwp/api/windows.ui.xaml.automation.peers.automationpeer.getboundingrectangle | Background for associating a XAML tree with a physical display |
| Taskbar Widgets | https://github.com/pfcdev/TaskbarWidgets | Consulted as prior art for taskbar XAML integration. Its public repository does not contain the diagnostics attachment bootstrap, so nothing was taken from it; PTMonitor's attachment, layout reservation and cleanup were derived independently from the SDK headers and runtime inspection. |

## Notes on the approach

The integration uses only documented SDK headers and a runtime-resolved
exported function. It performs no runtime code patching, no private-symbol
downloads, no function-signature scanning and no remote-memory function
pointers.
