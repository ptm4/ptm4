#include "XamlAttach.h"
#include "../shared/Protocol.h"

#include <xamlOM.h>
#include <chrono>
#include <string>

namespace ptmonitor::taskbar {

namespace {

// InitializeXamlDiagnosticsEx is exported by Windows.UI.Xaml.dll but ships
// with no import library in the Windows SDK, so it must be resolved with
// GetProcAddress at runtime (plan Section 3, "Loading the surface").
using InitializeXamlDiagnosticsExFn = HRESULT(WINAPI*)(LPCWSTR endPointName, DWORD pid,
                                                         LPCWSTR wszDllXamlDiagnostics,
                                                         LPCWSTR wszTAPDllName, CLSID tapClsid,
                                                         LPCWSTR wszInitializationData);

DWORD FindExplorerPidForWindow(HWND wnd) {
  DWORD pid = 0;
  GetWindowThreadProcessId(wnd, &pid);
  return pid;
}

} // namespace

AttachOutcome AttachToExplorerTaskbar(HWND taskbarWnd, const std::wstring& surfaceDllPath,
                                       const GUID& tapClsid, const std::wstring& initializationData) {
  AttachOutcome outcome{};

  const DWORD explorerPid = FindExplorerPidForWindow(taskbarWnd);
  if (explorerPid == 0) {
    outcome.result = AttachResult::ExplorerNotFound;
    return outcome;
  }
  outcome.explorerPid = explorerPid;

  HMODULE xamlDll = LoadLibraryExW(L"Windows.UI.Xaml.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
  if (!xamlDll) {
    outcome.result = AttachResult::XamlDllLoadFailed;
    outcome.hr = HRESULT_FROM_WIN32(GetLastError());
    return outcome;
  }

  auto initFn = reinterpret_cast<InitializeXamlDiagnosticsExFn>(
      GetProcAddress(xamlDll, "InitializeXamlDiagnosticsEx"));
  if (!initFn) {
    outcome.result = AttachResult::EntryPointNotFound;
    return outcome;
  }

  wchar_t xamlDllPath[MAX_PATH];
  GetModuleFileNameW(xamlDll, xamlDllPath, static_cast<DWORD>(std::size(xamlDllPath)));

  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(kAttachTimeoutSeconds);

  for (int i = kVisualDiagConnectionMin; i <= kVisualDiagConnectionMax; ++i) {
    if (std::chrono::steady_clock::now() >= deadline) {
      outcome.result = AttachResult::Timeout;
      return outcome;
    }

    const std::wstring endpoint = L"VisualDiagConnection" + std::to_wstring(i);
    const HRESULT hr = initFn(endpoint.c_str(), explorerPid, xamlDllPath,
                               surfaceDllPath.c_str(), tapClsid, initializationData.c_str());

    if (SUCCEEDED(hr)) {
      outcome.result = AttachResult::Success;
      outcome.hr = hr;
      outcome.connectionIndexUsed = i;
      return outcome;
    }

    if (hr != HRESULT_FROM_WIN32(ERROR_NOT_FOUND) && hr != HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND)) {
      // Any error other than "this connection slot doesn't exist" stops the search
      // (plan Section 3: "Continue on ERROR_NOT_FOUND; stop on success or any other error").
      outcome.result = AttachResult::InitializeFailed;
      outcome.hr = hr;
      return outcome;
    }
  }

  outcome.result = AttachResult::NoConnectionSlotFound;
  return outcome;
}

AttachOutcome AttachToExplorerTaskbarAtSlot(HWND taskbarWnd, const std::wstring& surfaceDllPath,
                                             const GUID& tapClsid, int slot,
                                             const std::wstring& initializationData) {
  AttachOutcome outcome{};

  const DWORD explorerPid = FindExplorerPidForWindow(taskbarWnd);
  if (explorerPid == 0) {
    outcome.result = AttachResult::ExplorerNotFound;
    return outcome;
  }
  outcome.explorerPid = explorerPid;

  HMODULE xamlDll = LoadLibraryExW(L"Windows.UI.Xaml.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
  if (!xamlDll) {
    outcome.result = AttachResult::XamlDllLoadFailed;
    outcome.hr = HRESULT_FROM_WIN32(GetLastError());
    return outcome;
  }
  auto initFn = reinterpret_cast<InitializeXamlDiagnosticsExFn>(
      GetProcAddress(xamlDll, "InitializeXamlDiagnosticsEx"));
  if (!initFn) {
    outcome.result = AttachResult::EntryPointNotFound;
    return outcome;
  }
  wchar_t xamlDllPath[MAX_PATH];
  GetModuleFileNameW(xamlDll, xamlDllPath, static_cast<DWORD>(std::size(xamlDllPath)));

  const std::wstring endpoint = L"VisualDiagConnection" + std::to_wstring(slot);
  const HRESULT hr = initFn(endpoint.c_str(), explorerPid, xamlDllPath, surfaceDllPath.c_str(),
                             tapClsid, initializationData.c_str());
  outcome.hr = hr;
  outcome.connectionIndexUsed = slot;
  outcome.result = SUCCEEDED(hr) ? AttachResult::Success : AttachResult::InitializeFailed;
  return outcome;
}

} // namespace ptmonitor::taskbar
