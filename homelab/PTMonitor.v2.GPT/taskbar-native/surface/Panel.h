// The PTMonitor taskbar panel, built from real XAML objects via C++/WinRT.
//
// The diagnostics API is only used to bootstrap into Explorer and to turn
// element handles into IInspectable; once we hold live objects, the normal
// projections give proper layout, a DispatcherTimer and clean teardown.
// Everything here must run on the owning element's dispatcher thread.
#pragma once

#include "../shared/Protocol.h"

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.UI.Xaml.h>
#include <winrt/Windows.UI.Xaml.Controls.h>
#include <winrt/Windows.UI.Xaml.Documents.h>
#include <winrt/Windows.UI.Xaml.Media.h>

#include <functional>
#include <string>

namespace ptmonitor::taskbar {

namespace wux = winrt::Windows::UI::Xaml;
namespace wuxc = winrt::Windows::UI::Xaml::Controls;

class Panel {
 public:
  // Builds the panel and reserves its slot inside `parentGrid`, which must be
  // the Grid parenting both the taskbar frame and the system tray frame.
  bool Attach(wuxc::Grid const& parentGrid, wux::FrameworkElement const& taskbarFrame,
              wux::FrameworkElement const& systemTrayFrame, wux::FrameworkElement const& repeater,
              double bodyWidthDip);

  // Restores every property and object PTMonitor owns.
  void Detach();

  bool attached() const { return attached_; }
  /// Body width this panel was actually built with, so a host whose
  /// configuration differs can have it rebuilt.
  double body_width() const { return bodyWidthDip_; }

  // Six formatted cells, laid out as three rows of two.
  void SetCells(std::wstring const cells[6]);
  void SetTooltip(std::wstring const& tooltip);

  /// Raised when the user asks for one of the allowlisted actions.
  void SetActionHandler(std::function<void(PanelAction)> handler) {
    onAction_ = std::move(handler);
  }

  wux::FrameworkElement root() const { return root_; }

 private:
  void BuildVisuals(double bodyWidthDip);
  void WireInteractions();

  std::function<void(PanelAction)> onAction_;

  bool attached_ = false;
  double bodyWidthDip_ = 0.0;
  wuxc::Grid parentGrid_{nullptr};
  wux::FrameworkElement taskbarFrame_{nullptr};
  wux::FrameworkElement systemTrayFrame_{nullptr};
  wux::FrameworkElement repeater_{nullptr};
  wuxc::Grid root_{nullptr};
  wuxc::TextBlock cells_[6]{nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};

  // Originals, for exact restoration.
  wux::Thickness originalRepeaterMargin_{};
  bool hadRepeaterMargin_ = false;
  int originalTaskbarColumnSpan_ = 1;
};

} // namespace ptmonitor::taskbar
