// PTMonitor.TaskbarHost.exe — plan Section 2/5.
//
// Owns the taskbar integration on PTMonitor's behalf: discovers monitors and
// taskbars, establishes the native attachment, transports state through
// shared memory, and supervises recovery. It performs no hardware collection
// of its own; readings arrive from PTMonitor over stdin as newline-delimited
// JSON.
#include "Discovery.h"
#include "XamlAttach.h"
#include "../shared/Protocol.h"
#include "../shared/SharedMemory.h"

#include <shlobj.h>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Data.Json.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

using namespace ptmonitor::taskbar;
namespace json = winrt::Windows::Data::Json;

namespace {

std::atomic<bool> g_running{true};
std::atomic<bool> g_enabled{true};
std::atomic<double> g_bodyWidth{kPanelBodyWidthDip};
// A width change cannot be applied in place: the panel is torn down by
// clearing `enabled`, and the supervisor then re-attaches at the new width.
std::atomic<bool> g_forceDetach{false};

std::mutex g_configMutex;
std::wstring g_selectedDevicePath; // empty = apply the initial-selection rule

SharedChannel g_channel;

void LogHost(const wchar_t* fmt, ...) {
  wchar_t buf[1024];
  va_list args;
  va_start(args, fmt);
  vswprintf_s(buf, fmt, args);
  va_end(args);
  // stderr is captured by PTMonitor's existing diagnostics.
  fwprintf(stderr, L"[taskbar-host] %s\n", buf);
  fflush(stderr);
}

std::wstring Utf8ToWide(const std::string& s) {
  if (s.empty()) return {};
  const int need = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
  std::wstring out(static_cast<size_t>(need), L'\0');
  MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), need);
  return out;
}

void CopyBounded(wchar_t* dest, size_t destCount, const std::wstring& src) {
  const size_t n = src.size() < (destCount - 1) ? src.size() : (destCount - 1);
  // Do not split a surrogate pair when truncating (plan Section 4).
  size_t copy = n;
  if (copy > 0 && src[copy - 1] >= 0xD800 && src[copy - 1] <= 0xDBFF) copy--;
  wmemcpy(dest, src.c_str(), copy);
  dest[copy] = L'\0';
}

// ---------------------------------------------------------------- supervisor

struct AttachmentTracker {
  DWORD explorerPid = 0;
  bool attached = false;
  int backoffIndex = 0;
  std::chrono::steady_clock::time_point nextAttempt{};
  std::chrono::steady_clock::time_point attachedSince{};
};

std::wstring ResolveTargetDevicePath(const std::vector<DisplayInfo>& displays) {
  std::lock_guard<std::mutex> lock(g_configMutex);
  if (!g_selectedDevicePath.empty()) return g_selectedDevicePath;
  const std::wstring initial = ResolveInitialSelection(displays);
  g_selectedDevicePath = initial;
  return initial;
}

std::wstring InstalledSurfaceDllPath() {
  wchar_t path[MAX_PATH];
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  std::wstring dir(path);
  const auto pos = dir.find_last_of(L"\\/");
  dir = (pos == std::wstring::npos) ? L"." : dir.substr(0, pos);

  // Beside the host in a portable layout; under `resources\` once bundled by
  // Tauri, which installs resources into that subdirectory.
  const std::wstring candidates[] = {
      dir + L"\\PTMonitor.TaskbarSurface.dll",
      dir + L"\\resources\\PTMonitor.TaskbarSurface.dll",
  };
  for (const auto& candidate : candidates) {
    if (GetFileAttributesW(candidate.c_str()) != INVALID_FILE_ATTRIBUTES) return candidate;
  }
  return {};
}

