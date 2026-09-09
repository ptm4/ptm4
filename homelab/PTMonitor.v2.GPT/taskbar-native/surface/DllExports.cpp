// COM server entry points for PTMonitor.TaskbarSurface.dll.
// Explorer's XAML diagnostics runtime loads this DLL and calls
// DllGetClassObject(kSurfaceTapClsid, IID_IClassFactory, ...) to construct
// the TAP object declared in SurfaceTap.h.
#include "SurfaceTap.h"
#include "../shared/Protocol.h"

#include <atomic>

namespace ptmonitor::taskbar {

namespace {

std::atomic<ULONG> g_lockCount{0};

class ClassFactory final : public IClassFactory {
 public:
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
    if (!ppv) return E_POINTER;
    if (riid == __uuidof(IUnknown) || riid == __uuidof(IClassFactory)) {
      *ppv = static_cast<IClassFactory*>(this);
      AddRef();
      return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refCount_; }
  ULONG STDMETHODCALLTYPE Release() override {
    const ULONG n = --refCount_;
    if (n == 0) delete this;
    return n;
  }

  HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
    if (outer) return CLASS_E_NOAGGREGATION;
    auto* tap = new (std::nothrow) SurfaceTapImpl();
    if (!tap) return E_OUTOFMEMORY;
    HRESULT hr = tap->QueryInterface(riid, ppv);
    tap->Release();
    return hr;
  }

  HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
    if (lock) ++g_lockCount;
    else --g_lockCount;
    return S_OK;
  }

 private:
  std::atomic<ULONG> refCount_{1};
};

} // namespace

} // namespace ptmonitor::taskbar

extern "C" BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) {
  // Kept minimal per plan Section 3: "Keep DllMain minimal. Schedule actual
  // initialization after loading." All real work happens in SetSite, called
  // by Explorer's diagnostics runtime well after load completes.
  return TRUE;
}

extern "C" HRESULT WINAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv) {
  using ptmonitor::taskbar::kSurfaceTapClsid;
  if (rclsid != kSurfaceTapClsid) return CLASS_E_CLASSNOTAVAILABLE;
  auto* factory = new (std::nothrow) ptmonitor::taskbar::ClassFactory();
  if (!factory) return E_OUTOFMEMORY;
  HRESULT hr = factory->QueryInterface(riid, ppv);
  factory->Release();
  return hr;
}

extern "C" HRESULT WINAPI DllCanUnloadNow() {
  return ptmonitor::taskbar::g_lockCount.load() == 0 ? S_OK : S_FALSE;
}
