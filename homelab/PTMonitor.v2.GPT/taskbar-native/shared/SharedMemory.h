// Host <-> surface shared state channel (plan Section 4, "Host-to-surface
// interface"). Session-local named shared memory plus a named mutex; both
// binaries compile the same POD definition from Protocol.h.
#pragma once

#include "Protocol.h"

#include <sddl.h>
#include <string>
#include <vector>

namespace ptmonitor::taskbar {

// Names are derived from the user SID and Windows session id so that two
// users, or two sessions of the same user, never collide.
inline std::wstring CurrentUserSidString() {
  HANDLE token = nullptr;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return L"unknown";

  DWORD len = 0;
  GetTokenInformation(token, TokenUser, nullptr, 0, &len);
  std::wstring result = L"unknown";
  if (len > 0) {
    std::vector<BYTE> buf(len);
    if (GetTokenInformation(token, TokenUser, buf.data(), len, &len)) {
      auto* tu = reinterpret_cast<TOKEN_USER*>(buf.data());
      LPWSTR sid = nullptr;
      if (ConvertSidToStringSidW(tu->User.Sid, &sid) && sid) {
        result = sid;
        LocalFree(sid);
      }
    }
  }
  CloseHandle(token);
  return result;
}

inline DWORD CurrentSessionId() {
  DWORD sessionId = 0;
  ProcessIdToSessionId(GetCurrentProcessId(), &sessionId);
  return sessionId;
}

inline std::wstring SharedMemoryName() {
  return L"Local\\PTMonitorTaskbar.Map." + CurrentUserSidString() + L"." +
         std::to_wstring(CurrentSessionId());
}

inline std::wstring SharedMutexName() {
  return L"Local\\PTMonitorTaskbar.Mutex." + CurrentUserSidString() + L"." +
         std::to_wstring(CurrentSessionId());
}

// Grants the current user and SYSTEM full access, and nothing else. The
// medium-integrity Explorer process must still be able to open these objects
// when PTMonitor itself was started elevated, so the integrity label is left
// at medium rather than inheriting the elevated process's high label.
inline bool BuildPermissiveDescriptor(SECURITY_ATTRIBUTES* sa, PSECURITY_DESCRIPTOR* out) {
  const std::wstring sddl =
      L"D:(A;;GA;;;SY)(A;;GA;;;" + CurrentUserSidString() + L")S:(ML;;NW;;;ME)";
  PSECURITY_DESCRIPTOR sd = nullptr;
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &sd,
                                                             nullptr)) {
    return false;
  }
  sa->nLength = sizeof(SECURITY_ATTRIBUTES);
  sa->lpSecurityDescriptor = sd;
  sa->bInheritHandle = FALSE;
  *out = sd;
  return true;
}

// Small RAII wrapper used by both sides.
class SharedChannel {
 public:
  ~SharedChannel() { Close(); }

  bool CreateAsHost() { return Open(true); }
  bool OpenAsClient() { return Open(false); }

  void Close() {
    if (view_) {
      UnmapViewOfFile(view_);
      view_ = nullptr;
    }
    if (map_) {
      CloseHandle(map_);
      map_ = nullptr;
    }
    if (mutex_) {
      CloseHandle(mutex_);
      mutex_ = nullptr;
    }
  }

  SharedState* state() { return view_; }
  bool valid() const { return view_ != nullptr; }

  // The Explorer UI thread must never block (plan Section 4), so it only ever
  // takes the lock with a zero timeout and skips the tick if it is busy.
  bool TryLock(DWORD timeoutMs) {
    if (!mutex_) return false;
    const DWORD r = WaitForSingleObject(mutex_, timeoutMs);
    // WAIT_ABANDONED still grants ownership; the previous owner died mid-write.
    return r == WAIT_OBJECT_0 || r == WAIT_ABANDONED;
  }
  void Unlock() {
    if (mutex_) ReleaseMutex(mutex_);
  }

 private:
  bool Open(bool create) {
    const std::wstring mapName = SharedMemoryName();
    const std::wstring mutexName = SharedMutexName();

    if (create) {
      SECURITY_ATTRIBUTES sa{};
      PSECURITY_DESCRIPTOR sd = nullptr;
      const bool haveSd = BuildPermissiveDescriptor(&sa, &sd);
      map_ = CreateFileMappingW(INVALID_HANDLE_VALUE, haveSd ? &sa : nullptr, PAGE_READWRITE, 0,
                                 sizeof(SharedState), mapName.c_str());
      mutex_ = CreateMutexW(haveSd ? &sa : nullptr, FALSE, mutexName.c_str());
      if (sd) LocalFree(sd);
    } else {
      map_ = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, mapName.c_str());
      mutex_ = OpenMutexW(SYNCHRONIZE, FALSE, mutexName.c_str());
    }
    if (!map_) return false;

    view_ = static_cast<SharedState*>(
        MapViewOfFile(map_, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(SharedState)));
    if (!view_) {
      Close();
      return false;
    }

    if (create) {
      ZeroMemory(view_, sizeof(SharedState));
      view_->magic = kSharedStateMagic;
      view_->version = kSharedStateVersion;
      view_->structSize = sizeof(SharedState);
      view_->hostPid = GetCurrentProcessId();
    } else if (view_->magic != kSharedStateMagic || view_->version != kSharedStateVersion ||
               view_->structSize != sizeof(SharedState)) {
      Close();
      return false;
    }
    return true;
  }

  HANDLE map_ = nullptr;
  HANDLE mutex_ = nullptr;
  SharedState* view_ = nullptr;
};

} // namespace ptmonitor::taskbar
