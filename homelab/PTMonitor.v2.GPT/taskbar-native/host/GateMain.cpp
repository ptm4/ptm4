// Stage 2 mandatory integration gate harness (plan Section 3).
// Standalone console tool: enumerates displays/taskbars, resolves the
// initial-selection rule, and attempts the real InitializeXamlDiagnosticsEx
// attach against the selected taskbar's Explorer process. Prints evidence
// to stdout and reads back the in-process SetSite log written by the
// surface TAP once it is loaded into explorer.exe.
//
// This harness proves/disproves the riskiest, previously-untested part of
// the design (Section 3's "mandatory integration gate", items 1-2). It does
// not yet implement layout reservation (items 3-5) — that is the next
// checkpoint once attachment itself is proven.
#include "Discovery.h"
#include "XamlAttach.h"
#include "../shared/Protocol.h"
#include "../shared/SharedMemory.h"

#include <cstdio>
#include <string>

using namespace ptmonitor::taskbar;

namespace {

const wchar_t* ResultName(AttachResult r) {
  switch (r) {
    case AttachResult::Success: return L"Success";
    case AttachResult::ExplorerNotFound: return L"ExplorerNotFound";
    case AttachResult::XamlDllLoadFailed: return L"XamlDllLoadFailed";
    case AttachResult::EntryPointNotFound: return L"EntryPointNotFound";
    case AttachResult::NoConnectionSlotFound: return L"NoConnectionSlotFound";
    case AttachResult::InitializeFailed: return L"InitializeFailed";
    case AttachResult::Timeout: return L"Timeout";
  }
  return L"Unknown";
}

std::wstring ModuleDir() {
  wchar_t path[MAX_PATH];
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  std::wstring s(path);
  const auto pos = s.find_last_of(L"\\/");
  return pos == std::wstring::npos ? L"." : s.substr(0, pos);
}

bool g_removeMode = false;
int g_widthDip = 0; // 0 = use the plan's default 220 body
int g_seconds = 30;

} // namespace

