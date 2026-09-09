// Monitor + taskbar discovery (plan Section 3, "Discovery and monitor identity").
// Read-only: never touches Explorer's process or Windows' taskbar settings.
#pragma once

#include <windows.h>
#include <string>
#include <vector>

namespace ptmonitor::taskbar {

struct DisplayInfo {
  std::wstring devicePath;   // stable identity to persist (never HMONITOR/HWND/index/coords)
  std::wstring friendlyName;
  int windowsDisplayNumber = 0;
  int widthPx = 0;
  int heightPx = 0;
  bool isPrimary = false;
  HMONITOR hMonitor = nullptr; // resolved fresh per call, not persisted
};

struct TaskbarWindowInfo {
  HWND hwnd = nullptr;
  bool isSecondary = false; // Shell_TrayWnd (false) vs Shell_SecondaryTrayWnd (true)
  HMONITOR hMonitor = nullptr;
  RECT rect{};
};

// Enumerates active display paths via QueryDisplayConfig / DisplayConfigGetDeviceInfo.
std::vector<DisplayInfo> EnumerateDisplays();

// Enumerates Shell_TrayWnd / Shell_SecondaryTrayWnd top-level windows via EnumWindows,
// resolving each one's monitor association via MonitorFromWindow.
std::vector<TaskbarWindowInfo> EnumerateTaskbarWindows();

// Resolves the DisplayInfo whose hMonitor matches the given taskbar window, if any.
const DisplayInfo* MatchDisplayForTaskbar(const std::vector<DisplayInfo>& displays,
                                           const TaskbarWindowInfo& taskbar);

// Section 3 "Initial selection" rule, applied only when no saved device path exists yet.
// Returns the device path to persist, or empty string if no eligible display exists.
std::wstring ResolveInitialSelection(const std::vector<DisplayInfo>& displays);

} // namespace ptmonitor::taskbar
