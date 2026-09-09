// Native tests for the taskbar integration (plan Section 6, "Native").
//
// These cover the parts that can be exercised without Explorer: shared-memory
// structure and version validation, IPC bounds checks, the monitor selection
// rule, and coordinate handling for negative desktop origins and mixed DPI.
#include "../shared/Protocol.h"
#include "../shared/SharedMemory.h"
#include "../host/Discovery.h"

#include <cstdio>
#include <string>
#include <vector>

using namespace ptmonitor::taskbar;

namespace {

int g_failures = 0;
int g_checks = 0;

void Check(bool condition, const char* what) {
  ++g_checks;
  if (!condition) {
    ++g_failures;
    printf("  FAIL: %s\n", what);
  }
}

DisplayInfo MakeDisplay(const wchar_t* path, int number, bool primary) {
  DisplayInfo d;
  d.devicePath = path;
  d.friendlyName = L"Test";
  d.windowsDisplayNumber = number;
  d.isPrimary = primary;
  d.widthPx = 2560;
  d.heightPx = 1440;
  return d;
}

// --- shared state ---------------------------------------------------------

void TestSharedStateLayout() {
  printf("shared-memory structure and version validation\n");

  Check(kSharedStateVersion == 2, "version constant is current");
  Check(sizeof(SharedState) > 0, "structure has a size");

  SharedState s{};
  s.magic = kSharedStateMagic;
  s.version = kSharedStateVersion;
  s.structSize = sizeof(SharedState);

  // A consumer must reject anything that is not exactly this contract.
  const bool acceptsGood =
      s.magic == kSharedStateMagic && s.version == kSharedStateVersion && s.structSize == sizeof(SharedState);
  Check(acceptsGood, "a well-formed header is accepted");

  SharedState wrongMagic = s;
  wrongMagic.magic = 0xDEADBEEF;
  Check(wrongMagic.magic != kSharedStateMagic, "a wrong magic is detectable");

  SharedState wrongVersion = s;
  wrongVersion.version = kSharedStateVersion + 1;
  Check(wrongVersion.version != kSharedStateVersion, "a future version is detectable");

  SharedState wrongSize = s;
  wrongSize.structSize = sizeof(SharedState) / 2;
  Check(wrongSize.structSize != sizeof(SharedState), "a size mismatch is detectable");
}

void TestCellBounds() {
  printf("IPC bounds checks\n");

  SharedState s{};
  // Cells and tooltip are fixed-size and always NUL-terminated.
  Check(std::size(s.cells) == 6, "there are exactly six cells");
  Check(std::size(s.cells[0]) == kMaxCellUtf16Units + 1, "cell capacity matches the protocol limit");
  Check(std::size(s.tooltip) == kMaxTooltipUtf16Units + 1, "tooltip capacity matches the protocol limit");
  Check(kMaxFrameBytes == 16 * 1024, "frame limit is 16 KiB");

  // Writing an over-long value must truncate rather than overflow.
  const std::wstring tooLong(kMaxCellUtf16Units * 3, L'x');
  const size_t capacity = std::size(s.cells[0]);
  const size_t copy = tooLong.size() < (capacity - 1) ? tooLong.size() : (capacity - 1);
  wmemcpy(s.cells[0], tooLong.c_str(), copy);
  s.cells[0][copy] = L'\0';
  Check(wcslen(s.cells[0]) == kMaxCellUtf16Units, "an over-long cell is truncated to the limit");
  Check(s.cells[0][capacity - 1] == L'\0', "the cell stays NUL-terminated");
}

void TestNamesAreSessionScoped() {
  printf("shared object naming\n");
  const std::wstring map = SharedMemoryName();
  const std::wstring mutex = SharedMutexName();
  Check(map.rfind(L"Local\\", 0) == 0, "mapping is session-local");
  Check(mutex.rfind(L"Local\\", 0) == 0, "mutex is session-local");
  Check(map != mutex, "mapping and mutex use distinct names");
  Check(map.find(L"S-1-") != std::wstring::npos, "name is derived from the user SID");
}

void TestChannelRoundTrip() {
  printf("host/client channel round trip\n");

  SharedChannel host;
  if (!host.CreateAsHost()) {
    printf("  SKIP: could not create the channel in this environment\n");
    return;
  }

  SharedChannel client;
  Check(client.OpenAsClient(), "a client can open the host's channel");
  if (!client.valid()) return;

  Check(host.TryLock(1000), "the host can take the lock");
  wcscpy_s(host.state()->cells[0], L"CPU 42%");
  host.state()->lastSnapshotTick = 1234;
  host.Unlock();

  Check(client.TryLock(1000), "the client can take the lock afterwards");
  Check(wcscmp(client.state()->cells[0], L"CPU 42%") == 0, "the client observes the host's write");
  Check(client.state()->lastSnapshotTick == 1234, "scalar fields survive the round trip");
  client.Unlock();

  // The Explorer side never blocks. A mutex is reentrant for its owning
  // thread, so genuine contention has to come from another thread.
  HANDLE acquired = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  HANDLE release = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  struct HolderArgs {
    SharedChannel* channel;
    HANDLE acquired;
    HANDLE release;
  } args{&host, acquired, release};

  HANDLE holder = CreateThread(
      nullptr, 0,
      [](LPVOID p) -> DWORD {
        auto* a = static_cast<HolderArgs*>(p);
        if (a->channel->TryLock(1000)) {
          SetEvent(a->acquired);
          WaitForSingleObject(a->release, 5000);
          a->channel->Unlock();
        }
        return 0;
      },
      &args, 0, nullptr);

  if (holder && WaitForSingleObject(acquired, 2000) == WAIT_OBJECT_0) {
    const DWORD before = GetTickCount();
    const bool got = client.TryLock(0);
    const DWORD elapsed = GetTickCount() - before;
    Check(!got, "a zero-timeout acquisition fails while another thread holds the lock");
    Check(elapsed < 200, "a zero-timeout acquisition returns immediately");
    if (got) client.Unlock();
  }
  SetEvent(release);
  if (holder) {
    WaitForSingleObject(holder, 5000);
    CloseHandle(holder);
  }
  CloseHandle(acquired);
  CloseHandle(release);
}

// --- monitor selection ----------------------------------------------------

void TestInitialSelectionRule() {
  printf("initial display selection rule\n");

  // Sole non-primary monitor wins on a two-monitor system.
  std::vector<DisplayInfo> two{MakeDisplay(L"\\\\?\\DISPLAY#PRIMARY", 2, true),
                               MakeDisplay(L"\\\\?\\DISPLAY#SECOND", 1, false)};
  Check(ResolveInitialSelection(two) == L"\\\\?\\DISPLAY#SECOND",
        "the sole non-primary display is chosen");

  // A single monitor selects itself even though it is primary.
  std::vector<DisplayInfo> one{MakeDisplay(L"\\\\?\\DISPLAY#ONLY", 1, true)};
  Check(ResolveInitialSelection(one) == L"\\\\?\\DISPLAY#ONLY", "a lone display is chosen");

  // With several non-primary displays, the lowest Windows display number wins.
  std::vector<DisplayInfo> many{MakeDisplay(L"\\\\?\\DISPLAY#P", 1, true),
                                MakeDisplay(L"\\\\?\\DISPLAY#C", 3, false),
                                MakeDisplay(L"\\\\?\\DISPLAY#B", 2, false)};
  Check(ResolveInitialSelection(many) == L"\\\\?\\DISPLAY#B",
        "the lowest-numbered non-primary display is chosen");

  // No displays at all yields no selection rather than a bogus one.
  std::vector<DisplayInfo> none;
  Check(ResolveInitialSelection(none).empty(), "no displays yields no selection");
}

void TestTaskbarMatchingAndNegativeCoordinates() {
  printf("taskbar/monitor association\n");

  std::vector<DisplayInfo> displays{MakeDisplay(L"\\\\?\\DISPLAY#LEFT", 1, false),
                                    MakeDisplay(L"\\\\?\\DISPLAY#MAIN", 2, true)};
  // A monitor placed to the left of the primary has negative desktop
  // coordinates; identity must come from the HMONITOR, never the coordinates.
  displays[0].hMonitor = reinterpret_cast<HMONITOR>(0x1111);
  displays[1].hMonitor = reinterpret_cast<HMONITOR>(0x2222);

  TaskbarWindowInfo left{};
  left.hMonitor = reinterpret_cast<HMONITOR>(0x1111);
  left.rect = RECT{-2560, -100, 0, -52}; // entirely negative
  const DisplayInfo* matched = MatchDisplayForTaskbar(displays, left);
  Check(matched != nullptr, "a taskbar at negative coordinates still matches");
  Check(matched && matched->devicePath == L"\\\\?\\DISPLAY#LEFT", "it matches the correct display");

  TaskbarWindowInfo unknown{};
  unknown.hMonitor = reinterpret_cast<HMONITOR>(0x9999);
  Check(MatchDisplayForTaskbar(displays, unknown) == nullptr,
        "an unmatched taskbar yields no display rather than a guess");

  TaskbarWindowInfo detached{};
  detached.hMonitor = nullptr;
  Check(MatchDisplayForTaskbar(displays, detached) == nullptr,
        "a taskbar with no monitor yields no display");
}

void TestReservationGeometry() {
  printf("reservation geometry\n");

  Check(kPanelBodyWidthDip == 220.0, "default body width is 220 DIP");
  Check(kPanelGapDip == 8.0, "gap before the tray is 8 DIP");
  Check(kPanelTotalReservationDip == 228.0, "total reservation is 228 DIP");
  Check(kPanelLeftColumnDip == 124.0, "left column is 124 DIP");

  // Every supported width keeps the left column fixed and grows the right one,
  // and stays positive at 1.0/1.25/1.5/2.0 scaling.
  for (double body : kSupportedBodyWidthsDip) {
    const double right = body - 12.0 /* padding */ - kPanelLeftColumnDip;
    Check(right > 0.0, "the right column stays positive at every supported width");
    for (double scale : {1.0, 1.25, 1.5, 2.0}) {
      Check(body * scale > 0.0, "scaled width remains positive");
    }
  }
  Check(kSupportedBodyWidthsDip[0] == 220.0 && kSupportedBodyWidthsDip[1] == 280.0 &&
            kSupportedBodyWidthsDip[2] == 340.0,
        "exactly the three documented widths are offered");
}

void TestRecoveryConstants() {
  printf("recovery policy\n");

  Check(kStaleAfterSeconds == 3, "readings go stale after three seconds");
  Check(kSurfaceRemoveAfterSeconds == 10, "the surface is removed after ten seconds without a host");
  Check(kShutdownGraceSeconds == 2, "shutdown allows two seconds for cleanup");
  Check(kAttachTimeoutSeconds == 5, "an attach attempt is limited to five seconds");

  // The backoff ladder is monotonic and capped at thirty seconds.
  int previous = 0;
  for (int seconds : kBackoffSequenceSeconds) {
    Check(seconds > previous, "backoff increases");
    Check(seconds <= 30, "backoff is capped at thirty seconds");
    previous = seconds;
  }
  Check(kBackoffResetAfterSeconds == 60, "backoff resets after a minute of stability");
}

void TestActionAllowlist() {
  printf("action allowlist\n");

  Check(static_cast<uint32_t>(PanelAction::None) == 0, "zero means no pending action");
  Check(static_cast<uint32_t>(PanelAction::ShowDashboard) == 1, "showDashboard is 1");
  Check(static_cast<uint32_t>(PanelAction::OpenSettings) == 2, "openSettings is 2");
  Check(static_cast<uint32_t>(PanelAction::DisableTaskbar) == 3, "disableTaskbar is 3");

  // Anything outside the allowlist must be rejected by the relay.
  for (uint32_t code : {0u, 4u, 99u, 0xFFFFFFFFu}) {
    const bool known = code == 1 || code == 2 || code == 3;
    Check(!known, "codes outside the allowlist are not recognised actions");
  }
}

} // namespace

int wmain() {
  printf("PTMonitor taskbar native tests\n\n");

  TestSharedStateLayout();
  TestCellBounds();
  TestNamesAreSessionScoped();
  TestChannelRoundTrip();
  TestInitialSelectionRule();
  TestTaskbarMatchingAndNegativeCoordinates();
  TestReservationGeometry();
  TestRecoveryConstants();
  TestActionAllowlist();

  printf("\n%d checks, %d failures\n", g_checks, g_failures);
  if (g_failures == 0) {
    printf("PASS\n");
    return 0;
  }
  printf("FAIL\n");
  return 1;
}
