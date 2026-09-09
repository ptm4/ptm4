#include "SurfaceTap.h"
#include "../shared/Protocol.h"

#include <winstring.h>
#include <cmath>
#include <cstdio>
#include <string>

namespace ptmonitor::taskbar {

namespace {

// Gate-only diagnostic sink: SetSite runs inside explorer.exe, so there is
// no console to write to. Append one line per attach attempt to a fixed
// path so the host process (running outside Explorer) can read back what
// actually happened in-process. Removed once the gate gives way to the
// real IPC channel in a later stage.
void LogGateEvidence(const wchar_t* fmt, ...) {
  wchar_t buf[1024];
  va_list args;
  va_start(args, fmt);
  vswprintf_s(buf, fmt, args);
  va_end(args);

  wchar_t path[MAX_PATH];
  GetTempPathW(MAX_PATH, path);
  wcscat_s(path, L"ptmonitor_gate_evidence.log");

  HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                          OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (h == INVALID_HANDLE_VALUE) return;
  SetFilePointer(h, 0, nullptr, FILE_END);

  std::wstring line = buf;
  line += L"\r\n";
  DWORD written = 0;
  WriteFile(h, line.c_str(), static_cast<DWORD>(line.size() * sizeof(wchar_t)), &written, nullptr);
  CloseHandle(h);
}

std::wstring BstrToLoggable(BSTR b, size_t maxLen = 200) {
  if (!b) return L"<null>";
  std::wstring s(b, SysStringLen(b));
  if (s.size() > maxLen) s.resize(maxLen);
  return s;
}

} // namespace

HRESULT STDMETHODCALLTYPE SurfaceTapImpl::QueryInterface(REFIID riid, void** ppv) {
  if (!ppv) return E_POINTER;
  if (riid == __uuidof(IUnknown) || riid == __uuidof(IObjectWithSite)) {
    *ppv = static_cast<IObjectWithSite*>(this);
  } else if (riid == __uuidof(IVisualTreeServiceCallback) || riid == __uuidof(IVisualTreeServiceCallback2)) {
    *ppv = static_cast<IVisualTreeServiceCallback2*>(this);
  } else {
    *ppv = nullptr;
    return E_NOINTERFACE;
  }
  AddRef();
  return S_OK;
}

ULONG STDMETHODCALLTYPE SurfaceTapImpl::AddRef() { return ++refCount_; }

ULONG STDMETHODCALLTYPE SurfaceTapImpl::Release() {
  const ULONG n = --refCount_;
  if (n == 0) delete this;
  return n;
}

HRESULT STDMETHODCALLTYPE SurfaceTapImpl::SetSite(IUnknown* pUnkSite) {
  LogGateEvidence(L"SetSite called, pid=%lu, tick=%lu, pUnkSite=%p", GetCurrentProcessId(),
                   GetTickCount(), pUnkSite);

  if (site_) {
    site_->Release();
    site_ = nullptr;
  }
  if (!pUnkSite) {
    return S_OK; // Explorer detaching us
  }

  HRESULT hr = pUnkSite->QueryInterface(IID_PPV_ARGS(&site_));
  if (FAILED(hr)) {
    LogGateEvidence(L"QueryInterface(IXamlDiagnostics) failed hr=0x%08lx", hr);
    return hr;
  }

  if (tree_) {
    tree_->Release();
    tree_ = nullptr;
  }
  // The diagnostics site typically implements both IXamlDiagnostics and the
  // IVisualTreeService family on the same object (per VS's Live Visual Tree
  // protocol); QI it separately since IObjectWithSite only hands us pUnkSite.
  pUnkSite->QueryInterface(IID_PPV_ARGS(&tree_));
  LogGateEvidence(L"QueryInterface(IVisualTreeService3) %s", tree_ ? L"succeeded" : L"FAILED");

  IInspectable* uiLayer = nullptr;
  hr = site_->GetUiLayer(&uiLayer);
  if (SUCCEEDED(hr) && uiLayer) {
    HSTRING className = nullptr;
    if (SUCCEEDED(uiLayer->GetRuntimeClassName(&className)) && className) {
      UINT32 len = 0;
      const wchar_t* raw = WindowsGetStringRawBuffer(className, &len);
      LogGateEvidence(L"GetUiLayer succeeded, runtime class = %.*s", len, raw);
      WindowsDeleteString(className);
    } else {
      LogGateEvidence(L"GetUiLayer succeeded but GetRuntimeClassName failed");
    }

    uiLayer->Release();
  } else {
    LogGateEvidence(L"GetUiLayer failed hr=0x%08lx", hr);
  }

  // GetUiLayer() is the diagnostics adorner layer (empty overlay), not the
  // app content — HitTest against the real taskbar screen rect instead, per
  // the InitializationData the host passed us (plan Section 3's automation-
  // peer bounding-rect matching, done here via the diagnostics-native HitTest
  // rather than a separate AutomationPeer walk).
  BSTR initData = nullptr;
  hr = site_->GetInitializationData(&initData);
  if (FAILED(hr) || !initData) {
    LogGateEvidence(L"GetInitializationData failed hr=0x%08lx", hr);
    return S_OK;
  }
  int slot = 0;
  RECT screenRect{}, clientRect{};
  swscanf_s(initData, L"%d;%ld,%ld,%ld,%ld;%ld,%ld,%ld,%ld", &slot, &screenRect.left, &screenRect.top,
            &screenRect.right, &screenRect.bottom, &clientRect.left, &clientRect.top,
            &clientRect.right, &clientRect.bottom);
  removeMode_ = wcsstr(initData, L";remove") != nullptr;
  if (const wchar_t* w = wcsstr(initData, L"apply;")) {
    const int override = _wtoi(w + 6);
    if (override > 0) bodyWidthDip_ = static_cast<double>(override);
  }
  LogGateEvidence(L"slot=%d screenRect=(%ld,%ld,%ld,%ld) clientRect=(%ld,%ld,%ld,%ld) mode=%s", slot,
                   screenRect.left, screenRect.top, screenRect.right, screenRect.bottom,
                   clientRect.left, clientRect.top, clientRect.right, clientRect.bottom,
                   removeMode_ ? L"REMOVE" : L"APPLY");
  SysFreeString(initData);

  if (!tree_) {
    LogGateEvidence(L"No IVisualTreeService3, cannot walk tree.");
    return S_OK;
  }

  // InitializeXamlDiagnosticsEx on the host side blocks until SetSite
  // returns, so retrying HitTest synchronously here starves the host's own
  // attach timeout (confirmed empirically: a 2s in-line retry loop caused
  // every VisualDiagConnection slot to time out). Probe from a detached
  // worker thread instead, well after attach has completed.
  slot_ = slot;
  probeRects_ = {clientRect, screenRect};
  AddRef(); // released by the thread when it finishes
  HANDLE th = CreateThread(nullptr, 0, &SurfaceTapImpl::HitTestProbeThreadProc, this, 0, nullptr);
  if (th) {
    CloseHandle(th);
  } else {
    LogGateEvidence(L"CreateThread for HitTest probe failed, gle=%lu", GetLastError());
    Release();
  }

  return S_OK;
}

DWORD WINAPI SurfaceTapImpl::HitTestProbeThreadProc(LPVOID param) {
  auto* self = static_cast<SurfaceTapImpl*>(param);
  self->RunTreeProbe();
  self->Release();
  return 0;
}

void SurfaceTapImpl::RunTreeProbe() {
  // The IVisualTreeService protocol is push-based: once a callback is
  // advised, the runtime replays the ENTIRE existing visual tree through
  // OnVisualTreeChange(..., Add) — one call per element, carrying handle,
  // type name, x:Name and child count. That, not HitTest, is how VS's Live
  // Visual Tree enumerates a running app. HitTest appears to be scoped to
  // the (always empty) diagnostics adorner layer, which is why every rect
  // returned E_INVALIDARG.
  const HRESULT advised = tree_->AdviseVisualTreeChange(this);
  LogGateEvidence(L"[slot=%d] AdviseVisualTreeChange hr=0x%08lx", slot_, advised);
  if (FAILED(advised)) return;

  // Let the tree replay land, then report what arrived.
  Sleep(3000);
  LogGateEvidence(L"[slot=%d] tree replay done: %u elements seen", slot_, elementsSeen_.load());

  size_t found = 0;
  {
    std::lock_guard<std::mutex> lock(treeMutex_);
    for (const auto& [parent, c] : candidates_) {
      if (c.taskbarFrame && c.systemTrayFrame) ++found;
    }
  }
  // The actual property inspection happens inside OnVisualTreeChange, on the
  // element's own dispatcher thread; this thread only reports the tally.
  LogGateEvidence(L"[slot=%d] %zu containing Grid(s) with both frames", slot_, found);
}

// IVisualTreeService2::GetPropertyIndex does not resolve these names on this
// build, but the property chain reports each property's index directly — so
// resolve by walking the chain, which is known to work.
bool SurfaceTapImpl::GetPropIndex(InstanceHandle obj, const wchar_t* name, unsigned int* index) {
  if (!tree_) return false;
  if (SUCCEEDED(tree_->GetPropertyIndex(obj, name, index)) && *index != 0) return true;

  unsigned int sourceCount = 0, propCount = 0;
  PropertyChainSource* sources = nullptr;
  PropertyChainValue* values = nullptr;
  if (FAILED(tree_->GetPropertyValuesChain(obj, &sourceCount, &sources, &propCount, &values))) {
    LogGateEvidence(L"    GetPropIndex('%s'): property chain unavailable", name);
    return false;
  }

  bool found = false;
  for (unsigned int i = 0; i < propCount; ++i) {
    if (!found && values[i].PropertyName && wcscmp(values[i].PropertyName, name) == 0) {
      *index = values[i].Index;
      found = true;
    }
    if (values[i].Type) SysFreeString(values[i].Type);
    if (values[i].DeclaringType) SysFreeString(values[i].DeclaringType);
    if (values[i].ValueType) SysFreeString(values[i].ValueType);
    if (values[i].ItemType) SysFreeString(values[i].ItemType);
    if (values[i].Value) SysFreeString(values[i].Value);
    if (values[i].PropertyName) SysFreeString(values[i].PropertyName);
  }
  CoTaskMemFree(values);
  for (unsigned int i = 0; i < sourceCount; ++i) {
    if (sources[i].TargetType) SysFreeString(sources[i].TargetType);
    if (sources[i].Name) SysFreeString(sources[i].Name);
  }
  CoTaskMemFree(sources);

  if (!found) LogGateEvidence(L"    GetPropIndex('%s'): NOT FOUND in property chain", name);
  return found;
}

// Values passed to SetProperty must themselves be instances; the diagnostics
// service builds them from a type name plus a string representation.
InstanceHandle SurfaceTapImpl::MakeValue(const wchar_t* typeName, const wchar_t* value) {
  if (!tree_) return 0;

  // Object construction and value parsing take different shapes of the second
  // argument; which one this build accepts is undocumented, so try null (pure
  // construction), then empty, then the literal value.
  const wchar_t* attempts[3] = {value, value ? nullptr : L"", nullptr};
  int attemptCount = value ? 2 : 2;
  if (!value) {
    attempts[0] = nullptr;
    attempts[1] = L"";
  }

  BSTR t = SysAllocString(typeName);
  InstanceHandle h = 0;
  HRESULT hr = E_FAIL;
  for (int i = 0; i < attemptCount; ++i) {
    BSTR v = attempts[i] ? SysAllocString(attempts[i]) : nullptr;
    hr = tree_->CreateInstance(t, v, &h);
    if (v) SysFreeString(v);
    if (SUCCEEDED(hr)) {
      SysFreeString(t);
      return h;
    }
    LogGateEvidence(L"    CreateInstance(%s, %s) hr=0x%08lx", typeName,
                     attempts[i] ? attempts[i] : L"<null>", hr);
  }
  SysFreeString(t);
  return 0;
}

double SurfaceTapImpl::GetDoubleProp(InstanceHandle obj, const wchar_t* name) {
  unsigned int sourceCount = 0, propCount = 0;
  PropertyChainSource* sources = nullptr;
  PropertyChainValue* values = nullptr;
  if (!tree_ || FAILED(tree_->GetPropertyValuesChain(obj, &sourceCount, &sources, &propCount, &values)))
    return 0.0;

  double result = 0.0;
  for (unsigned int i = 0; i < propCount; ++i) {
    if (values[i].PropertyName && wcscmp(values[i].PropertyName, name) == 0 && values[i].Value) {
      result = _wtof(values[i].Value);
      break;
    }
  }
  for (unsigned int i = 0; i < propCount; ++i) {
    if (values[i].Type) SysFreeString(values[i].Type);
    if (values[i].DeclaringType) SysFreeString(values[i].DeclaringType);
    if (values[i].ValueType) SysFreeString(values[i].ValueType);
    if (values[i].ItemType) SysFreeString(values[i].ItemType);
    if (values[i].Value) SysFreeString(values[i].Value);
    if (values[i].PropertyName) SysFreeString(values[i].PropertyName);
  }
  CoTaskMemFree(values);
  for (unsigned int i = 0; i < sourceCount; ++i) {
    if (sources[i].TargetType) SysFreeString(sources[i].TargetType);
    if (sources[i].Name) SysFreeString(sources[i].Name);
  }
  CoTaskMemFree(sources);
  return result;
}

bool SurfaceTapImpl::SetIntProp(InstanceHandle obj, const wchar_t* name, int value) {
  unsigned int idx = 0;
  if (!GetPropIndex(obj, name, &idx)) {
    LogGateEvidence(L"    GetPropertyIndex('%s') failed", name);
    return false;
  }
  wchar_t buf[32];
  swprintf_s(buf, L"%d", value);
  const InstanceHandle v = MakeValue(L"Windows.Foundation.Int32", buf);
  if (!v) return false;
  const HRESULT hr = tree_->SetProperty(obj, v, idx);
  LogGateEvidence(L"    SetProperty(%s=%d) idx=%u hr=0x%08lx", name, value, idx, hr);
  return SUCCEEDED(hr);
}

// The repeater sits several levels below the taskbar frame, so walk down the
// parentage recorded during the tree replay to find it.
InstanceHandle SurfaceTapImpl::FindRepeaterUnder(InstanceHandle root) {
  std::vector<InstanceHandle> queue{root};
  for (size_t i = 0; i < queue.size() && i < 2000; ++i) {
    const InstanceHandle h = queue[i];
    for (InstanceHandle r : repeaterHandles_) {
      if (r == h) return r;
    }
    auto it = childrenByParent_.find(h);
    if (it != childrenByParent_.end()) {
      for (InstanceHandle child : it->second) queue.push_back(child);
    }
  }
  return 0;
}

// Diagnostics hands out opaque handles; GetIInspectableFromHandle turns one
// into the real in-process object, after which the ordinary projections work.
// Only valid on the object's dispatcher thread.
template <typename T>
T SurfaceTapImpl::AsLiveObject(InstanceHandle handle) {
  if (!site_ || !handle) return nullptr;
  IInspectable* raw = nullptr;
  if (FAILED(site_->GetIInspectableFromHandle(handle, &raw)) || !raw) return nullptr;
  winrt::Windows::Foundation::IInspectable insp{nullptr};
  winrt::copy_from_abi(insp, raw);
  raw->Release();
  return insp.try_as<T>();
}

void SurfaceTapImpl::AttachPanel(const Candidate& c) {
  auto grid = AsLiveObject<wuxc::Grid>(c.grid);
  auto frame = AsLiveObject<wux::FrameworkElement>(c.taskbarFrame);
  auto tray = AsLiveObject<wux::FrameworkElement>(c.systemTrayFrame);
  auto repeater = AsLiveObject<wux::FrameworkElement>(FindRepeaterUnder(c.taskbarFrame));

  LogGateEvidence(L"  live objects: grid=%d frame=%d tray=%d repeater=%d", grid ? 1 : 0,
                   frame ? 1 : 0, tray ? 1 : 0, repeater ? 1 : 0);
  if (!grid || !frame || !tray) {
    LogGateEvidence(L"  ABORT: could not project live XAML objects");
    return;
  }

  // Route panel interactions through shared memory; the host turns them into
  // allowlisted `action` messages for PTMonitor.
  panel_.SetActionHandler([this](PanelAction action) {
    LogGateEvidence(L"  panel interaction: action=%u", static_cast<uint32_t>(action));
    if (!channelOpen_ || !channel_.TryLock(50)) {
      LogGateEvidence(L"  action dropped: channel unavailable");
      return;
    }
    SharedState* s = channel_.state();
    s->actionCode = static_cast<uint32_t>(action);
    s->actionSequence++;
    channel_.Unlock();
  });

  if (!panel_.Attach(grid, frame, tray, repeater, bodyWidthDip_)) {
    LogGateEvidence(L"  ABORT: Panel::Attach failed (unsupported layout)");
    return;
  }
  LogGateEvidence(L"  Panel attached (bodyWidth=%.0f)", bodyWidthDip_);

  channelOpen_ = channel_.OpenAsClient();
  LogGateEvidence(L"  shared channel %s", channelOpen_ ? L"opened" : L"NOT AVAILABLE (host not running)");

  StartUpdateTimer();
}

// Plan Section 4: a 250 ms dispatcher timer processes pending state; source
// data still changes only at the existing one-second cadence.
void SurfaceTapImpl::StartUpdateTimer() {
  try {
    timer_ = winrt::Windows::UI::Xaml::DispatcherTimer();
    timer_.Interval(std::chrono::milliseconds(250));
    timer_.Tick([this](auto&&, auto&&) {
      try {
        OnTimerTick();
      } catch (...) {
        // Never let a feature exception reach Explorer.
      }
    });
    timer_.Start();
    LogGateEvidence(L"  dispatcher timer started (250ms)");
  } catch (...) {
    LogGateEvidence(L"  dispatcher timer FAILED to start");
  }
}

void SurfaceTapImpl::OnTimerTick() {
  if (!panel_.attached()) return;

  if (!channelOpen_) {
    channelOpen_ = channel_.OpenAsClient();
    if (!channelOpen_) return;
  }

  std::wstring cells[6];
  std::wstring tooltip;
  int64_t snapshotTick = 0;
  int64_t hostHeartbeat = 0;
  double configuredWidth = 0.0;
  bool enabled = true;

  // Explorer's UI thread must never block: take the lock with zero timeout and
  // simply keep the current display if the host happens to be writing.
  if (!channel_.TryLock(0)) return;
  SharedState* s = channel_.state();
  if (s && s->magic == kSharedStateMagic) {
    for (int i = 0; i < 6; ++i) cells[i] = s->cells[i];
    tooltip = s->tooltip;
    snapshotTick = s->lastSnapshotTick;
    hostHeartbeat = s->hostHeartbeatTick;
    configuredWidth = s->bodyWidthDip;
    enabled = s->enabled != 0;
    // Tell the host we are alive; its absence is how a dead surface (and so
    // an Explorer restart) is detected.
    s->surfaceHeartbeatTick = static_cast<int64_t>(GetTickCount64());
    s->surfaceExplorerPid = GetCurrentProcessId();
    s->surfaceStatus = static_cast<uint32_t>(AttachmentState::Attached);
  }
  channel_.Unlock();

  const int64_t now = static_cast<int64_t>(GetTickCount64());

  // Disabled by the user, or the host is gone: remove the surface entirely and
  // give the reservation back (plan Section 5 — ten seconds without a host
  // heartbeat removes the surface).
  const bool hostGone =
      hostHeartbeat != 0 && (now - hostHeartbeat) > (kSurfaceRemoveAfterSeconds * 1000);
  // A panel left over from a previous host will have the previous width; a
  // newly started host must not silently adopt it. Rebuilding is the host's
  // job, so tear down and let it re-attach at the configured width.
  const bool widthMismatch =
      configuredWidth > 0.0 && std::fabs(panel_.body_width() - configuredWidth) > 0.5;

  if (!enabled || hostGone || widthMismatch) {
    LogGateEvidence(L"  detaching panel (%s)", !enabled          ? L"disabled"
                                               : hostGone        ? L"host heartbeat lost"
                                                                 : L"configured width changed");
    if (timer_) timer_.Stop();
    panel_.Detach();
    return;
  }

  // Freshness: after three seconds without a NEW source snapshot, keep the
  // panel but replace readings with dashes (plan Section 5). Staleness depends
  // on a new snapshot tick, never on heartbeats alone.
  if (snapshotTick != lastSeenSnapshotTick_) {
    lastSeenSnapshotTick_ = snapshotTick;
    showingStale_ = false;
  }
  const bool stale = snapshotTick != 0 && (now - snapshotTick) > (kStaleAfterSeconds * 1000);

  if (stale) {
    if (!showingStale_) {
      std::wstring dashes[6] = {L"CPU —", L"RAM —", L"GPU —", L"—", L"↓ —", L"↑ —"};
      panel_.SetCells(dashes);
      panel_.SetTooltip(L"Waiting for fresh readings.");
      showingStale_ = true;
    }
    return;
  }

  panel_.SetCells(cells);
  if (!tooltip.empty()) panel_.SetTooltip(tooltip);
}

// Plan Section 3, Adapter B: the parent grid has no explicit columns, so
// introduce three (*, 228 DIP, Auto), place the taskbar frame in column 0,
// PTMonitor in column 1 and the system tray in column 2, and constrain the
// taskbar frame so the reservation actually removes width from it rather
// than drawing over the app buttons.
void SurfaceTapImpl::ApplyAdapterB(const Candidate& c) {
  LogGateEvidence(L"--- ApplyAdapterB on grid=%llu (tid=%lu) ---",
                   static_cast<unsigned long long>(c.grid), GetCurrentThreadId());

  const double gridWidthBefore = GetDoubleProp(c.grid, L"ActualWidth");
  const double frameWidthBefore = GetDoubleProp(c.taskbarFrame, L"ActualWidth");
  const double trayWidthBefore = GetDoubleProp(c.systemTrayFrame, L"ActualWidth");
  LogGateEvidence(L"  BEFORE: grid=%.0f taskbarFrame=%.0f systemTray=%.0f", gridWidthBefore,
                   frameWidthBefore, trayWidthBefore);

  unsigned int colDefsIdx = 0;
  if (!GetPropIndex(c.grid, L"ColumnDefinitions", &colDefsIdx)) {
    LogGateEvidence(L"  ABORT: cannot resolve ColumnDefinitions property index");
    return;
  }
  InstanceHandle colDefs = 0;
  const HRESULT gphr = tree_->GetProperty(c.grid, colDefsIdx, &colDefs);
  LogGateEvidence(L"  ColumnDefinitions idx=%u handle=%llu hr=0x%08lx", colDefsIdx,
                   static_cast<unsigned long long>(colDefs), gphr);
  if (FAILED(gphr)) return;

  // Three columns: * (app buttons), the panel body (228 DIP by default), and
  // Auto for the native tray.
  wchar_t bodyWidthText[32];
  swprintf_s(bodyWidthText, L"%.0f", bodyWidthDip_);
  const wchar_t* widths[3] = {L"*", bodyWidthText, L"Auto"};
  for (int i = 0; i < 3; ++i) {
    const InstanceHandle col = MakeValue(L"Windows.UI.Xaml.Controls.ColumnDefinition", nullptr);
    if (!col) return;
    const InstanceHandle len = MakeValue(L"Windows.UI.Xaml.GridLength", widths[i]);
    unsigned int widthIdx = 0;
    if (len && GetPropIndex(col, L"Width", &widthIdx)) {
      const HRESULT shr = tree_->SetProperty(col, len, widthIdx);
      LogGateEvidence(L"  column[%d] width='%s' set hr=0x%08lx", i, widths[i], shr);
    }
    const HRESULT ahr = tree_->AddChild(colDefs, col, static_cast<unsigned int>(i));
    LogGateEvidence(L"  AddChild(ColumnDefinitions, col[%d]) hr=0x%08lx handle=%llu", i, ahr,
                     static_cast<unsigned long long>(col));
    if (SUCCEEDED(ahr)) insertedColumns_.push_back(col);
  }

  // The PTMonitor panel itself. Fixed test readings for the gate — real
  // values arrive over shared memory in a later stage.
  const InstanceHandle panel = MakeValue(L"Windows.UI.Xaml.Controls.TextBlock", nullptr);
  if (!panel) return;

  struct StrProp {
    const wchar_t* prop;
    const wchar_t* type;
    const wchar_t* value;
  };
  const StrProp panelProps[] = {
      {L"Text", L"Windows.Foundation.String",
       L"CPU 47%  —      RAM 59%\nGPU 38%        44°C\n↓ 4 KiB/s     ↑ 6 KiB/s"},
      {L"Name", L"Windows.Foundation.String", L"PTMonitorTaskbarRoot"},
      {L"Foreground", L"Windows.UI.Xaml.Media.SolidColorBrush", L"#FFFFFFFF"},
      {L"FontSize", L"Windows.Foundation.Double", L"12"},
  };
  for (const auto& p : panelProps) {
    unsigned int idx = 0;
    if (!GetPropIndex(panel, p.prop, &idx)) continue;
    const InstanceHandle v = MakeValue(p.type, p.value);
    if (!v) continue;
    const HRESULT hr = tree_->SetProperty(panel, v, idx);
    LogGateEvidence(L"    SetProperty(panel.%s) idx=%u hr=0x%08lx", p.prop, idx, hr);
  }
  SetIntProp(panel, L"VerticalAlignment", 1 /* Center */);

  // AddChild operates on collections, not on the parent element itself — that
  // is why adding the column definitions worked while passing the Grid
  // directly returned ERROR_NOT_FOUND. Resolve the Children collection and
  // insert between the taskbar frame and the tray so visual order matches
  // column order.
  unsigned int childrenIdx = 0;
  InstanceHandle children = 0;
  if (GetPropIndex(c.grid, L"Children", &childrenIdx) &&
      SUCCEEDED(tree_->GetProperty(c.grid, childrenIdx, &children))) {
    const HRESULT phr = tree_->AddChild(children, panel, 1);
    LogGateEvidence(L"  AddChild(grid.Children=%llu, PTMonitorTaskbarRoot=%llu, idx=1) hr=0x%08lx",
                     static_cast<unsigned long long>(children),
                     static_cast<unsigned long long>(panel), phr);
  } else {
    LogGateEvidence(L"  ABORT: could not resolve grid.Children collection");
    return;
  }

  SetIntProp(c.taskbarFrame, L"Grid.Column", 0);
  SetIntProp(panel, L"Grid.Column", 1);
  SetIntProp(c.systemTrayFrame, L"Grid.Column", 2);

  // The taskbar frame paints the taskbar's full-width background, so it must
  // keep spanning the whole row — constraining the frame itself leaves our
  // column with no taskbar material behind it (observed as wallpaper showing
  // through). Plan Section 3, Adapter B: "Preserve background elements
  // spanning the complete taskbar" / "Assign full-width background elements a
  // three-column span". The width limit therefore goes on the button
  // repeater, which is what actually needs to shrink and overflow.
  SetIntProp(c.taskbarFrame, L"Grid.ColumnSpan", 3);

  const double col0 = gridWidthBefore - bodyWidthDip_ - trayWidthBefore;
  const InstanceHandle repeater = FindRepeaterUnder(c.taskbarFrame);
  LogGateEvidence(L"  repeater under taskbarFrame = %llu, col0=%.0f",
                   static_cast<unsigned long long>(repeater), col0);

  // Use a right margin rather than MaxWidth: the repeater centres itself
  // inside the frame, so a MaxWidth shrinks it symmetrically and visibly
  // shifts the buttons inward. A margin reduces the available area while the
  // repeater still stretches into what remains, keeping its original edge.
  const double reserved = bodyWidthDip_ + trayWidthBefore;
  unsigned int marginIdx = 0;
  if (repeater && reserved > 0 && GetPropIndex(repeater, L"Margin", &marginIdx)) {
    wchar_t buf[64];
    swprintf_s(buf, L"0,0,%.0f,0", reserved);
    const InstanceHandle mg = MakeValue(L"Windows.UI.Xaml.Thickness", buf);
    if (mg) {
      const HRESULT mhr = tree_->SetProperty(repeater, mg, marginIdx);
      LogGateEvidence(L"  SetProperty(repeater.Margin=%s) hr=0x%08lx", buf, mhr);
      constrainedRepeater_ = repeater;
    }
  }

  // Layout is asynchronous; sample a few times so a genuine reservation is
  // distinguishable from a not-yet-run layout pass.
  for (int i = 1; i <= 3; ++i) {
    Sleep(1000);
    LogGateEvidence(L"  AFTER[%ds]: grid=%.0f taskbarFrame=%.0f systemTray=%.0f panel=%.0f", i,
                     GetDoubleProp(c.grid, L"ActualWidth"),
                     GetDoubleProp(c.taskbarFrame, L"ActualWidth"),
                     GetDoubleProp(c.systemTrayFrame, L"ActualWidth"),
                     GetDoubleProp(panel, L"ActualWidth"));
  }
}

// Plan Section 3: "Remove inserted objects by identity, not stale numeric
// indexes" and restore what PTMonitor actually owns.
void SurfaceTapImpl::RemoveReservation(const Candidate& c, InstanceHandle panel) {
  LogGateEvidence(L"--- RemoveReservation grid=%llu panel=%llu ---",
                   static_cast<unsigned long long>(c.grid),
                   static_cast<unsigned long long>(panel));

  // Drop the panel by locating it by identity among the grid's children.
  unsigned int childrenIdx = 0;
  if (GetPropIndex(c.grid, L"Children", &childrenIdx)) {
    InstanceHandle children = 0;
    if (SUCCEEDED(tree_->GetProperty(c.grid, childrenIdx, &children))) {
      unsigned int count = 0;
      if (SUCCEEDED(tree_->GetCollectionCount(children, &count)) && count > 0) {
        unsigned int want = count;
        CollectionElementValue* elems = nullptr;
        if (SUCCEEDED(tree_->GetCollectionElements(children, 0, &want, &elems))) {
          for (unsigned int i = 0; i < want; ++i) {
            const InstanceHandle h = elems[i].Value ? wcstoull(elems[i].Value, nullptr, 10) : 0;
            if (h == panel) {
              const HRESULT rhr = tree_->RemoveChild(children, i);
              LogGateEvidence(L"  RemoveChild(grid.Children, idx=%u) hr=0x%08lx", i, rhr);
            }
            if (elems[i].Value) SysFreeString(elems[i].Value);
            if (elems[i].ValueType) SysFreeString(elems[i].ValueType);
          }
          CoTaskMemFree(elems);
        }
      }
    }
  }

  // Clear the columns we introduced and the constraints we applied, so the
  // grid returns to its original single-cell overlap layout.
  unsigned int colDefsIdx = 0;
  if (GetPropIndex(c.grid, L"ColumnDefinitions", &colDefsIdx)) {
    InstanceHandle colDefs = 0;
    if (SUCCEEDED(tree_->GetProperty(c.grid, colDefsIdx, &colDefs))) {
      const HRESULT chr = tree_->ClearChildren(colDefs);
      LogGateEvidence(L"  ClearChildren(ColumnDefinitions) hr=0x%08lx", chr);
    }
  }

  // Restore only what PTMonitor actually changed.
  const InstanceHandle repeater =
      constrainedRepeater_ ? constrainedRepeater_ : FindRepeaterUnder(c.taskbarFrame);
  unsigned int marginIdx = 0;
  if (repeater && GetPropIndex(repeater, L"Margin", &marginIdx)) {
    const HRESULT hr = tree_->ClearProperty(repeater, marginIdx);
    LogGateEvidence(L"  ClearProperty(repeater.Margin) hr=0x%08lx", hr);
  }
  unsigned int repMaxIdx = 0;
  if (repeater && GetPropIndex(repeater, L"MaxWidth", &repMaxIdx)) {
    tree_->ClearProperty(repeater, repMaxIdx);
  }
  // The frame may still carry a stale MaxWidth from an earlier build's
  // strategy; clearing it is harmless when unset.
  unsigned int frameMaxIdx = 0;
  if (GetPropIndex(c.taskbarFrame, L"MaxWidth", &frameMaxIdx)) {
    tree_->ClearProperty(c.taskbarFrame, frameMaxIdx);
  }
  SetIntProp(c.taskbarFrame, L"Grid.Column", 0);
  SetIntProp(c.taskbarFrame, L"Grid.ColumnSpan", 1);
  SetIntProp(c.systemTrayFrame, L"Grid.Column", 0);

  Sleep(600);
  LogGateEvidence(L"  RESTORED: grid=%.0f taskbarFrame=%.0f systemTray=%.0f",
                   GetDoubleProp(c.grid, L"ActualWidth"),
                   GetDoubleProp(c.taskbarFrame, L"ActualWidth"),
                   GetDoubleProp(c.systemTrayFrame, L"ActualWidth"));
}

// Dumps the layout-relevant properties needed to choose between plan
// Section 3's Adapter A (parent grid has explicit columns) and Adapter B
// (no explicit columns), and to record originals for exact restoration.
void SurfaceTapImpl::DumpLayoutProperties(InstanceHandle handle, const wchar_t* label) {
  if (!tree_ || !handle) return;

  unsigned int sourceCount = 0, propCount = 0;
  PropertyChainSource* sources = nullptr;
  PropertyChainValue* values = nullptr;
  const HRESULT hr =
      tree_->GetPropertyValuesChain(handle, &sourceCount, &sources, &propCount, &values);
  if (FAILED(hr)) {
    LogGateEvidence(L"  [%s] GetPropertyValuesChain failed hr=0x%08lx", label, hr);
    return;
  }

  int columnDefsIndex = -1;
  for (unsigned int i = 0; i < propCount; ++i) {
    const auto& v = values[i];
    if (!v.PropertyName) continue;
    const std::wstring pn(v.PropertyName, SysStringLen(v.PropertyName));
    if (pn == L"ColumnDefinitions" || pn == L"RowDefinitions" || pn == L"Grid.Column" ||
        pn == L"Grid.ColumnSpan" || pn == L"Grid.Row" || pn == L"Width" || pn == L"MaxWidth" ||
        pn == L"HorizontalAlignment" || pn == L"ActualWidth" || pn == L"ActualHeight" ||
        pn == L"Margin" || pn == L"Padding") {
      LogGateEvidence(L"  [%s] %s = %s   (type=%s valueType=%s source=%d idx=%u)", label, pn.c_str(),
                       BstrToLoggable(v.Value, 100).c_str(), BstrToLoggable(v.Type, 60).c_str(),
                       BstrToLoggable(v.ValueType, 60).c_str(), static_cast<int>(v.Overridden),
                       v.Index);
      if (pn == L"ColumnDefinitions") columnDefsIndex = static_cast<int>(v.Index);
    }
  }

  if (columnDefsIndex >= 0) {
    InstanceHandle colDefs = 0;
    if (SUCCEEDED(tree_->GetProperty(handle, static_cast<unsigned int>(columnDefsIndex), &colDefs))) {
      unsigned int count = 0;
      const HRESULT chr = tree_->GetCollectionCount(colDefs, &count);
      LogGateEvidence(L"  [%s] *** ColumnDefinitions handle=%llu COUNT=%u hr=0x%08lx *** -> %s",
                       label, static_cast<unsigned long long>(colDefs), count, chr,
                       count > 0 ? L"ADAPTER A (explicit columns)" : L"ADAPTER B (no explicit columns)");
      if (SUCCEEDED(chr) && count > 0) {
        unsigned int want = count;
        CollectionElementValue* elems = nullptr;
        if (SUCCEEDED(tree_->GetCollectionElements(colDefs, 0, &want, &elems))) {
          for (unsigned int i = 0; i < want; ++i) {
            InstanceHandle colHandle =
                elems[i].Value ? wcstoull(elems[i].Value, nullptr, 10) : 0;
            LogGateEvidence(L"    col[%u] handle=%llu valueType=%s", i,
                             static_cast<unsigned long long>(colHandle),
                             BstrToLoggable(elems[i].ValueType, 60).c_str());
            if (colHandle) DumpLayoutProperties(colHandle, L"COLDEF");
            if (elems[i].Value) SysFreeString(elems[i].Value);
            if (elems[i].ValueType) SysFreeString(elems[i].ValueType);
          }
          CoTaskMemFree(elems);
        }
      }
    }
  }

  for (unsigned int i = 0; i < propCount; ++i) {
    if (values[i].Type) SysFreeString(values[i].Type);
    if (values[i].DeclaringType) SysFreeString(values[i].DeclaringType);
    if (values[i].ValueType) SysFreeString(values[i].ValueType);
    if (values[i].ItemType) SysFreeString(values[i].ItemType);
    if (values[i].Value) SysFreeString(values[i].Value);
    if (values[i].PropertyName) SysFreeString(values[i].PropertyName);
  }
  CoTaskMemFree(values);
  for (unsigned int i = 0; i < sourceCount; ++i) {
    if (sources[i].TargetType) SysFreeString(sources[i].TargetType);
    if (sources[i].Name) SysFreeString(sources[i].Name);
  }
  CoTaskMemFree(sources);
}

void SurfaceTapImpl::WalkElement(InstanceHandle handle, int depth, int maxDepth) {
  if (depth > maxDepth || !tree_ || !site_) return;

  std::wstring indent(depth * 2, L' ');

  IInspectable* inst = nullptr;
  std::wstring className = L"<unknown>";
  if (SUCCEEDED(site_->GetIInspectableFromHandle(handle, &inst)) && inst) {
    HSTRING hs = nullptr;
    if (SUCCEEDED(inst->GetRuntimeClassName(&hs)) && hs) {
      UINT32 len = 0;
      const wchar_t* raw = WindowsGetStringRawBuffer(hs, &len);
      className.assign(raw, len);
      WindowsDeleteString(hs);
    }
    inst->Release();
  }

  unsigned int sourceCount = 0, propCount = 0;
  PropertyChainSource* sources = nullptr;
  PropertyChainValue* values = nullptr;
  HRESULT hr = tree_->GetPropertyValuesChain(handle, &sourceCount, &sources, &propCount, &values);
  if (FAILED(hr)) {
    LogGateEvidence(L"%shandle=%llu type=%s (GetPropertyValuesChain failed 0x%08lx)", indent.c_str(),
                     static_cast<unsigned long long>(handle), className.c_str(), hr);
    return;
  }

  std::wstring name, automationId;
  int childrenPropertyIndex = -1;
  for (unsigned int i = 0; i < propCount; ++i) {
    const auto& v = values[i];
    if (!v.PropertyName) continue;
    if (wcscmp(v.PropertyName, L"Children") == 0) childrenPropertyIndex = static_cast<int>(v.Index);
    else if (wcscmp(v.PropertyName, L"Name") == 0) name = BstrToLoggable(v.Value, 80);
    else if (wcscmp(v.PropertyName, L"AutomationProperties.AutomationId") == 0)
      automationId = BstrToLoggable(v.Value, 80);
  }

  LogGateEvidence(L"%shandle=%llu type=%s name=%s automationId=%s", indent.c_str(),
                   static_cast<unsigned long long>(handle), className.c_str(), name.c_str(),
                   automationId.c_str());

  if (childrenPropertyIndex >= 0 && depth < maxDepth) {
    InstanceHandle childrenHandle = 0;
    if (SUCCEEDED(tree_->GetProperty(handle, static_cast<unsigned int>(childrenPropertyIndex),
                                      &childrenHandle))) {
      unsigned int count = 0;
      if (SUCCEEDED(tree_->GetCollectionCount(childrenHandle, &count)) && count > 0) {
        unsigned int want = min(count, 60u);
        CollectionElementValue* elems = nullptr;
        if (SUCCEEDED(tree_->GetCollectionElements(childrenHandle, 0, &want, &elems))) {
          for (unsigned int i = 0; i < want; ++i) {
            InstanceHandle childHandle = 0;
            if (elems[i].Value) childHandle = wcstoull(elems[i].Value, nullptr, 10);
            if (childHandle != 0) WalkElement(childHandle, depth + 1, maxDepth);
            if (elems[i].Value) SysFreeString(elems[i].Value);
            if (elems[i].ValueType) SysFreeString(elems[i].ValueType);
          }
          CoTaskMemFree(elems);
        }
      }
    }
  }

  for (unsigned int i = 0; i < propCount; ++i) {
    if (values[i].Type) SysFreeString(values[i].Type);
    if (values[i].DeclaringType) SysFreeString(values[i].DeclaringType);
    if (values[i].ValueType) SysFreeString(values[i].ValueType);
    if (values[i].ItemType) SysFreeString(values[i].ItemType);
    if (values[i].Value) SysFreeString(values[i].Value);
    if (values[i].PropertyName) SysFreeString(values[i].PropertyName);
  }
  CoTaskMemFree(values);
  for (unsigned int i = 0; i < sourceCount; ++i) {
    if (sources[i].TargetType) SysFreeString(sources[i].TargetType);
    if (sources[i].Name) SysFreeString(sources[i].Name);
  }
  CoTaskMemFree(sources);
}

HRESULT STDMETHODCALLTYPE SurfaceTapImpl::GetSite(REFIID riid, void** ppvSite) {
  if (!site_) return E_FAIL;
  return site_->QueryInterface(riid, ppvSite);
}

HRESULT STDMETHODCALLTYPE SurfaceTapImpl::OnVisualTreeChange(ParentChildRelation relation,
                                                               VisualElement element,
                                                               VisualMutationType mutationType) {
  // Runs on Explorer's own threads — never let anything escape into the shell
  // (plan Section 5: "Never let an ordinary feature exception propagate into
  // Explorer").
  try {
    const unsigned int n = ++elementsSeen_;

    const std::wstring type = element.Type ? std::wstring(element.Type, SysStringLen(element.Type))
                                            : L"";
    const std::wstring name = element.Name ? std::wstring(element.Name, SysStringLen(element.Name))
                                            : L"";

    // Record the anchors the reservation needs. A containing Grid is one that
    // parents BOTH a Taskbar.TaskbarFrame and a SystemTray.SystemTrayFrame —
    // exactly the shape plan Section 3 describes. There is one such Grid per
    // taskbar (one per monitor), so collect them all and disambiguate later.
    Candidate ready{};
    bool inspectNow = false;
    if (mutationType == VisualMutationType::Add) {
      std::lock_guard<std::mutex> lock(treeMutex_);
      if (type == L"Taskbar.TaskbarFrame") {
        candidates_[relation.Parent].taskbarFrame = element.Handle;
        candidates_[relation.Parent].grid = relation.Parent;
      } else if (type == L"SystemTray.SystemTrayFrame") {
        candidates_[relation.Parent].systemTrayFrame = element.Handle;
        candidates_[relation.Parent].grid = relation.Parent;
      } else if (name == L"TaskbarFrameRepeater") {
        repeaterChildCounts_[element.Handle] = element.NumChildren;
      }
      // Track parentage so the repeater belonging to a given taskbar frame can
      // be found later; the repeater is nested several levels below the frame.
      childrenByParent_[relation.Parent].push_back(element.Handle);
      if (name == L"TaskbarFrameRepeater") repeaterHandles_.push_back(element.Handle); else if (name == L"PTMonitorTaskbarRoot" ||
                 (type == L"Windows.UI.Xaml.Controls.TextBlock" &&
                  candidates_.count(relation.Parent) &&
                  candidates_[relation.Parent].taskbarFrame != 0)) {
        // A panel from a previous session is still attached — never insert a
        // second one (plan Section 5: "never leave duplicate panels").
        // Identity is structural: the native containing Grid only ever parents
        // the taskbar frame and the system tray frame, so a TextBlock directly
        // under it is necessarily ours.
        existingPanel_ = element.Handle;
        LogGateEvidence(L"[tree] found existing PTMonitor panel handle=%llu type=%s name=%s",
                         static_cast<unsigned long long>(element.Handle), type.c_str(),
                         name.c_str());
      }

      // Do not act the moment both frames are known: the tree is still being
      // replayed, and the button repeater (needed to constrain the app area)
      // arrives several elements later. Wait until it is actually reachable
      // from the taskbar frame.
      for (auto& [parent, cand] : candidates_) {
        if (cand.taskbarFrame && cand.systemTrayFrame && !cand.inspected &&
            FindRepeaterUnder(cand.taskbarFrame) != 0) {
          cand.inspected = true;
          ready = cand;
          inspectNow = true;
          break;
        }
      }
    }

    // XAML objects are thread-affine: touching them from our own worker thread
    // returns RPC_E_WRONG_THREAD (0x8001010E). This callback, by contrast,
    // arrives on the element's own dispatcher thread — which is exactly where
    // plan Section 3 requires peer/XAML access to happen — so inspect here.
    if (inspectNow) {
      LogGateEvidence(L"=== containing Grid=%llu taskbarFrame=%llu systemTrayFrame=%llu (tid=%lu) ===",
                       static_cast<unsigned long long>(ready.grid),
                       static_cast<unsigned long long>(ready.taskbarFrame),
                       static_cast<unsigned long long>(ready.systemTrayFrame),
                       GetCurrentThreadId());
      DumpLayoutProperties(ready.grid, L"GRID");
      DumpLayoutProperties(ready.taskbarFrame, L"TASKBAR_FRAME");
      DumpLayoutProperties(ready.systemTrayFrame, L"SYSTEMTRAY_FRAME");

      // Target only the selected display's taskbar. On this machine the two
      // taskbars are distinguished by system-tray width: the primary carries
      // the full notification area (~431 DIP), the secondary only clock plus
      // notifications (~87 DIP). Proper device-path matching via automation
      // peer bounds replaces this heuristic in the product implementation.
      const double trayWidth = GetDoubleProp(ready.systemTrayFrame, L"ActualWidth");
      const bool isSecondary = trayWidth > 0 && trayWidth < 200;
      LogGateEvidence(L"  target check: trayWidth=%.0f -> %s", trayWidth,
                       isSecondary ? L"SELECTED (secondary taskbar)" : L"skipped (primary)");

      if (isSecondary) {
        if (removeMode_) {
          if (panel_.attached()) {
            if (timer_) timer_.Stop();
            panel_.Detach();
            LogGateEvidence(L"  Panel detached via live objects");
          } else {
            RemoveReservation(ready, existingPanel_);
          }
        } else if (existingPanel_) {
          LogGateEvidence(L"  panel already present (handle=%llu); not inserting a duplicate",
                           static_cast<unsigned long long>(existingPanel_));
        } else {
          AttachPanel(ready);
        }
      }
    }

    // Log the whole replay while proving the gate; this is evidence-gathering
    // scaffolding, not shipping behaviour.
    if (n <= 4000) {
      LogGateEvidence(L"[tree] #%u %s handle=%llu parent=%llu type=%s name=%s children=%u", n,
                       mutationType == VisualMutationType::Add ? L"ADD" : L"REM",
                       static_cast<unsigned long long>(element.Handle),
                       static_cast<unsigned long long>(relation.Parent), type.c_str(), name.c_str(),
                       element.NumChildren);
    }
  } catch (...) {
    // swallow — never propagate into Explorer
  }
  return S_OK;
}

HRESULT STDMETHODCALLTYPE SurfaceTapImpl::OnElementStateChanged(InstanceHandle, VisualElementState,
                                                                  LPCWSTR) {
  return S_OK;
}

} // namespace ptmonitor::taskbar
