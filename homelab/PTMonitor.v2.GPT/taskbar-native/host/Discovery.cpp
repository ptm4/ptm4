#include "Discovery.h"

#include <algorithm>

namespace ptmonitor::taskbar {

namespace {

std::wstring DeviceLuidPathKey(const DISPLAYCONFIG_PATH_INFO& path) {
  // The (adapterId, id) pair for the target is Windows' stable per-boot
  // identity; DisplayConfigGetDeviceInfo(DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME)
  // exposes the actual monitor device path string we persist instead.
  wchar_t buf[64];
  swprintf_s(buf, L"%08lx%08lx-%u", path.targetInfo.adapterId.HighPart,
             path.targetInfo.adapterId.LowPart, path.targetInfo.id);
  return buf;
}

} // namespace

std::vector<DisplayInfo> EnumerateDisplays() {
  std::vector<DisplayInfo> result;

  UINT32 pathCount = 0;
  UINT32 modeCount = 0;
  if (GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, &pathCount, &modeCount) !=
      ERROR_SUCCESS) {
    return result;
  }

  std::vector<DISPLAYCONFIG_PATH_INFO> paths(pathCount);
  std::vector<DISPLAYCONFIG_MODE_INFO> modes(modeCount);
  if (QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, &pathCount, paths.data(), &modeCount,
                          modes.data(), nullptr) != ERROR_SUCCESS) {
    return result;
  }
  paths.resize(pathCount);
  modes.resize(modeCount);

  int nextDisplayNumber = 1;
  for (const auto& path : paths) {
    if (path.targetInfo.targetAvailable == FALSE) continue;

    DISPLAYCONFIG_TARGET_DEVICE_NAME targetName{};
    targetName.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME;
    targetName.header.size = sizeof(targetName);
    targetName.header.adapterId = path.targetInfo.adapterId;
    targetName.header.id = path.targetInfo.id;
    if (DisplayConfigGetDeviceInfo(&targetName.header) != ERROR_SUCCESS) continue;

    DISPLAYCONFIG_SOURCE_DEVICE_NAME sourceName{};
    sourceName.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME;
    sourceName.header.size = sizeof(sourceName);
    sourceName.header.adapterId = path.sourceInfo.adapterId;
    sourceName.header.id = path.sourceInfo.id;
    if (DisplayConfigGetDeviceInfo(&sourceName.header) != ERROR_SUCCESS) continue;

    DisplayInfo info;
    // Prefer the monitor's own device path (\\?\DISPLAY#...); fall back to the
    // adapter/target LUID key if the OS didn't report one for this target.
    if (targetName.monitorDevicePath[0] != L'\0') {
      info.devicePath = targetName.monitorDevicePath;
    } else {
      info.devicePath = DeviceLuidPathKey(path);
    }
    info.friendlyName = targetName.monitorFriendlyDeviceName[0] != L'\0'
                             ? targetName.monitorFriendlyDeviceName
                             : L"Unknown display";
    info.isPrimary = (path.targetInfo.outputTechnology != DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL) ||
                      false; // corrected below via HMONITOR primary flag

    // Resolve HMONITOR + pixel size + true primary flag from the GDI device name.
    DISPLAY_DEVICEW dd{};
    dd.cb = sizeof(dd);
    // sourceName.viewGdiDeviceName gives us the \\.\DISPLAYn adapter name.
    HMONITOR matched = nullptr;
    DEVMODEW devMode{};
    devMode.dmSize = sizeof(devMode);
    if (EnumDisplaySettingsW(sourceName.viewGdiDeviceName, ENUM_CURRENT_SETTINGS, &devMode)) {
      info.widthPx = devMode.dmPelsWidth;
      info.heightPx = devMode.dmPelsHeight;
      POINT pt{devMode.dmPosition.x + 1, devMode.dmPosition.y + 1};
      matched = MonitorFromPoint(pt, MONITOR_DEFAULTTONULL);
    }
    info.hMonitor = matched;
    if (matched) {
      MONITORINFO mi{};
      mi.cbSize = sizeof(mi);
      if (GetMonitorInfoW(matched, &mi)) {
        info.isPrimary = (mi.dwFlags & MONITORINFOF_PRIMARY) != 0;
      }
    }
    info.windowsDisplayNumber = nextDisplayNumber++;

    result.push_back(std::move(info));
  }

  return result;
}

namespace {

BOOL CALLBACK EnumTaskbarWindowsProc(HWND hwnd, LPARAM lParam) {
  auto* out = reinterpret_cast<std::vector<TaskbarWindowInfo>*>(lParam);
  wchar_t className[256];
  if (!GetClassNameW(hwnd, className, static_cast<int>(std::size(className)))) return TRUE;

  bool isSecondary;
  if (wcscmp(className, L"Shell_TrayWnd") == 0) {
    isSecondary = false;
  } else if (wcscmp(className, L"Shell_SecondaryTrayWnd") == 0) {
    isSecondary = true;
  } else {
    return TRUE;
  }

  TaskbarWindowInfo info;
  info.hwnd = hwnd;
  info.isSecondary = isSecondary;
  info.hMonitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL);
  GetWindowRect(hwnd, &info.rect);
  out->push_back(info);
  return TRUE;
}

} // namespace

std::vector<TaskbarWindowInfo> EnumerateTaskbarWindows() {
  std::vector<TaskbarWindowInfo> result;
  EnumWindows(EnumTaskbarWindowsProc, reinterpret_cast<LPARAM>(&result));
  return result;
}

const DisplayInfo* MatchDisplayForTaskbar(const std::vector<DisplayInfo>& displays,
                                           const TaskbarWindowInfo& taskbar) {
  if (!taskbar.hMonitor) return nullptr;
  for (const auto& d : displays) {
    if (d.hMonitor == taskbar.hMonitor) return &d;
  }
  return nullptr;
}

std::wstring ResolveInitialSelection(const std::vector<DisplayInfo>& displays) {
  std::vector<const DisplayInfo*> nonPrimary;
  for (const auto& d : displays) {
    if (!d.isPrimary) nonPrimary.push_back(&d);
  }

  if (displays.size() == 1) {
    return displays[0].devicePath;
  }
  if (nonPrimary.size() == 1) {
    return nonPrimary[0]->devicePath;
  }
  if (nonPrimary.size() > 1) {
    const DisplayInfo* lowest = nonPrimary[0];
    for (auto* d : nonPrimary) {
      if (d->windowsDisplayNumber < lowest->windowsDisplayNumber) lowest = d;
    }
    return lowest->devicePath;
  }
  return {};
}

} // namespace ptmonitor::taskbar