// 64-bit FNV-1a over the file contents. Only used to name a directory, so a
// non-cryptographic hash is sufficient.
bool HashFile(const std::wstring& path, uint64_t* out) {
  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                             OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) return false;

  uint64_t hash = 1469598103934665603ULL;
  std::vector<BYTE> buffer(64 * 1024);
  DWORD read = 0;
  while (ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &read, nullptr) && read > 0) {
    for (DWORD i = 0; i < read; ++i) {
      hash ^= buffer[i];
      hash *= 1099511628211ULL;
    }
  }
  CloseHandle(file);
  *out = hash;
  return true;
}

// Explorer keeps the surface DLL loaded for as long as it lives, so the
// shipped copy must never be the one it loads — otherwise an upgrade (or a
// rebuild) cannot replace the file. Stage each build into a content-hashed
// directory under PTMonitor's local data (plan Section 5) and load from there;
// older directories are removed once nothing is using them.
std::wstring SurfaceDllPath() {
  const std::wstring installed = InstalledSurfaceDllPath();
  if (installed.empty()) {
    LogHost(L"surface DLL not found beside the host or under resources\\");
    return {};
  }

  wchar_t localAppData[MAX_PATH];
  if (FAILED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, 0, localAppData))) {
    return installed;
  }
  const std::wstring runtimeRoot =
      std::wstring(localAppData) + L"\\PTMonitor-v2\\taskbar-runtime";

  uint64_t hash = 0;
  if (!HashFile(installed, &hash)) return installed;

  wchar_t hashText[32];
  swprintf_s(hashText, L"%016llx", static_cast<unsigned long long>(hash));
  const std::wstring stageDir = runtimeRoot + L"\\" + hashText;
  const std::wstring staged = stageDir + L"\\PTMonitor.TaskbarSurface.dll";

  CreateDirectoryW((std::wstring(localAppData) + L"\\PTMonitor-v2").c_str(), nullptr);
  CreateDirectoryW(runtimeRoot.c_str(), nullptr);
  CreateDirectoryW(stageDir.c_str(), nullptr);

  if (GetFileAttributesW(staged.c_str()) == INVALID_FILE_ATTRIBUTES) {
    if (!CopyFileW(installed.c_str(), staged.c_str(), FALSE)) {
      LogHost(L"could not stage the surface DLL (gle=%lu); loading in place", GetLastError());
      return installed;
    }
    LogHost(L"staged surface DLL at %s", staged.c_str());
  }

  // Retire previous builds. A directory whose DLL is still loaded by an
  // Explorer that has not restarted stays locked, and is simply skipped.
  WIN32_FIND_DATAW found{};
  HANDLE search = FindFirstFileW((runtimeRoot + L"\\*").c_str(), &found);
  if (search != INVALID_HANDLE_VALUE) {
    do {
      if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
      if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0) continue;
      if (wcscmp(found.cFileName, hashText) == 0) continue;
      const std::wstring old = runtimeRoot + L"\\" + found.cFileName;
      if (DeleteFileW((old + L"\\PTMonitor.TaskbarSurface.dll").c_str())) {
        RemoveDirectoryW(old.c_str());
      }
    } while (FindNextFileW(search, &found));
    FindClose(search);
  }

  return staged;
}

// Emits one newline-delimited JSON message to PTMonitor on stdout.
void EmitToParent(const std::wstring& json) {
  const int need =
      WideCharToMultiByte(CP_UTF8, 0, json.c_str(), static_cast<int>(json.size()), nullptr, 0,
                           nullptr, nullptr);
  std::string utf8(static_cast<size_t>(need), '\0');
  WideCharToMultiByte(CP_UTF8, 0, json.c_str(), static_cast<int>(json.size()), utf8.data(), need,
                       nullptr, nullptr);
  fwrite(utf8.data(), 1, utf8.size(), stdout);
  fputc('\n', stdout);
  fflush(stdout);
}

// Only these three actions may ever be relayed (plan Section 4).
const wchar_t* ActionName(uint32_t code) {
  switch (static_cast<PanelAction>(code)) {
    case PanelAction::ShowDashboard: return L"showDashboard";
    case PanelAction::OpenSettings: return L"openSettings";
    case PanelAction::DisableTaskbar: return L"disableTaskbar";
    default: return nullptr;
  }
}

