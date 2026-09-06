# PTMonitor v2 validation

Validation performed September 6, 2026 on Windows, Ryzen 7 5800X and NVIDIA RTX
4070 Ti, **standard user access**. This is a local implementation/build check, not
a claim that every vendor or monitor topology has been physically certified.

## Completed

- 33 Rust unit tests: GPU engine aggregation, no cross-GPU sensor mixing, missing
  data, unit conversion, sustained alert thresholds/hysteresis/resume handling,
  bounded histories, process ranking, adapter selection/hotplug/replacement/reset,
  physical-disk mapping, settings bounds/null patches/startup quoting, placement,
  corner anchoring and high-DPI tray raster/tooltip/signatures.
- 10 JavaScript tests covering formatting, history time geometry/gaps, tray-resume restoration, stale data,
  disk priority, sensor text handling and event-based native integration.
- 7 mocked C# hardware-tree checks: identity, units, missing values, error isolation,
  provenance and standard-permission filtering.
- Five actual native samples: CPU/RAM, two fixed volumes, Ethernet, true uptime,
  PDH GPU fallback and 62 LHM sensors. Typical observed collection work was roughly
  5–15 ms per sample (not a long-term CPU/RAM benchmark).
- Real sensor-host one-second frames; no sensor TCP listener; clean stdin-EOF exit;
  no-ping parent watchdog terminates the helper within the 22-second test bound.
- Browser layout/behavior checks at 100/125/150% rendering scale, compact and
  expanded layouts, long/malicious-looking sensor names, all thresholds, adapter
  reset, unavailable sensors and stopped updates. Screenshots in ignored
  `test/artifacts/`.
- Native Windows acrylic dashboard and expanded charts visibly update; native
  settings work. Enabled click-through, launched v2 again, confirmed it was
  disabled and only the original GUI process remained.
- Killed the specifically owned QA sensor helper. The UI cleared hardware readings,
  kept core/PDH monitoring live, reported a retry, and recovered 62 sensors in a new
  child. Killed the QA parent afterward; no sensor helper remained.
- No TCP listener owned by the native GUI during the check. Runtime process tree
  contained the GUI, WebView2 and sensor helper, not recurring PowerShell collectors.
- Release build and NSIS packaging succeeded. The native executable is about 3.7 MB,
  self-contained sensor helper 37.4 MB, and installer 32.1 MB (decimal). The packaged
  sidecar repeated the live IPC/watchdog checks successfully; all six upstream
  license/notice files and the sensor dependency notice are present beside it.
- `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings` pass.
- After removing meter animations, a 15-second compact-mode sample measured
  **0.388% whole-machine CPU** across the native GUI, WebView2 descendants and sensor
  helper, with **161.9 MiB private working set** in aggregate. This is a short local
  observation, not a guaranteed performance budget; shared-page working-set sums
  are much larger and should not be confused with private resident memory.

## Manual release matrix still required

- Intel CPU/iGPU and AMD GPU systems; multi-GPU summaries under different loads.
- User-confirmed UAC restart, cancellation, driver-policy restrictions, motherboard
  and SMART readings. No security settings were changed during validation.
- Physically move between mixed 100/125/150% DPI monitors; remove/reconnect a monitor;
  taskbars on different edges; recover a saved position after topology changes.
- Tray overflow visibility and Explorer restart under the user's Windows settings.
- Per-user installer/uninstaller execution and simultaneous v1/v2 installed use;
  startup from a path containing spaces. Registry quoting/isolation is unit-tested,
  but startup was not enabled on the user's workstation during QA.
- Opt-in Windows toast delivery/suppression in the installed app. Notifications
  remain off; synthetic alert logic was tested without sending desktop toasts.
- Sustained game/fullscreen use on monitor 1 with v2 on monitor 2, sleep/resume,
  and long-running memory/handle/CPU measurements on the target workstation.

## Known boundaries

Missing CPU/SMART/motherboard sensors in standard mode are expected. Some Windows
driver policies also prevent them when elevated. GPU zero-RPM mode is a genuine
reading and not a failure. PDH-only GPU load is explicitly across adapters; it is
not attached to a different named sensor GPU. Remote/removable drives are excluded.
No persistent metric history, remote endpoint or monitoring service is provided.
