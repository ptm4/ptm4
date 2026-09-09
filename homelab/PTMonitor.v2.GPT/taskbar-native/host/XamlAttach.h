// Explorer XAML diagnostics attachment (plan Section 3, "Loading the surface").
#pragma once

#include <windows.h>
#include <string>

namespace ptmonitor::taskbar {

enum class AttachResult {
  Success,
  ExplorerNotFound,
  XamlDllLoadFailed,
  EntryPointNotFound,
  NoConnectionSlotFound,   // exhausted VisualDiagConnection1..10000 without ERROR_NOT_FOUND stopping early on success
  InitializeFailed,
  Timeout,
};

struct AttachOutcome {
  AttachResult result;
  HRESULT hr = S_OK;
  int connectionIndexUsed = 0; // which VisualDiagConnectionN succeeded, 0 if none
  DWORD explorerPid = 0;
};

// Finds the Explorer process hosting the taskbar window, then attempts
// InitializeXamlDiagnosticsEx against it, searching VisualDiagConnection1..10000
// in order and continuing past ERROR_NOT_FOUND. Must be called off the
// PTMonitor UI/sampling threads. Enforces the 5-second attempt budget itself.
AttachOutcome AttachToExplorerTaskbar(HWND taskbarWnd, const std::wstring& surfaceDllPath,
                                       const GUID& tapClsid, const std::wstring& initializationData = L"");

// Gate-only: attach at one specific VisualDiagConnectionN slot instead of
// searching, so multiple islands can be probed in one process run without
// restarting Explorer between attempts.
AttachOutcome AttachToExplorerTaskbarAtSlot(HWND taskbarWnd, const std::wstring& surfaceDllPath,
                                             const GUID& tapClsid, int slot,
                                             const std::wstring& initializationData = L"");

} // namespace ptmonitor::taskbar
