// PTMonitor.TaskbarSurface COM diagnostics TAP (Test Access Point).
// Explorer's XAML diagnostics runtime loads this DLL in-process and hands
// this object a live site (IXamlDiagnostics) once InitializeXamlDiagnosticsEx
// succeeds on the host side (plan Section 3, "Loading the surface").
#pragma once

#include "../shared/Protocol.h"
#include "../shared/SharedMemory.h"
#include "Panel.h"

#include <windows.h>
#include <ocidl.h>
#include <xamlOM.h>
#include <winrt/Windows.UI.Xaml.h>
#include <atomic>
#include <map>
#include <mutex>
#include <utility>
#include <vector>

namespace ptmonitor::taskbar {

class __declspec(uuid("6C1F5B2E-6A6E-4E1C-9E36-2A7E9E4F0C21")) SurfaceTapImpl
    : public IObjectWithSite,
      public IVisualTreeServiceCallback2 {
 public:
  SurfaceTapImpl() = default;

  // IUnknown
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override;
  ULONG STDMETHODCALLTYPE AddRef() override;
  ULONG STDMETHODCALLTYPE Release() override;

  // IObjectWithSite — Explorer calls SetSite() with the live IXamlDiagnostics
  // once our TAP is attached; this is the actual "we're running inside
  // Explorer now" signal.
  HRESULT STDMETHODCALLTYPE SetSite(IUnknown* pUnkSite) override;
  HRESULT STDMETHODCALLTYPE GetSite(REFIID riid, void** ppvSite) override;

  // IVisualTreeServiceCallback
  HRESULT STDMETHODCALLTYPE OnVisualTreeChange(ParentChildRelation relation, VisualElement element,
                                                VisualMutationType mutationType) override;
  // IVisualTreeServiceCallback2
  HRESULT STDMETHODCALLTYPE OnElementStateChanged(InstanceHandle element,
                                                   VisualElementState elementState,
                                                   LPCWSTR context) override;

  // One per taskbar (i.e. per monitor): the Grid that parents both the
  // taskbar frame and the system tray frame.
  struct Candidate {
    InstanceHandle grid = 0;
    InstanceHandle taskbarFrame = 0;
    InstanceHandle systemTrayFrame = 0;
    bool inspected = false;
  };

 private:
  void WalkElement(InstanceHandle handle, int depth, int maxDepth);
  void RunTreeProbe();
  void DumpLayoutProperties(InstanceHandle handle, const wchar_t* label);
  static DWORD WINAPI HitTestProbeThreadProc(LPVOID param);

  // --- Adapter B reservation (plan Section 3, "Reserving a permanent slot").
  // All of these must run on the element's dispatcher thread.
  bool GetPropIndex(InstanceHandle obj, const wchar_t* name, unsigned int* index);
  InstanceHandle MakeValue(const wchar_t* typeName, const wchar_t* value);
  double GetDoubleProp(InstanceHandle obj, const wchar_t* name);
  bool SetIntProp(InstanceHandle obj, const wchar_t* name, int value);
  InstanceHandle FindRepeaterUnder(InstanceHandle root);
  void ApplyAdapterB(const Candidate& c);
  void RemoveReservation(const Candidate& c, InstanceHandle panel);

  // Live-object path: turn diagnostics handles into real XAML objects, build
  // the panel and drive it from a dispatcher timer reading shared memory.
  template <typename T>
  T AsLiveObject(InstanceHandle handle);
  void AttachPanel(const Candidate& c);
  void StartUpdateTimer();
  void OnTimerTick();

  std::atomic<ULONG> refCount_{1};
  IXamlDiagnostics* site_ = nullptr;
  IVisualTreeService3* tree_ = nullptr;
  std::pair<RECT, RECT> probeRects_{}; // (clientRect, screenRect), set by SetSite before spawning the probe thread
  int slot_ = 0;

  // Populated from the OnVisualTreeChange replay, which arrives on Explorer's
  // threads while the probe thread reads it.
  std::atomic<unsigned int> elementsSeen_{0};
  std::mutex treeMutex_;
  std::map<InstanceHandle, Candidate> candidates_;
  std::map<InstanceHandle, unsigned int> repeaterChildCounts_;
  std::map<InstanceHandle, std::vector<InstanceHandle>> childrenByParent_;
  std::vector<InstanceHandle> repeaterHandles_;

  bool removeMode_ = false;                  // from init data: "remove" tears the panel back out
  double bodyWidthDip_ = kPanelBodyWidthDip;  // overridable to stress-test crowding

  Panel panel_;
  winrt::Windows::UI::Xaml::DispatcherTimer timer_{nullptr};
  SharedChannel channel_;
  bool channelOpen_ = false;
  int64_t lastSeenSnapshotTick_ = 0;
  bool showingStale_ = false;
  InstanceHandle existingPanel_ = 0;         // a PTMonitorTaskbarRoot found during replay
  InstanceHandle constrainedRepeater_ = 0;   // repeater whose MaxWidth we set, for exact restore
  std::vector<InstanceHandle> insertedColumns_;
};

} // namespace ptmonitor::taskbar