// Forwards any pending panel interaction, then clears it.
void DrainPanelActions(uint32_t& lastSequence) {
  if (!g_channel.valid() || !g_channel.TryLock(50)) return;
  SharedState* s = g_channel.state();
  const uint32_t sequence = s->actionSequence;
  const uint32_t code = s->actionCode;
  g_channel.Unlock();

  if (sequence == lastSequence) return;
  lastSequence = sequence;

  const wchar_t* name = ActionName(code);
  if (!name) return; // unknown codes are dropped, never forwarded

  if (static_cast<PanelAction>(code) == PanelAction::DisableTaskbar) {
    g_enabled.store(false);
  }
  LogHost(L"panel action: %s", name);
  EmitToParent(std::wstring(L"{\"protocolVersion\":1,\"type\":\"action\",\"action\":\"") + name +
                L"\"}");
}

void SupervisorLoop() {
  AttachmentTracker tracker;
  const std::wstring dll = SurfaceDllPath();
  uint32_t lastActionSequence = 0;

  // Announce readiness so PTMonitor can send configuration immediately.
  EmitToParent(L"{\"protocolVersion\":1,\"type\":\"ready\"}");

  while (g_running.load()) {
    // Poll interactions far more often than topology, so clicks feel instant.
    for (int i = 0; i < 8 && g_running.load(); ++i) {
      DrainPanelActions(lastActionSequence);
      std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    if (!g_running.load()) break;

    if (!g_enabled.load()) {
      tracker.attached = false;
      continue;
    }

    const auto displays = EnumerateDisplays();
    const auto taskbars = EnumerateTaskbarWindows();
    const std::wstring target = ResolveTargetDevicePath(displays);
    if (target.empty()) continue;

    // The selected display may be disconnected; keep the selection and wait
    // rather than migrating onto another monitor (plan Section 3).
    HWND targetWnd = nullptr;
    bool displayPresent = false;
    for (const auto& d : displays) {
      if (d.devicePath == target) displayPresent = true;
    }
    for (const auto& t : taskbars) {
      const auto* match = MatchDisplayForTaskbar(displays, t);
      if (match && match->devicePath == target) targetWnd = t.hwnd;
    }
    if (!displayPresent || !targetWnd) {
      if (tracker.attached) LogHost(L"selected display/taskbar unavailable; waiting");
      tracker.attached = false;
      continue;
    }

    DWORD pid = 0;
    GetWindowThreadProcessId(targetWnd, &pid);

    // A different Explorer means a fresh taskbar, not a repeatedly failing
    // one: restart the backoff so recovery after an Explorer restart is
    // prompt instead of inheriting the previous ladder.
    if (tracker.explorerPid != 0 && pid != tracker.explorerPid) {
      LogHost(L"explorer changed (%lu -> %lu); resetting backoff", tracker.explorerPid, pid);
      tracker.backoffIndex = 0;
      tracker.nextAttempt = std::chrono::steady_clock::now();
      tracker.attached = false;
    }
    tracker.explorerPid = pid;

    // Is the surface still alive? It heartbeats through shared memory; its
    // absence means Explorer restarted or the panel was torn down.
    bool surfaceAlive = false;
    if (g_channel.valid() && g_channel.TryLock(50)) {
      SharedState* s = g_channel.state();
      const int64_t now = static_cast<int64_t>(GetTickCount64());
      surfaceAlive = s->surfaceHeartbeatTick != 0 &&
                     (now - s->surfaceHeartbeatTick) < (kSurfaceRemoveAfterSeconds * 1000) &&
                     s->surfaceExplorerPid == pid;
      g_channel.Unlock();
    }

    // A pending re-attach clears once the old panel is actually gone.
    if (g_forceDetach.load()) {
      if (!surfaceAlive) {
        LogHost(L"old panel removed; re-attaching at width %.0f", g_bodyWidth.load());
        g_forceDetach.store(false);
        tracker.backoffIndex = 0;
        tracker.nextAttempt = std::chrono::steady_clock::now();
      } else {
        tracker.attached = false;
        continue; // still waiting for the surface to tear itself down
      }
    }

    if (surfaceAlive) {
      if (!tracker.attached) {
        tracker.attached = true;
        tracker.attachedSince = std::chrono::steady_clock::now();
        LogHost(L"surface attached (explorer pid %lu)", pid);
      }
      // Reset backoff after a sustained good attachment (plan Section 5).
      if (tracker.backoffIndex != 0 &&
          std::chrono::steady_clock::now() - tracker.attachedSince >
              std::chrono::seconds(kBackoffResetAfterSeconds)) {
        tracker.backoffIndex = 0;
      }
      continue;
    }

    tracker.attached = false;
    if (std::chrono::steady_clock::now() < tracker.nextAttempt) continue;

    LogHost(L"attaching to explorer pid %lu (attempt after backoff step %d)", pid,
            tracker.backoffIndex);
    wchar_t initData[128];
    swprintf_s(initData, L"1;0,0,0,0;0,0,0,0;apply;%d", static_cast<int>(g_bodyWidth.load()));
    const AttachOutcome outcome =
        AttachToExplorerTaskbarAtSlot(targetWnd, dll, kSurfaceTapClsid, 1, initData);

    if (outcome.result == AttachResult::Success) {
      LogHost(L"attach call succeeded");
      tracker.nextAttempt = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    } else {
      const int steps = static_cast<int>(std::size(kBackoffSequenceSeconds));
      const int wait = kBackoffSequenceSeconds[tracker.backoffIndex < steps ? tracker.backoffIndex
                                                                            : steps - 1];
      if (tracker.backoffIndex < steps - 1) tracker.backoffIndex++;
      LogHost(L"attach failed hr=0x%08lx; retrying in %ds", outcome.hr, wait);
      tracker.nextAttempt = std::chrono::steady_clock::now() + std::chrono::seconds(wait);
    }
  }
}

// ------------------------------------------------------------------ protocol

void HandleSnapshot(json::JsonObject const& obj) {
  if (!g_channel.valid()) return;

  std::wstring cells[6];
  if (obj.HasKey(L"cells")) {
    auto arr = obj.GetNamedArray(L"cells");
    for (uint32_t i = 0; i < arr.Size() && i < 6; ++i) {
      cells[i] = std::wstring(arr.GetStringAt(i));
    }
  }
  const std::wstring tooltip =
      obj.HasKey(L"tooltip") ? std::wstring(obj.GetNamedString(L"tooltip")) : L"";
  const std::wstring sequence =
      obj.HasKey(L"sourceSequence") ? std::wstring(obj.GetNamedString(L"sourceSequence")) : L"";

  if (!g_channel.TryLock(1000)) return;
  SharedState* s = g_channel.state();
  for (int i = 0; i < 6; ++i) CopyBounded(s->cells[i], kMaxCellUtf16Units + 1, cells[i]);
  CopyBounded(s->tooltip, kMaxTooltipUtf16Units + 1, tooltip);
  CopyBounded(s->sourceSequence, 24, sequence);
  s->enabled = (g_enabled.load() && !g_forceDetach.load()) ? 1 : 0;
  s->bodyWidthDip = g_bodyWidth.load();
  s->lastSnapshotTick = static_cast<int64_t>(GetTickCount64());
  s->hostHeartbeatTick = s->lastSnapshotTick;
  g_channel.Unlock();
}

void HandleConfigure(json::JsonObject const& obj) {
  if (obj.HasKey(L"enabled")) g_enabled.store(obj.GetNamedBoolean(L"enabled"));

  if (obj.HasKey(L"widthDip")) {
    const double next = obj.GetNamedNumber(L"widthDip");
    if (next > 0 && next != g_bodyWidth.exchange(next)) {
      g_forceDetach.store(true); // rebuild the panel at the new width
    }
  }
  if (obj.HasKey(L"monitorDevicePath")) {
    const std::wstring next(obj.GetNamedString(L"monitorDevicePath"));
    std::lock_guard<std::mutex> lock(g_configMutex);
    if (!next.empty() && next != g_selectedDevicePath) {
      // Moving displays is remove-old then attach-new, never both at once.
      g_forceDetach.store(true);
    }
    if (!next.empty()) g_selectedDevicePath = next;
  }

  // Apply the enabled state immediately rather than waiting for the next
  // snapshot, so toggling the panel off feels instant.
  if (g_channel.valid() && g_channel.TryLock(200)) {
    g_channel.state()->enabled = (g_enabled.load() && !g_forceDetach.load()) ? 1 : 0;
    g_channel.state()->bodyWidthDip = g_bodyWidth.load();
    g_channel.Unlock();
  }
  LogHost(L"configured: enabled=%d width=%.0f", g_enabled.load() ? 1 : 0, g_bodyWidth.load());
}

void HandleLine(const std::string& utf8) {
  if (utf8.empty()) return;
  if (utf8.size() > kMaxFrameBytes) {
    LogHost(L"rejected oversized frame (%zu bytes)", utf8.size());
    return;
  }

  json::JsonObject obj{nullptr};
  if (!json::JsonObject::TryParse(Utf8ToWide(utf8), obj) || !obj) {
    LogHost(L"rejected malformed frame");
    return;
  }
  if (!obj.HasKey(L"protocolVersion") || static_cast<int>(obj.GetNamedNumber(L"protocolVersion")) != 1) {
    LogHost(L"rejected unsupported protocol version");
    return;
  }
  if (!obj.HasKey(L"type")) return;

  const std::wstring type(obj.GetNamedString(L"type"));
  if (type == L"snapshot") {
    HandleSnapshot(obj);
  } else if (type == L"configure") {
    HandleConfigure(obj);
  } else if (type == L"heartbeat") {
    if (g_channel.valid() && g_channel.TryLock(50)) {
      g_channel.state()->hostHeartbeatTick = static_cast<int64_t>(GetTickCount64());
      g_channel.Unlock();
    }
  } else if (type == L"shutdown") {
    LogHost(L"shutdown requested");
    g_running.store(false);
  }
  // Unknown message types are ignored by design.
}

} // namespace

int wmain() {
  winrt::init_apartment(winrt::apartment_type::multi_threaded);

  if (!g_channel.CreateAsHost()) {
    LogHost(L"FATAL: could not create shared channel");
    return 1;
  }
  LogHost(L"started, pid=%lu", GetCurrentProcessId());

  std::thread supervisor(SupervisorLoop);

  // Newline-delimited UTF-8 JSON on stdin. EOF (parent exit) ends the host.
  std::string line;
  int ch;
  while (g_running.load() && (ch = fgetc(stdin)) != EOF) {
    if (ch == '\n') {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      HandleLine(line);
      line.clear();
      if (line.capacity() > kMaxFrameBytes * 2) line.shrink_to_fit();
    } else {
      if (line.size() < kMaxFrameBytes * 2) line.push_back(static_cast<char>(ch));
    }
  }

  LogHost(L"stdin closed; shutting down");
  g_running.store(false);
  supervisor.join();

  // Ask the surface to tear itself down, and give it a moment to comply.
  if (g_channel.valid() && g_channel.TryLock(500)) {
    g_channel.state()->enabled = 0;
    g_channel.Unlock();
  }
  std::this_thread::sleep_for(std::chrono::seconds(kShutdownGraceSeconds));
  return 0;
}