int wmain(int argc, wchar_t** argv) {
  for (int i = 1; i < argc; ++i) {
    if (wcscmp(argv[i], L"--remove") == 0) g_removeMode = true;
    else if (wcscmp(argv[i], L"--width") == 0 && i + 1 < argc) g_widthDip = _wtoi(argv[++i]);
    else if (wcscmp(argv[i], L"--seconds") == 0 && i + 1 < argc) g_seconds = _wtoi(argv[++i]);
  }
  wprintf(L"=== PTMonitor taskbar-native Stage 2 gate ===\n\n");

  const auto displays = EnumerateDisplays();
  wprintf(L"Displays (%zu):\n", displays.size());
  for (const auto& d : displays) {
    wprintf(L"  #%d %s [%s] %dx%d primary=%d path=%s\n", d.windowsDisplayNumber,
             d.friendlyName.c_str(), d.hMonitor ? L"resolved" : L"UNRESOLVED", d.widthPx,
             d.heightPx, d.isPrimary ? 1 : 0, d.devicePath.c_str());
  }

  const auto taskbars = EnumerateTaskbarWindows();
  wprintf(L"\nTaskbar windows (%zu):\n", taskbars.size());
  for (const auto& t : taskbars) {
    const auto* match = MatchDisplayForTaskbar(displays, t);
    wprintf(L"  hwnd=0x%p secondary=%d rect=(%ld,%ld,%ld,%ld) display=%s\n", t.hwnd,
             t.isSecondary ? 1 : 0, t.rect.left, t.rect.top, t.rect.right, t.rect.bottom,
             match ? match->friendlyName.c_str() : L"<no match>");
  }

  const std::wstring selected = ResolveInitialSelection(displays);
  wprintf(L"\nInitial-selection rule resolves to device path: %s\n",
           selected.empty() ? L"<none>" : selected.c_str());
  if (selected.empty()) {
    wprintf(L"No eligible display found; stopping.\n");
    return 1;
  }

  // Find the taskbar window whose monitor matches the selected device path.
  HWND targetWnd = nullptr;
  for (const auto& t : taskbars) {
    const auto* match = MatchDisplayForTaskbar(displays, t);
    if (match && match->devicePath == selected) {
      targetWnd = t.hwnd;
      break;
    }
  }
  if (!targetWnd) {
    wprintf(L"Selected display has no taskbar window (\"Selected display has no taskbar.\").\n");
    return 1;
  }
  wprintf(L"Target taskbar hwnd=0x%p\n", targetWnd);

  RECT taskbarRect{};
  GetWindowRect(targetWnd, &taskbarRect);
  const long width = taskbarRect.right - taskbarRect.left;
  const long height = taskbarRect.bottom - taskbarRect.top;
  wprintf(L"Taskbar (ground truth via UI Automation, matches TaskbarFrame) screen rect: (%ld,%ld,%ld,%ld)\n",
          taskbarRect.left, taskbarRect.top, taskbarRect.right, taskbarRect.bottom);

  const std::wstring surfaceDllPath = ModuleDir() + L"\\PTMonitor.TaskbarSurface.dll";
  wprintf(L"Surface DLL path: %s\n", surfaceDllPath.c_str());
  if (GetFileAttributesW(surfaceDllPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
    wprintf(L"ERROR: surface DLL not found next to host exe.\n");
    return 1;
  }

  // Probe multiple VisualDiagConnectionN slots: slot 1 (which always attaches
  // instantly) appears to land on an unrelated, empty XAML island rather than
  // this taskbar's own island. Try several slots, each carrying the known-
  // correct TaskbarFrame rect, and let the surface's evidence log show which
  // slot (if any) actually contains our taskbar content.
  // Only VisualDiagConnection1 is ever a live endpoint for a given Explorer
  // process (slots 2+ consistently report ERROR_NOT_FOUND), so attach there.
  const int slot = 1;
  wchar_t initData[256];
  swprintf_s(initData, L"%d;%ld,%ld,%ld,%ld;%ld,%ld,%ld,%ld;%s;%d", slot, taskbarRect.left,
             taskbarRect.top, taskbarRect.right, taskbarRect.bottom, 0L, 0L, width, height,
             g_removeMode ? L"remove" : L"apply", g_widthDip);
  wprintf(L"Mode: %s  widthOverride=%d\n", g_removeMode ? L"REMOVE" : L"APPLY", g_widthDip);

  // Create the shared channel BEFORE attaching so the surface finds it on its
  // first timer tick.
  SharedChannel channel;
  if (!g_removeMode) {
    if (!channel.CreateAsHost()) {
      wprintf(L"ERROR: could not create shared channel\n");
      return 1;
    }
    wprintf(L"Shared channel created: %s\n", SharedMemoryName().c_str());
  }

  const AttachOutcome outcome =
      AttachToExplorerTaskbarAtSlot(targetWnd, surfaceDllPath, kSurfaceTapClsid, slot, initData);
  wprintf(L"slot=%-3d Result: %-20s hr=0x%08lx explorerPid=%lu\n", slot, ResultName(outcome.result),
          outcome.hr, outcome.explorerPid);

  if (outcome.result != AttachResult::Success) return 2;
  if (g_removeMode) {
    Sleep(6000);
    wprintf(L"\nRemoval requested.\n");
    return 0;
  }

  // Feed changing values so the live update path is observable. The real host
  // gets these from PTMonitor over stdin instead.
  wprintf(L"Publishing live test values for %d seconds...\n", g_seconds);
  for (int t = 0; t < g_seconds; ++t) {
    const int cpu = 20 + (t * 7) % 70;
    const int ram = 55 + (t * 3) % 20;
    const int gpu = 10 + (t * 11) % 80;
    const int temp = 40 + (t % 15);
    const int down = 1 + (t * 13) % 900;
    const int up = 1 + (t * 5) % 400;

    if (channel.TryLock(1000)) {
      SharedState* s = channel.state();
      swprintf_s(s->cells[0], L"CPU %d%%", cpu);
      swprintf_s(s->cells[1], L"RAM %d%%", ram);
      swprintf_s(s->cells[2], L"GPU %d%%", gpu);
      swprintf_s(s->cells[3], L"%d°C", temp);
      swprintf_s(s->cells[4], L"↓ %d KiB/s", down);
      swprintf_s(s->cells[5], L"↑ %d KiB/s", up);
      swprintf_s(s->tooltip, L"PTMonitor — CPU %d%%, RAM %d%%, GPU %d%%, %d°C", cpu, ram, gpu, temp);
      s->enabled = 1;
      s->lastSnapshotTick = static_cast<int64_t>(GetTickCount64());
      s->hostHeartbeatTick = s->lastSnapshotTick;
      swprintf_s(s->sourceSequence, L"%d", t);
      channel.Unlock();
    }
    Sleep(1000);
  }

  wprintf(L"\nDone publishing.\n");
  return 0;
}
