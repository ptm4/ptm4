#include "Panel.h"

#include <winrt/Windows.UI.h>
#include <winrt/Windows.UI.Text.h>
#include <winrt/Windows.UI.Xaml.Automation.h>

namespace ptmonitor::taskbar {

namespace {

using namespace winrt::Windows::UI::Xaml;
using namespace winrt::Windows::UI::Xaml::Controls;
using namespace winrt::Windows::UI::Xaml::Media;

// Plan Section 4: Segoe UI, 12-DIP text, three 14-DIP rows, tabular numerals,
// stable cell positions, native foreground colour.
constexpr double kRowHeightDip = 14.0;
constexpr double kFontSizeDip = 12.0;
constexpr double kBodyPaddingDip = 6.0;
constexpr double kLeftColumnDip = 124.0;

// Uses the taskbar's own theme brush so the panel matches light, dark and
// high-contrast without PTMonitor picking colours of its own.
Brush ResolveForegroundBrush() {
  try {
    auto app = Application::Current();
    if (app) {
      auto resources = app.Resources();
      for (auto const& key : {L"TextFillColorPrimaryBrush", L"SystemControlForegroundBaseHighBrush",
                              L"ApplicationForegroundThemeBrush"}) {
        auto boxed = winrt::box_value(winrt::hstring{key});
        if (resources.HasKey(boxed)) {
          if (auto brush = resources.Lookup(boxed).try_as<Brush>()) return brush;
        }
      }
    }
  } catch (...) {
  }
  return SolidColorBrush(winrt::Windows::UI::Colors::White());
}

} // namespace

void Panel::BuildVisuals(double bodyWidthDip) {
  root_ = Grid();
  root_.Name(L"PTMonitorTaskbarRoot");
  root_.Width(bodyWidthDip);
  root_.Padding(ThicknessHelper::FromLengths(kBodyPaddingDip, 0, kBodyPaddingDip, 0));
  root_.VerticalAlignment(VerticalAlignment::Center);
  root_.HorizontalAlignment(HorizontalAlignment::Left);
  // Transparent, so the native taskbar material shows through unchanged, but
  // still hit-testable for the click handling added later.
  root_.Background(SolidColorBrush(winrt::Windows::UI::Colors::Transparent()));

  const double rightColumnDip = bodyWidthDip - (2 * kBodyPaddingDip) - kLeftColumnDip;
  ColumnDefinition left, right;
  left.Width(GridLengthHelper::FromPixels(kLeftColumnDip));
  right.Width(GridLengthHelper::FromPixels(rightColumnDip > 0 ? rightColumnDip : 84.0));
  root_.ColumnDefinitions().Append(left);
  root_.ColumnDefinitions().Append(right);

  for (int r = 0; r < 3; ++r) {
    RowDefinition row;
    row.Height(GridLengthHelper::FromPixels(kRowHeightDip));
    root_.RowDefinitions().Append(row);
  }

  auto brush = ResolveForegroundBrush();
  for (int i = 0; i < 6; ++i) {
    TextBlock tb;
    tb.FontSize(kFontSizeDip);
    tb.FontFamily(FontFamily(L"Segoe UI"));
    tb.Foreground(brush);
    tb.VerticalAlignment(VerticalAlignment::Center);
    tb.TextTrimming(TextTrimming::Clip);
    // Tabular figures keep digits from shifting cell positions as values change.
    tb.IsTextScaleFactorEnabled(false);
    winrt::Windows::UI::Xaml::Documents::Typography::SetNumeralAlignment(
        tb, winrt::Windows::UI::Xaml::FontNumeralAlignment::Tabular);

    Grid::SetRow(tb, i / 2);
    Grid::SetColumn(tb, i % 2);
    root_.Children().Append(tb);
    cells_[i] = tb;
  }
}

// Plan Section 4: single left-click shows the dashboard (it never toggles it
// closed), right-click offers a native menu. Clicking the clock continues to
// open Windows' own flyout because the panel only handles its own bounds.
void Panel::WireInteractions() {
  if (!root_) return;

  root_.Tapped([this](auto&&, auto&& args) {
    args.Handled(true);
    if (onAction_) onAction_(PanelAction::ShowDashboard);
  });

  root_.RightTapped([this](auto&&, auto&& args) {
    args.Handled(true);
    try {
      MenuFlyout flyout;

      MenuFlyoutItem open;
      open.Text(L"Open dashboard");
      open.Click([this](auto&&, auto&&) {
        if (onAction_) onAction_(PanelAction::ShowDashboard);
      });
      flyout.Items().Append(open);

      MenuFlyoutItem settings;
      settings.Text(L"Settings");
      settings.Click([this](auto&&, auto&&) {
        if (onAction_) onAction_(PanelAction::OpenSettings);
      });
      flyout.Items().Append(settings);

      MenuFlyoutItem hide;
      hide.Text(L"Hide taskbar readings");
      hide.Click([this](auto&&, auto&&) {
        if (onAction_) onAction_(PanelAction::DisableTaskbar);
      });
      flyout.Items().Append(hide);

      flyout.ShowAt(root_);
    } catch (...) {
    }
  });
}

bool Panel::Attach(wuxc::Grid const& parentGrid, wux::FrameworkElement const& taskbarFrame,
                   wux::FrameworkElement const& systemTrayFrame,
                   wux::FrameworkElement const& repeater, double bodyWidthDip) {
  if (attached_) return true;
  if (!parentGrid || !taskbarFrame || !systemTrayFrame) return false;

  parentGrid_ = parentGrid;
  taskbarFrame_ = taskbarFrame;
  systemTrayFrame_ = systemTrayFrame;
  repeater_ = repeater;
  bodyWidthDip_ = bodyWidthDip;

  const double totalWidth = parentGrid.ActualWidth();
  const double trayWidth = systemTrayFrame.ActualWidth();
  const double reservation = bodyWidthDip + kPanelGapDip;

  BuildVisuals(bodyWidthDip);
  WireInteractions();

  // Adapter B (plan Section 3): the parent grid has no explicit columns, so
  // introduce *, <reservation>, Auto and place the three participants.
  auto columns = parentGrid_.ColumnDefinitions();
  if (columns.Size() != 0) return false; // an Adapter A tree; not handled here
  ColumnDefinition c0, c1, c2;
  c0.Width(GridLengthHelper::FromValueAndType(1.0, GridUnitType::Star));
  c1.Width(GridLengthHelper::FromPixels(reservation));
  c2.Width(GridLengthHelper::FromValueAndType(0, GridUnitType::Auto));
  columns.Append(c0);
  columns.Append(c1);
  columns.Append(c2);

  // Insert between the taskbar frame and the tray so visual order matches
  // column order.
  auto children = parentGrid_.Children();
  uint32_t insertAt = children.Size();
  for (uint32_t i = 0; i < children.Size(); ++i) {
    if (children.GetAt(i).try_as<UIElement>() == systemTrayFrame_.try_as<UIElement>()) {
      insertAt = i;
      break;
    }
  }
  children.InsertAt(insertAt, root_);

  Grid::SetColumn(taskbarFrame_, 0);
  Grid::SetColumn(root_, 1);
  Grid::SetColumn(systemTrayFrame_, 2);

  // The taskbar frame paints the full-width taskbar material, so it must keep
  // spanning the whole row; the button repeater is what actually has to give
  // up width. A right margin (rather than MaxWidth) keeps the buttons anchored
  // at their original edge instead of re-centring them.
  originalTaskbarColumnSpan_ = Grid::GetColumnSpan(taskbarFrame_);
  Grid::SetColumnSpan(taskbarFrame_, 3);

  if (repeater_) {
    originalRepeaterMargin_ = repeater_.Margin();
    hadRepeaterMargin_ = true;
    auto m = originalRepeaterMargin_;
    m.Right = originalRepeaterMargin_.Right + reservation + trayWidth;
    repeater_.Margin(m);
  }

  attached_ = true;
  (void)totalWidth;
  return true;
}

void Panel::Detach() {
  if (!attached_) return;

  try {
    if (repeater_ && hadRepeaterMargin_) repeater_.Margin(originalRepeaterMargin_);
    if (taskbarFrame_) {
      Grid::SetColumnSpan(taskbarFrame_, originalTaskbarColumnSpan_);
      Grid::SetColumn(taskbarFrame_, 0);
    }
    if (systemTrayFrame_) Grid::SetColumn(systemTrayFrame_, 0);

    if (parentGrid_) {
      auto children = parentGrid_.Children();
      for (uint32_t i = 0; i < children.Size(); ++i) {
        if (children.GetAt(i).try_as<UIElement>() == root_.try_as<UIElement>()) {
          children.RemoveAt(i);
          break;
        }
      }
      parentGrid_.ColumnDefinitions().Clear();
    }
  } catch (...) {
  }

  root_ = nullptr;
  for (auto& c : cells_) c = nullptr;
  parentGrid_ = nullptr;
  taskbarFrame_ = nullptr;
  systemTrayFrame_ = nullptr;
  repeater_ = nullptr;
  attached_ = false;
}

void Panel::SetCells(std::wstring const cells[6]) {
  for (int i = 0; i < 6; ++i) {
    if (!cells_[i]) continue;
    winrt::hstring next{cells[i]};
    // Only touch the tree when the value actually changed (plan Section 4).
    if (cells_[i].Text() != next) cells_[i].Text(next);
  }
}

void Panel::SetTooltip(std::wstring const& tooltip) {
  if (!root_) return;
  try {
    winrt::hstring text{tooltip};
    auto existing = ToolTipService::GetToolTip(root_).try_as<ToolTip>();
    if (existing) {
      if (existing.Content().try_as<winrt::hstring>() != text) existing.Content(winrt::box_value(text));
    } else {
      ToolTip tip;
      tip.Content(winrt::box_value(text));
      ToolTipService::SetToolTip(root_, tip);
    }
    winrt::Windows::UI::Xaml::Automation::AutomationProperties::SetName(root_, text);
  } catch (...) {
  }
}

} // namespace ptmonitor::taskbar
