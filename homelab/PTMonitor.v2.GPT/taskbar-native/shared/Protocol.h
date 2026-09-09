// PTMonitor taskbar-native shared protocol definitions.
// Included by both PTMonitor.TaskbarHost.exe and PTMonitor.TaskbarSurface.dll
// so the two binaries always agree on wire/struct layout.
#pragma once

#include <cstdint>
#include <windows.h>

namespace ptmonitor::taskbar {

// Fixed CLSID identifying the PTMonitor XAML diagnostics TAP.
// {6C1F5B2E-6A6E-4E1C-9E36-2A7E9E4F0C21}
constexpr GUID kSurfaceTapClsid = {
    0x6c1f5b2e, 0x6a6e, 0x4e1c, {0x9e, 0x36, 0x2a, 0x7e, 0x9e, 0x4f, 0x0c, 0x21}};

// Layout constants (Section 4 of the plan). DIPs, not pixels.
constexpr double kPanelBodyWidthDip = 220.0;
constexpr double kPanelGapDip = 8.0;
constexpr double kPanelTotalReservationDip = kPanelBodyWidthDip + kPanelGapDip; // 228
constexpr double kPanelLeftColumnDip = 124.0;

constexpr double kSupportedBodyWidthsDip[3] = {220.0, 280.0, 340.0};

// VisualDiagConnectionN search bound (Section 3).
constexpr int kVisualDiagConnectionMin = 1;
constexpr int kVisualDiagConnectionMax = 10000;

constexpr int kAttachTimeoutSeconds = 5;
constexpr int kBackoffSequenceSeconds[] = {1, 2, 4, 8, 16, 30};
constexpr int kBackoffResetAfterSeconds = 60;

constexpr int kStaleAfterSeconds = 3;
constexpr int kSurfaceRemoveAfterSeconds = 10;
constexpr int kShutdownGraceSeconds = 2;

constexpr size_t kMaxCellUtf16Units = 63;
constexpr size_t kMaxTooltipUtf16Units = 511;
constexpr size_t kMaxFrameBytes = 16 * 1024;

enum class AttachmentState {
  Starting,
  Attached,
  WaitingForDisplay,
  WaitingForTaskbar,
  Stale,
  Retrying,
  UnsupportedLayout,
  Disabled,
};

// The only actions the panel may request. Nothing else can cross this
// interface — no command, path, script or elevation (plan Section 4).
enum class PanelAction : uint32_t {
  None = 0,
  ShowDashboard = 1,
  OpenSettings = 2,
  DisableTaskbar = 3,
};

enum class LayoutAdapter {
  None,
  A_ExplicitColumns,
  B_NoExplicitColumns,
};

// Identity of a taskbar target, resolved by monitor device path (never an
// HMONITOR / HWND / array index / desktop coordinate — Section 3).
struct TaskbarTarget {
  wchar_t monitorDevicePath[256];
  int windowsDisplayNumber;
  bool isPrimary;
  HWND trayWnd; // Shell_TrayWnd or Shell_SecondaryTrayWnd, resolved fresh each attach attempt
};

// Host <-> Surface shared-memory structure (Section 4, "Host-to-surface
// interface"). POD, versioned, fixed size. Both binaries must build from
// this exact header revision.
#pragma pack(push, 1)
struct SharedState {
  uint32_t magic;        // 'PTMB'
  uint32_t version;      // structure version, bump on any layout change
  uint32_t structSize;   // sizeof(SharedState), for defensive validation

  uint32_t hostPid;
  int64_t hostProcessCreationTime; // FILETIME as int64

  int64_t hostHeartbeatTick;
  int64_t lastSnapshotTick;
  wchar_t sourceSequence[24]; // decimal string, matches protocol's snapshot.sourceSequence

  uint8_t enabled;
  RECT selectedTaskbarRect;
  double bodyWidthDip;

  wchar_t cells[6][kMaxCellUtf16Units + 1];
  wchar_t tooltip[kMaxTooltipUtf16Units + 1];

  uint32_t surfaceStatus;      // AttachmentState
  uint32_t attachmentGeneration;
  uint32_t actionSequence;
  uint32_t actionCode;         // 0 = none, else showDashboard/openSettings/disableTaskbar

  // Written by the surface each timer tick; the host treats its absence as
  // "the surface is gone" (Explorer restarted, or the panel was torn down)
  // and re-attaches.
  int64_t surfaceHeartbeatTick;
  uint32_t surfaceExplorerPid;
};
#pragma pack(pop)

constexpr uint32_t kSharedStateMagic = 0x50544D42; // 'PTMB'
constexpr uint32_t kSharedStateVersion = 2;

} // namespace ptmonitor::taskbar
