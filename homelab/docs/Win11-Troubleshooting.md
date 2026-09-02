# Windows 11 Troubleshooting

Field-tested fixes. One entry per issue, newest first.

---

## SecurityHealthSystray.exe Bad Image — SecurityHealthSSO.dll, 0xc000012f (2026-08-29)

**Machine:** brother's PC, Win11 build 26200.9168 (current)

### Symptom

- Popup at every login: `SecurityHealthSystray.exe - Bad Image: \\?\C:\Windows\System32\SecurityHealth\10.0.27840.1000-0\SecurityHealthSSO.dll is either not designed to run on Windows or it contains an error. Error status 0xc000012f.`
- Windows Security app refuses to open.
- Defender real-time protection unaffected throughout (separate service, `WinDefend`/MsMpEng — verify with `Get-MpComputerStatus`).

### Root cause

`0xc000012f` = `STATUS_INVALID_IMAGE_NOT_MZ`: the DLL on disk is hard-corrupt (not even a valid PE header). The file lives in the **Windows Security platform** versioned folder `C:\Windows\System32\SecurityHealth\<version>-0\`, which is serviced by its own update — **KB5007651 "Update for Windows Security platform"** (Definition Updates class) — outside the component store, outside OS cumulative updates, and outside the SecHealthUI appx. The active version is selected by the registry pointer:

```
HKLM\SOFTWARE\Microsoft\Windows Security Health\Platform → CoreLocation
```

The affected machine was stuck on platform `10.0.27840.1000` (May 2025) — the corrupt folder blocked every subsequent platform update, while OS cumulative updates kept installing fine.

### What does NOT work (verified, don't waste time)

| Attempt | Why it fails |
|---|---|
| Reset/reinstall Windows Security app (`Reset-AppxPackage Microsoft.SecHealthUI`) | The app is just the UI — and the appx package itself ships *inside* the platform folder |
| `sfc /scannow`, `DISM /RestoreHealth` | Versioned folder is not in the component store; no SecHealth CBS package exists |
| In-place repair install | Documented cases show the SecurityHealth folder untouched (unchanged timestamps) afterward |
| Running the KB5007651 installer with the corrupt folder still present | Exits 0, drops a `SecurityHealthSetup.exe` self-copy in the SecurityHealth root, but never creates the new version folder |

### Fix that worked

1. Download the newest x64 **KB5007651** (`securityhealthsetup_<hash>.exe`) from the [Microsoft Update Catalog](https://catalog.update.microsoft.com/Search.aspx?q=KB5007651); `Unblock-File` it.
2. Get a **TrustedInstaller** shell (admin is not enough — the folder is TrustedInstaller-owned): [ExecTI](https://winaero.com/execti/) → launch `cmd.exe`. Then:
   ```
   taskkill /f /im SecurityHealthSystray.exe     :: "not found" is fine — it crashed at login
   rd /s /q "C:\Windows\System32\SecurityHealth\10.0.27840.1000-0"
   del /f "C:\Windows\System32\SecurityHealth\SecurityHealthSetup.exe"
   sc start SecurityHealthService
   ```
3. From a **normal elevated PowerShell** (not one spawned from the TI cmd — see gotchas), run the downloaded installer:
   ```powershell
   $p = Start-Process "C:\Users\<user>\Downloads\securityhealthsetup_<hash>.exe" -Wait -PassThru
   $p.ExitCode   # expect 0
   ```
4. Verify, then reboot:
   ```powershell
   reg query "HKLM\SOFTWARE\Microsoft\Windows Security Health\Platform" /v CoreLocation
   # → \\?\C:\Windows\System32\SecurityHealth\10.0.29628.1000-0  (fresh current-version folder)
   ```
5. After reboot: no popup, Windows Security opens, `Get-MpComputerStatus` healthy.

### Gotchas hit along the way

- **Installer exit 0 ≠ success.** With the corrupt folder in place it exits clean without installing anything. Always verify `CoreLocation` + folder listing.
- **PowerShell launched from the TrustedInstaller cmd runs as SYSTEM** — `$env:USERPROFILE` resolves to `C:\WINDOWS\system32\config\systemprofile`, so Downloads-relative paths break. Use explicit paths or a fresh elevated shell.
- **`CoreLocation` falls back to `\\?\C:\Windows\System32`** after deleting the platform folder and restarting the service — expected in-box-stub fallback, the installer repoints it.
- The standalone installer leaves a `SecurityHealthSetup.exe` self-copy in the SecurityHealth root — normal breadcrumb, leave it.
- Delete only the **versioned subfolder**, never the whole `SecurityHealth` parent.

### Aftercare

- `chkdsk C: /scan` + `Get-PhysicalDisk | Select FriendlyName, HealthStatus` — corruption has a cause; a failing drive would be the real problem.
- One-time `sfc /scannow` to confirm nothing else was hit.
- C: was at ~15 GB free — cleanup pass due before the next feature update.

### Verdict notes

Not reinstall-worthy: single corrupt, separately-serviced component with a ~15-min targeted fix, on an otherwise current and healthy install. Full runbook artifact (with sources — two OP-confirmed Microsoft Q&A threads, mechanism verified on a healthy machine): <https://claude.ai/code/artifact/b76a6584-81c0-41c4-b3a0-ca738524262e>
