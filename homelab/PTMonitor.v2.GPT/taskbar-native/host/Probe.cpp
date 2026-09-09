// Diagnostic: opens the shared channel read-only and reports what the host is
// publishing, without attaching anything to Explorer.
#include "../shared/Protocol.h"
#include "../shared/SharedMemory.h"

#include <cstdio>
#include <thread>

using namespace ptmonitor::taskbar;

int wmain() {
  SharedChannel channel;
  if (!channel.OpenAsClient()) {
    wprintf(L"shared channel NOT available (%s)\n", SharedMemoryName().c_str());
    return 1;
  }
  wprintf(L"opened %s\n", SharedMemoryName().c_str());

  for (int i = 0; i < 8; ++i) {
    if (channel.TryLock(500)) {
      SharedState* s = channel.state();
      const int64_t now = static_cast<int64_t>(GetTickCount64());
      wprintf(L"[%d] seq=%s snapAge=%lldms hostHbAge=%lldms surfHbAge=%lldms enabled=%u surfPid=%u\n",
              i, s->sourceSequence, now - s->lastSnapshotTick, now - s->hostHeartbeatTick,
              s->surfaceHeartbeatTick ? (now - s->surfaceHeartbeatTick) : -1, s->enabled,
              s->surfaceExplorerPid);
      wprintf(L"     cells: [%s] [%s] [%s] [%s] [%s] [%s]\n", s->cells[0], s->cells[1], s->cells[2],
              s->cells[3], s->cells[4], s->cells[5]);
      channel.Unlock();
    } else {
      wprintf(L"[%d] mutex busy\n", i);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
  }
  return 0;
}
