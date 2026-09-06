//! App state machine on the UI thread: owns the window, graphics, text, view model, tray,
//! hotkey and config; handles every window message. All modal or re-entrant work (menus,
//! message boxes, DestroyWindow) runs as an [`Action`] after the `APP` borrow is released.

use std::cell::RefCell;
use std::time::Instant;

use windows::core::{w, Result, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::Graphics::Gdi::ValidateRect;
use windows::Win32::UI::Controls::WM_MOUSELEAVE;
use windows::Win32::UI::HiDpi::GetDpiForSystem;
use windows::Win32::UI::Input::KeyboardAndMouse::{TrackMouseEvent, TME_LEAVE, TME_NONCLIENT, TRACKMOUSEEVENT};
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::Graphics::Direct2D::Common::D2D1_COLOR_F;
use windows::Win32::Graphics::Gdi::{GetSysColor, COLOR_WINDOW, COLOR_WINDOWTEXT};
use windows::Win32::UI::Accessibility::{HCF_HIGHCONTRASTON, HIGHCONTRASTW};
use windows::Win32::UI::Shell::{
    SHQueryUserNotificationState, QUNS_BUSY, QUNS_PRESENTATION_MODE, QUNS_RUNNING_D3D_FULL_SCREEN,
};
use windows::Win32::UI::WindowsAndMessaging::{
    DefWindowProcW, DestroyWindow, GetCursorPos, KillTimer, MessageBoxW, PostQuitMessage, SetTimer,
    SystemParametersInfoW, HTCAPTION, HTCLIENT, HWND_BOTTOM, MA_NOACTIVATE, MB_ICONINFORMATION,
    MB_OK, PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMSUSPEND, SPI_GETHIGHCONTRAST,
    SWP_NOZORDER, SW_SHOWNORMAL, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS, WINDOWPOS, WM_CLOSE,
    WM_DESTROY, WM_DISPLAYCHANGE, WM_DPICHANGED, WM_ENTERSIZEMOVE, WM_ERASEBKGND, WM_EXITSIZEMOVE,
    WM_HOTKEY, WM_LBUTTONUP, WM_MOUSEACTIVATE, WM_MOUSEMOVE, WM_NCHITTEST, WM_NCLBUTTONDBLCLK,
    WM_NCMOUSELEAVE, WM_NCMOUSEMOVE, WM_NCRBUTTONUP, WM_PAINT, WM_POWERBROADCAST, WM_RBUTTONUP,
    WM_SETTINGCHANGE, WM_TIMER, WM_WINDOWPOSCHANGING,
};

use crate::config::{Config, UptimeMode};
use crate::gfx::backdrop::{self, Applied, BackdropMode};
use crate::gfx::device::Gfx;
use crate::gfx::paint::{self, Painter, Styles};
use crate::gfx::text::TextEngine;
use crate::menu::{self, Cmd, MenuState};
use crate::model::{self, GpuSource, Snapshot, ViewModel};
use crate::sample::{Sampler, SamplerConfig, WM_APP_SNAPSHOT};
use crate::single_instance::{MAIN_CLASS, WM_APP_SHOW};
use crate::theme;
use crate::tray::{self, Tray, TrayEvent, TRAY_CLASS, WM_APP_TRAY};
use crate::win::monitors;
use crate::win::window::{self, Layer};
use crate::{autostart, hotkey, util};

/// Scripting/test hook: `PostMessage(main, WM_APP_CMD, <menu command id>, 0)` applies a menu command.
pub const WM_APP_CMD: u32 = windows::Win32::UI::WindowsAndMessaging::WM_APP + 4;

const ID_TIMER_FAKE: usize = 7;
const ID_TIMER_TEST_HIDE: usize = 8;
const ID_TIMER_SAVE: usize = 9;
const ID_TIMER_RECLAMP: usize = 10;
const ID_TIMER_QUNS: usize = 11;
const ID_TIMER_FIRST_SHOW: usize = 12;
const QUNS_PERIOD_MS: u32 = 2000;

/// Side effects that must run after the `APP` borrow is released (they re-enter the WndProc
/// or run a modal loop).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Action {
    Destroy,
    ShowMenu { x: i32, y: i32 },
    About,
    OpenSettings,
}

/// What a right-click on the card does. Spikes use it as their only input.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RightClick {
    /// Open the settings menu at the cursor (the app).
    Menu,
    Quit,
    CycleBackdrop,
    /// Topmost → Normal → Desktop → click-through on → quit.
    CycleLayers,
}

#[derive(Clone, Debug)]
pub struct AppOptions {
    pub config: Config,
    pub right_click: RightClick,
    /// Feed deterministic fake data every 2 s (development / spikes) instead of sampling.
    pub fake_data: bool,
    /// Create the tray icon and register the hotkey (off for spikes).
    pub tray: bool,
}

impl AppOptions {
    pub fn spike(config: Config, right_click: RightClick) -> Self {
        AppOptions { config, right_click, fake_data: true, tray: false }
    }
}

pub struct App {
    pub hwnd: HWND,
    pub tray_hwnd: HWND,
    pub gfx: Gfx,
    pub text: TextEngine,
    pub styles: Styles,
    pub vm: ViewModel,
    pub cfg: Config,
    pub dpi: u32,
    pub build: u32,
    pub applied: Applied,
    pub click_through: bool,
    pub hover: bool,
    /// Hidden by the user (tray / hotkey / menu); sampling is paused while hidden.
    pub hidden: bool,
    /// Hidden automatically because a fullscreen app is in front (game mode).
    pub game_suppressed: bool,
    /// Waiting for the first snapshot before the first show (avoids a placeholder flash).
    pending_show: bool,
    /// High-contrast theme active: (background, text) system colors.
    pub high_contrast: Option<(D2D1_COLOR_F, D2D1_COLOR_F)>,
    pub sampler: Option<Sampler>,
    pub tray: Option<Tray>,
    pub hotkey_problem: Option<String>,
    pub gpu_source: GpuSource,
    pub opts: AppOptions,
    pub frames: u64,
    pub ticks: u64,
    start: Instant,
    cycle_step: u32,
}

thread_local! {
    static APP: RefCell<Option<App>> = const { RefCell::new(None) };
}

pub fn dip_to_px(dip: f32, dpi: u32) -> i32 {
    (dip * dpi as f32 / 96.0).round() as i32
}

/// Where to put the window at startup: the saved position (rescaled if that monitor's DPI
/// changed, clamped on-screen), else first-run placement. Returns (x, y, dpi).
fn initial_position(cfg: &Config, w_dip: f32, h_dip: f32) -> (i32, i32, u32) {
    if cfg.window.placed {
        let saved = &cfg.window;
        let mon = monitors::by_device(&saved.monitor).or_else(|| {
            let r = RECT { left: saved.x, top: saved.y, right: saved.x + 256, bottom: saved.y + 400 };
            monitors::nearest_to_rect(&r)
        });
        if let Some(m) = mon {
            let (mut x, mut y) = (saved.x, saved.y);
            if m.dpi != saved.dpi && saved.dpi > 0 {
                let k = m.dpi as f32 / saved.dpi as f32;
                x = m.rect.left + ((saved.x - m.rect.left) as f32 * k).round() as i32;
                y = m.rect.top + ((saved.y - m.rect.top) as f32 * k).round() as i32;
            }
            let (w, h) = (dip_to_px(w_dip, m.dpi), dip_to_px(h_dip, m.dpi));
            let (cx, cy) = monitors::clamp_into(&m.work, x, y, w, h);
            return (cx, cy, m.dpi);
        }
    }
    let (_, _, dpi) = monitors::first_run_position(0, 0, 20.0);
    let (w, h) = (dip_to_px(w_dip, dpi), dip_to_px(h_dip, dpi));
    let (x, y, _) = monitors::first_run_position(w, h, 20.0);
    (x, y, dpi)
}

/// Create the windows + app, show it, run the loop. Returns the exit code.
pub fn run(opts: AppOptions) -> Result<i32> {
    window::register_class(MAIN_CLASS, wndproc)?;
    window::register_class(TRAY_CLASS, tray_wndproc)?;
    let build = util::os_build();
    let cfg = opts.config.clone();

    let mut vm = ViewModel::new(cfg.sparklines, cfg.ring_capacity());
    if opts.fake_data {
        vm.ingest(&model::fake_snapshot(0));
    } else {
        vm.ingest(&Snapshot::default());
    }

    let (mut x, mut y, dpi) = initial_position(&cfg, theme::WIDTH, vm.content_height());
    // `PTM2_POS=x,y` (physical px) overrides the position for tests.
    if let Some((ox, oy)) = std::env::var("PTM2_POS").ok().and_then(|v| {
        let (a, b) = v.split_once(',')?;
        Some((a.trim().parse::<i32>().ok()?, b.trim().parse::<i32>().ok()?))
    }) {
        x = ox;
        y = oy;
    }
    let px_w = dip_to_px(theme::WIDTH, dpi);
    let px_h = dip_to_px(vm.content_height(), dpi);

    let hwnd = window::create_popup(MAIN_CLASS, w!("PTMonitor 2"), x, y, px_w, px_h, cfg.layer == Layer::Topmost)?;
    let dpi = window::dpi(hwnd).max(dpi);
    let tray_hwnd = window::create_hidden_owner(TRAY_CLASS, w!("PTMonitor 2 tray"))?;

    let gfx = Gfx::new(hwnd, px_w as u32, px_h as u32, dpi, cfg.renderer == crate::config::Renderer::Warp)?;
    let text = TextEngine::new()?;
    let styles = Styles::new(&text)?;
    crate::logf!(
        "fonts: small='{}' text='{}' icons='{}'; warp={}; dpi={}; size {}x{} at {},{}",
        text.resolved.0, text.resolved.1, text.resolved.2, gfx.warp, dpi, px_w, px_h, x, y
    );

    backdrop::apply_chrome(hwnd);
    let applied = backdrop::apply(hwnd, cfg.backdrop, build);
    crate::logf!("backdrop requested={:?} applied={}", cfg.backdrop, applied.label());
    let _ = gfx.set_opacity(cfg.opacity);

    let app = App {
        hwnd,
        tray_hwnd,
        gfx,
        text,
        styles,
        vm,
        cfg: cfg.clone(),
        dpi,
        build,
        applied,
        click_through: false,
        hover: false,
        hidden: false,
        game_suppressed: false,
        pending_show: false,
        high_contrast: high_contrast(),
        sampler: None,
        tray: None,
        hotkey_problem: None,
        gpu_source: GpuSource::None,
        opts: opts.clone(),
        frames: 0,
        ticks: 0,
        start: Instant::now(),
        cycle_step: 0,
    };
    APP.with(|a| *a.borrow_mut() = Some(app));

    with_app(|app| {
        if app.cfg.window.placed && app.cfg.window.monitor.is_empty() {
            // Imported from v1 (no monitor name): record the monitor we landed on.
            let r = window::window_rect(app.hwnd);
            if let Some(m) = monitors::nearest_to_rect(&r) {
                app.cfg.window.monitor = m.device;
                app.schedule_save();
            }
        }
        if app.high_contrast.is_some() {
            crate::util::log("high-contrast theme active: system-color palette, no material");
        }
        window::set_layer(app.hwnd, app.cfg.layer);
        if app.cfg.click_through {
            app.set_click_through(true);
        }
        app.render();
        if app.opts.tray {
            // SAFETY: plain query.
            let sys_dpi = unsafe { GetDpiForSystem() }.max(96);
            match Tray::new(app.tray_hwnd, sys_dpi) {
                Ok(t) => app.tray = Some(t),
                Err(e) => crate::logf!("tray icon failed: {e}"),
            }
            app.register_hotkey();
            if app.cfg.autostart {
                autostart::sync_path();
            }
        }
        if app.opts.fake_data {
            // SAFETY: timer on our own window.
            unsafe {
                SetTimer(Some(app.hwnd), ID_TIMER_FAKE, 2000, None);
            }
        } else {
            match Sampler::start(
                app.hwnd,
                SamplerConfig {
                    interval_ms: app.cfg.interval_ms,
                    gpu: app.cfg.gpu_source,
                    disks: app.cfg.disks.clone(),
                    net_adapters: app.cfg.net_adapters.clone(),
                },
            ) {
                Ok(s) => app.sampler = Some(s),
                Err(e) => crate::logf!("sampler failed to start: {e}"),
            }
        }
        if app.cfg.start_hidden && app.opts.tray {
            app.hidden = true;
            if let Some(s) = &app.sampler {
                s.pause();
            }
            app.update_tooltip();
            crate::util::log("started hidden");
        } else if app.opts.fake_data {
            window::show(app.hwnd);
            app.reapply_backdrop();
        } else {
            // Show after the first real snapshot (or 1.5 s), so the card never flashes placeholders.
            app.pending_show = true;
            // SAFETY: timer on our own window.
            unsafe {
                SetTimer(Some(app.hwnd), ID_TIMER_FIRST_SHOW, 1500, None);
            }
        }
        if app.cfg.game_mode && app.opts.tray {
            app.start_quns_timer();
        }
        // Test hook: `PTM2_HIDE_AFTER=<secs>` hides the widget (pausing sampling) after N seconds.
        if let Some(secs) = std::env::var("PTM2_HIDE_AFTER").ok().and_then(|v| v.parse::<u32>().ok()) {
            // SAFETY: timer on our own window.
            unsafe {
                SetTimer(Some(app.hwnd), ID_TIMER_TEST_HIDE, secs * 1000, None);
            }
        }
    });

    let code = window::run_message_loop();
    // Drop order: sampler thread stops, tray icon is removed, graphics released.
    APP.with(|a| *a.borrow_mut() = None);
    Ok(code)
}

fn with_app<R>(f: impl FnOnce(&mut App) -> R) -> Option<R> {
    APP.with(|a| a.borrow_mut().as_mut().map(f))
}

impl App {
    fn paint_once(&self) -> Result<()> {
        let (w, h) = self.gfx.size_dip();
        let frame = self.gfx.begin()?;
        let painter = Painter {
            ctx: &self.gfx.ctx,
            factory: &self.gfx.d2d_factory,
            text: &self.text,
            styles: &self.styles,
            scale: self.gfx.scale(),
        };
        painter.draw(&self.vm, w, h, self.applied.is_material(), self.hover && !self.click_through, self.high_contrast)?;
        self.gfx.end(frame)
    }

    pub fn render(&mut self) {
        match self.paint_once() {
            Ok(()) => self.frames += 1,
            Err(e) => {
                crate::logf!("render failed: {e}; recreating graphics");
                self.recreate_gfx();
            }
        }
    }

    fn recreate_gfx(&mut self) {
        match Gfx::new(self.hwnd, self.gfx.width_px, self.gfx.height_px, self.dpi, self.cfg.renderer == crate::config::Renderer::Warp) {
            Ok(g) => {
                self.gfx = g;
                let _ = self.gfx.set_opacity(self.cfg.opacity);
                if let Err(e) = self.paint_once() {
                    crate::logf!("render after recreation failed: {e}");
                } else {
                    self.frames += 1;
                }
            }
            Err(e) => crate::logf!("graphics recreation failed: {e}"),
        }
    }

    /// Resize the window to the view model's height if it changed (e.g. a volume appeared).
    fn fit_height(&mut self) {
        let want_h = dip_to_px(self.vm.content_height(), self.dpi) as u32;
        let want_w = dip_to_px(theme::WIDTH, self.dpi) as u32;
        if want_h != self.gfx.height_px || want_w != self.gfx.width_px {
            let r = window::window_rect(self.hwnd);
            let mon = monitors::nearest_to_rect(&r);
            let (x, y) = match &mon {
                Some(m) => monitors::clamp_into(&m.work, r.left, r.top, want_w as i32, want_h as i32),
                None => (r.left, r.top),
            };
            window::move_resize(self.hwnd, x, y, want_w as i32, want_h as i32);
            if let Err(e) = self.gfx.resize(want_w, want_h, self.dpi) {
                crate::logf!("resize failed: {e}");
                self.recreate_gfx();
            }
        }
    }

    fn update_tooltip(&mut self) {
        let Some(t) = self.tray.as_mut() else { return };
        if self.hidden {
            t.set_tooltip("PTMonitor 2 — hidden (paused)");
            return;
        }
        let row = |name: &str| self.vm.sections.iter().flat_map(|s| s.rows.iter()).find(|r| r.label == name);
        let cpu = row("CPU").map(|r| r.value.clone()).unwrap_or_else(|| "—".into());
        let gpu = row("GPU").map(|r| r.value.clone()).unwrap_or_else(|| "—".into());
        let ram = row("RAM").and_then(|r| r.sub.clone()).unwrap_or_else(|| "—".into());
        let down = row("DOWN").map(|r| r.value.clone()).unwrap_or_else(|| "—".into());
        let up = row("UP").map(|r| r.value.clone()).unwrap_or_else(|| "—".into());
        let tip = format!("PTMonitor 2\nCPU {cpu}  GPU {gpu}\nRAM {ram}\n↓ {down}  ↑ {up}");
        t.set_tooltip(&tip);
    }

    pub fn ingest(&mut self, s: &Snapshot) {
        let mut snap = s.clone();
        if self.cfg.uptime == UptimeMode::App {
            snap.uptime_s = self.start.elapsed().as_secs();
        }
        self.gpu_source = snap.gpu.source;
        let dirty = self.vm.ingest(&snap);
        self.fit_height();
        if dirty {
            self.render();
        }
        self.update_tooltip();
    }

    fn first_show(&mut self) {
        if !self.pending_show {
            return;
        }
        self.pending_show = false;
        // SAFETY: our own timer.
        unsafe {
            let _ = KillTimer(Some(self.hwnd), ID_TIMER_FIRST_SHOW);
        }
        if !self.hidden && !self.game_suppressed {
            window::show(self.hwnd);
            self.reapply_backdrop();
        }
    }

    fn start_quns_timer(&self) {
        // SAFETY: timer on our own window.
        unsafe {
            SetTimer(Some(self.hwnd), ID_TIMER_QUNS, QUNS_PERIOD_MS, None);
        }
    }

    fn stop_quns_timer(&self) {
        // SAFETY: our own timer.
        unsafe {
            let _ = KillTimer(Some(self.hwnd), ID_TIMER_QUNS);
        }
    }

    /// Game mode: hide + pause while a fullscreen app owns the screen; restore afterwards.
    fn check_fullscreen(&mut self) {
        if !self.cfg.game_mode {
            if self.game_suppressed {
                self.set_game_suppressed(false);
            }
            return;
        }
        // SAFETY: plain shell query.
        let busy = match unsafe { SHQueryUserNotificationState() } {
            Ok(s) => s == QUNS_BUSY || s == QUNS_RUNNING_D3D_FULL_SCREEN || s == QUNS_PRESENTATION_MODE,
            Err(_) => false,
        };
        if busy != self.game_suppressed {
            self.set_game_suppressed(busy);
        }
    }

    fn set_game_suppressed(&mut self, on: bool) {
        self.game_suppressed = on;
        if self.hidden {
            return; // the user hid it; nothing to do either way
        }
        if on {
            window::hide(self.hwnd);
            if let Some(s) = &self.sampler {
                s.pause();
            }
            crate::util::log("game mode: fullscreen app in front, widget hidden and sampling paused");
        } else {
            if let Some(s) = &self.sampler {
                s.resume();
            }
            if !self.pending_show {
                window::show(self.hwnd);
                self.reapply_backdrop();
                self.vm.invalidate();
                self.render();
            }
            crate::util::log("game mode: restored");
        }
        self.update_tooltip();
    }

    fn on_power(&mut self, event: usize) {
        match event as u32 {
            PBT_APMSUSPEND => {
                crate::util::log("PBT_APMSUSPEND: pausing");
                if let Some(s) = &self.sampler {
                    s.pause();
                }
                self.stop_quns_timer();
            }
            PBT_APMRESUMEAUTOMATIC | PBT_APMRESUMESUSPEND => {
                crate::util::log("resume: re-baseline, re-clamp, re-apply backdrop");
                if !self.hidden && !self.game_suppressed {
                    if let Some(s) = &self.sampler {
                        s.resume();
                    }
                }
                if self.cfg.game_mode {
                    self.start_quns_timer();
                }
                // SAFETY: timers on our own window.
                unsafe {
                    SetTimer(Some(self.hwnd), ID_TIMER_RECLAMP, 3000, None);
                }
                self.render(); // also a device-health check: a failed Present recreates the device
            }
            _ => {}
        }
    }

    fn refresh_high_contrast(&mut self) {
        let hc = high_contrast();
        if hc.is_some() != self.high_contrast.is_some() {
            crate::logf!("high-contrast theme {}", if hc.is_some() { "on" } else { "off" });
            self.high_contrast = hc;
            self.applied = if hc.is_some() {
                backdrop::apply(self.hwnd, BackdropMode::None, self.build)
            } else {
                backdrop::apply(self.hwnd, self.cfg.backdrop, self.build)
            };
            self.vm.invalidate();
            self.render();
        }
    }

    /// Hide the widget and park the sampler (zero wakeups).
    pub fn hide(&mut self) {
        if self.hidden {
            return;
        }
        self.hidden = true;
        self.hover = false;
        window::hide(self.hwnd);
        if let Some(s) = &self.sampler {
            s.pause();
        }
        self.stop_quns_timer();
        self.update_tooltip();
        crate::util::log("hidden (sampler paused)");
    }

    /// Show the widget: resume sampling (immediate tick), show without activating, re-apply material.
    pub fn show(&mut self) {
        if !self.hidden {
            window::show(self.hwnd);
            return;
        }
        self.hidden = false;
        self.game_suppressed = false;
        if let Some(s) = &self.sampler {
            s.resume();
        }
        window::show(self.hwnd);
        self.reapply_backdrop();
        self.vm.invalidate();
        self.render();
        if self.cfg.game_mode && self.opts.tray {
            self.start_quns_timer();
        }
        self.update_tooltip();
        crate::util::log("shown (sampler resumed)");
    }

    pub fn toggle_visible(&mut self) {
        if self.hidden {
            self.show();
        } else {
            self.hide();
        }
    }

    pub fn reapply_backdrop(&mut self) {
        let before = self.applied;
        self.applied = backdrop::apply(self.hwnd, self.cfg.backdrop, self.build);
        if self.applied != before {
            crate::logf!("backdrop now {}", self.applied.label());
            self.render();
        }
    }

    pub fn set_layer(&mut self, layer: Layer) {
        self.cfg.layer = layer;
        window::set_layer(self.hwnd, layer);
        crate::logf!("layer -> {layer:?}");
    }

    pub fn set_click_through(&mut self, on: bool) {
        self.click_through = on;
        self.cfg.click_through = on;
        self.hover = false;
        window::set_click_through(self.hwnd, on);
        crate::logf!("click-through -> {on}");
        self.render();
    }

    fn register_hotkey(&mut self) {
        hotkey::unregister(self.hwnd);
        self.hotkey_problem = match hotkey::register(self.hwnd, &self.cfg.hotkey) {
            Ok(_) => None,
            Err(e) => {
                crate::logf!("{e}");
                Some(e)
            }
        };
    }

    fn schedule_save(&self) {
        // SAFETY: one-shot debounce timer on our own window.
        unsafe {
            SetTimer(Some(self.hwnd), ID_TIMER_SAVE, 500, None);
        }
    }

    fn save_now(&self) {
        if let Err(e) = self.cfg.save() {
            crate::logf!("settings save failed: {e}");
        }
    }

    fn remember_position(&mut self) {
        let r = window::window_rect(self.hwnd);
        let mon = monitors::nearest_to_rect(&r);
        self.cfg.window.placed = true;
        self.cfg.window.x = r.left;
        self.cfg.window.y = r.top;
        self.cfg.window.monitor = mon.as_ref().map(|m| m.device.clone()).unwrap_or_default();
        self.cfg.window.dpi = self.dpi;
        self.schedule_save();
    }

    /// Move back on-screen if the monitor layout changed under us.
    fn reclamp(&mut self) {
        let r = window::window_rect(self.hwnd);
        if let Some(m) = monitors::nearest_to_rect(&r) {
            let (w, h) = (r.right - r.left, r.bottom - r.top);
            let (x, y) = monitors::clamp_into(&m.work, r.left, r.top, w, h);
            if (x, y) != (r.left, r.top) {
                crate::logf!("reclamp: {},{} -> {},{} on {}", r.left, r.top, x, y, m.device);
                window::move_resize(self.hwnd, x, y, w, h);
            }
        }
        self.reapply_backdrop();
    }

    fn on_dpi_changed(&mut self, wparam: WPARAM, lparam: LPARAM) {
        let dpi = (wparam.0 >> 16) as u32;
        // SAFETY: lParam points to the suggested RECT for the lifetime of the message.
        let r: RECT = unsafe { *(lparam.0 as *const RECT) };
        self.dpi = dpi;
        let w = dip_to_px(theme::WIDTH, dpi);
        let h = dip_to_px(self.vm.content_height(), dpi);
        window::move_resize(self.hwnd, r.left, r.top, w, h);
        if let Err(e) = self.gfx.resize(w as u32, h as u32, dpi) {
            crate::logf!("resize after DPI change failed: {e}");
            self.recreate_gfx();
        }
        crate::logf!("WM_DPICHANGED -> dpi {dpi}, {w}x{h} at {},{}", r.left, r.top);
        self.render();
    }

    /// Screen point → is it over the hover gear?
    fn over_gear(&self, sx: i32, sy: i32) -> bool {
        if self.click_through {
            return false;
        }
        let r = window::window_rect(self.hwnd);
        let scale = self.gfx.scale();
        let (lx, ly) = ((sx - r.left) as f32 / scale, (sy - r.top) as f32 / scale);
        let g = paint::gear_rect(theme::WIDTH);
        lx >= g.left && lx <= g.right && ly >= g.top && ly <= g.bottom
    }

    fn cursor_pos() -> (i32, i32) {
        let mut p = POINT::default();
        // SAFETY: valid out-param.
        unsafe {
            let _ = GetCursorPos(&mut p);
        }
        (p.x, p.y)
    }

    fn cursor_inside(&self) -> bool {
        let (x, y) = Self::cursor_pos();
        let r = window::window_rect(self.hwnd);
        x >= r.left && x < r.right && y >= r.top && y < r.bottom
    }

    fn set_hover(&mut self, on: bool) {
        if self.hover != on {
            self.hover = on;
            self.render();
        }
    }

    fn track_mouse(&self, nonclient: bool) {
        let mut t = TRACKMOUSEEVENT {
            cbSize: std::mem::size_of::<TRACKMOUSEEVENT>() as u32,
            dwFlags: if nonclient { TME_LEAVE | TME_NONCLIENT } else { TME_LEAVE },
            hwndTrack: self.hwnd,
            dwHoverTime: 0,
        };
        // SAFETY: valid struct for our window.
        unsafe {
            let _ = TrackMouseEvent(&mut t);
        }
    }

    fn menu_state_snapshot(&self) -> (Config, bool, Option<String>, String) {
        (self.cfg.clone(), !self.hidden, self.hotkey_problem.clone(), self.applied.label().to_string())
    }

    /// Apply a settings-menu command. May return a follow-up action (modal / destroy).
    pub fn apply(&mut self, cmd: Cmd) -> Option<Action> {
        match cmd {
            Cmd::ToggleVisible => self.toggle_visible(),
            Cmd::Layer(l) => {
                self.set_layer(l);
                self.schedule_save();
            }
            Cmd::Backdrop(m) => {
                self.cfg.backdrop = m;
                self.applied = backdrop::apply(self.hwnd, m, self.build);
                crate::logf!("backdrop {:?} -> {}", m, self.applied.label());
                self.render();
                self.schedule_save();
            }
            Cmd::Opacity(o) => {
                self.cfg.opacity = o;
                let _ = self.gfx.set_opacity(o);
                self.schedule_save();
            }
            Cmd::ClickThrough => {
                let on = !self.click_through;
                self.set_click_through(on);
                self.schedule_save();
            }
            Cmd::Sparklines => {
                self.cfg.sparklines = !self.cfg.sparklines;
                self.vm.sparklines = self.cfg.sparklines;
                self.fit_height();
                self.vm.invalidate();
                self.render();
                self.schedule_save();
            }
            Cmd::GameMode => {
                self.cfg.game_mode = !self.cfg.game_mode;
                if self.cfg.game_mode {
                    self.start_quns_timer();
                } else {
                    self.stop_quns_timer();
                    self.check_fullscreen(); // restores if currently suppressed
                }
                self.schedule_save();
            }
            Cmd::Autostart => {
                let want = !self.cfg.autostart;
                if autostart::set(want) {
                    self.cfg.autostart = want;
                    crate::logf!("autostart -> {want}");
                    self.schedule_save();
                } else {
                    crate::util::log("autostart registry write failed");
                }
            }
            Cmd::StartHidden => {
                self.cfg.start_hidden = !self.cfg.start_hidden;
                self.schedule_save();
            }
            Cmd::OpenSettings => {
                self.save_now();
                return Some(Action::OpenSettings);
            }
            Cmd::ReloadSettings => self.reload_settings(),
            Cmd::About => return Some(Action::About),
            Cmd::Quit => return Some(Action::Destroy),
        }
        None
    }

    fn reload_settings(&mut self) {
        let (cfg, src) = Config::load();
        crate::logf!("reload settings ({src:?})");
        let old = std::mem::replace(&mut self.cfg, cfg);
        if old.layer != self.cfg.layer {
            window::set_layer(self.hwnd, self.cfg.layer);
        }
        if old.backdrop != self.cfg.backdrop {
            self.applied = backdrop::apply(self.hwnd, self.cfg.backdrop, self.build);
        }
        if (old.opacity - self.cfg.opacity).abs() > 0.001 {
            let _ = self.gfx.set_opacity(self.cfg.opacity);
        }
        if old.click_through != self.cfg.click_through {
            let on = self.cfg.click_through;
            self.set_click_through(on);
        }
        if old.hotkey != self.cfg.hotkey && self.opts.tray {
            self.register_hotkey();
        }
        if old.interval_ms != self.cfg.interval_ms {
            if let Some(s) = &self.sampler {
                s.set_interval(self.cfg.interval_ms);
            }
            self.vm.set_ring_capacity(self.cfg.ring_capacity());
        }
        if self.cfg.autostart && !old.autostart {
            let _ = autostart::set(true);
        } else if !self.cfg.autostart && old.autostart {
            let _ = autostart::set(false);
        }
        self.vm.sparklines = self.cfg.sparklines;
        if self.cfg.game_mode && !self.hidden {
            self.start_quns_timer();
        } else {
            self.stop_quns_timer();
            self.check_fullscreen();
        }
        self.fit_height();
        self.vm.invalidate();
        self.render();
    }

    fn about_text(&self) -> String {
        format!(
            "PTMonitor 2  v{}\nWindows build {}\n\nRenderer: {}\nBackdrop: {}\nGPU source: {:?}\nFrames rendered: {}\nSettings: {}",
            env!("CARGO_PKG_VERSION"),
            self.build,
            if self.gfx.warp { "WARP software rasterizer (GPU untouched)" } else { "Direct3D 11 hardware" },
            self.applied.label(),
            self.gpu_source,
            self.frames,
            Config::path().display()
        )
    }

    fn on_right_click(&mut self) -> Option<Action> {
        match self.opts.right_click {
            RightClick::Menu => {
                let (x, y) = Self::cursor_pos();
                Some(Action::ShowMenu { x, y })
            }
            RightClick::Quit => Some(Action::Destroy),
            RightClick::CycleBackdrop => {
                let all = BackdropMode::ALL;
                let idx = all.iter().position(|m| *m == self.cfg.backdrop).unwrap_or(0);
                if idx + 1 >= all.len() {
                    return Some(Action::Destroy); // cycled through everything: quit
                }
                self.cfg.backdrop = all[idx + 1];
                self.applied = backdrop::apply(self.hwnd, self.cfg.backdrop, self.build);
                let msg = format!("backdrop mode {:?} -> applied {}", self.cfg.backdrop, self.applied.label());
                crate::util::log(&msg);
                println!("{msg}");
                self.render();
                None
            }
            RightClick::CycleLayers => {
                self.cycle_step += 1;
                let step = self.cycle_step;
                let msg = match step {
                    1 => { self.set_layer(Layer::Normal); "layer Normal" }
                    2 => { self.set_layer(Layer::Desktop); "layer Desktop (pinned under other windows)" }
                    3 => { self.set_layer(Layer::Topmost); "layer Topmost" }
                    4 => { self.set_click_through(true); "click-through ON (right-click no longer reaches the card; use the tray later)" }
                    _ => { return Some(Action::Destroy); }
                };
                println!("step {step}: {msg}");
                None
            }
        }
    }

    /// Handle one main-window message. Returns the LRESULT (None = DefWindowProc) and an
    /// optional action that the WndProc performs after releasing the `APP` borrow.
    fn handle(&mut self, msg: u32, wparam: WPARAM, lparam: LPARAM) -> (Option<LRESULT>, Option<Action>) {
        let mut action = None;
        let result = match msg {
            WM_NCHITTEST => {
                let (sx, sy) = (lparam.0 as i32 as i16 as i32, (lparam.0 as i32 >> 16) as i16 as i32);
                Some(LRESULT(if self.over_gear(sx, sy) { HTCLIENT } else { HTCAPTION } as isize))
            }
            WM_MOUSEACTIVATE => Some(LRESULT(MA_NOACTIVATE as isize)),
            WM_NCLBUTTONDBLCLK => Some(LRESULT(0)),
            WM_ERASEBKGND => Some(LRESULT(1)),
            WM_PAINT => {
                // SAFETY: our own window.
                unsafe {
                    let _ = ValidateRect(Some(self.hwnd), None);
                }
                Some(LRESULT(0))
            }
            WM_NCMOUSEMOVE | WM_MOUSEMOVE => {
                self.track_mouse(msg == WM_NCMOUSEMOVE);
                self.set_hover(true);
                None
            }
            WM_NCMOUSELEAVE | WM_MOUSELEAVE => {
                if !self.cursor_inside() {
                    self.set_hover(false);
                }
                None
            }
            WM_LBUTTONUP => {
                // Only reachable over the gear (HTCLIENT): open the menu under it.
                let r = window::window_rect(self.hwnd);
                let g = paint::gear_rect(theme::WIDTH);
                let s = self.gfx.scale();
                action = Some(Action::ShowMenu { x: r.left + (g.left * s) as i32, y: r.top + (g.bottom * s) as i32 + 2 });
                Some(LRESULT(0))
            }
            WM_NCRBUTTONUP | WM_RBUTTONUP => {
                action = self.on_right_click();
                Some(LRESULT(0))
            }
            WM_WINDOWPOSCHANGING => {
                if self.cfg.layer == Layer::Desktop {
                    // SAFETY: lParam is a WINDOWPOS for the lifetime of the message.
                    let wp = unsafe { &mut *(lparam.0 as *mut WINDOWPOS) };
                    if wp.flags & SWP_NOZORDER == Default::default() && wp.hwndInsertAfter != HWND_BOTTOM {
                        wp.hwndInsertAfter = HWND_BOTTOM;
                    }
                }
                None
            }
            WM_TIMER if wparam.0 == ID_TIMER_FAKE => {
                self.ticks += 1;
                let s = model::fake_snapshot(self.ticks);
                self.ingest(&s);
                Some(LRESULT(0))
            }
            WM_TIMER if wparam.0 == ID_TIMER_TEST_HIDE => {
                // SAFETY: our own timer.
                unsafe {
                    let _ = KillTimer(Some(self.hwnd), ID_TIMER_TEST_HIDE);
                }
                self.hide();
                Some(LRESULT(0))
            }
            WM_TIMER if wparam.0 == ID_TIMER_SAVE => {
                // SAFETY: our own timer.
                unsafe {
                    let _ = KillTimer(Some(self.hwnd), ID_TIMER_SAVE);
                }
                self.save_now();
                Some(LRESULT(0))
            }
            WM_TIMER if wparam.0 == ID_TIMER_RECLAMP => {
                // SAFETY: our own timer.
                unsafe {
                    let _ = KillTimer(Some(self.hwnd), ID_TIMER_RECLAMP);
                }
                self.reclamp();
                Some(LRESULT(0))
            }
            WM_APP_SNAPSHOT => {
                if let Some(s) = self.sampler.as_ref().map(|s| s.latest()) {
                    self.ticks += 1;
                    if !self.hidden && !self.game_suppressed {
                        self.ingest(&s);
                    }
                    self.first_show();
                }
                Some(LRESULT(0))
            }
            WM_TIMER if wparam.0 == ID_TIMER_FIRST_SHOW => {
                self.first_show();
                Some(LRESULT(0))
            }
            WM_TIMER if wparam.0 == ID_TIMER_QUNS => {
                self.check_fullscreen();
                Some(LRESULT(0))
            }
            WM_POWERBROADCAST => {
                self.on_power(wparam.0);
                Some(LRESULT(1))
            }
            WM_HOTKEY => {
                self.toggle_visible();
                Some(LRESULT(0))
            }
            WM_APP_CMD => {
                if let Some(cmd) = menu::cmd_from_id(wparam.0 as u32) {
                    crate::logf!("WM_APP_CMD {cmd:?}");
                    action = self.apply(cmd);
                }
                Some(LRESULT(0))
            }
            WM_DPICHANGED => {
                self.on_dpi_changed(wparam, lparam);
                Some(LRESULT(0))
            }
            WM_ENTERSIZEMOVE => {
                crate::util::log("WM_ENTERSIZEMOVE (drag start)");
                Some(LRESULT(0))
            }
            WM_EXITSIZEMOVE => {
                let r = window::window_rect(self.hwnd);
                crate::logf!("WM_EXITSIZEMOVE rect {},{} {}x{}", r.left, r.top, r.right - r.left, r.bottom - r.top);
                self.remember_position();
                Some(LRESULT(0))
            }
            WM_DISPLAYCHANGE | WM_SETTINGCHANGE => {
                if msg == WM_SETTINGCHANGE {
                    self.refresh_high_contrast();
                }
                // Coalesce bursts of display / work-area / theme changes into one re-clamp.
                // SAFETY: our own timer.
                unsafe {
                    SetTimer(Some(self.hwnd), ID_TIMER_RECLAMP, 1500, None);
                }
                None
            }
            WM_APP_SHOW => {
                self.show();
                Some(LRESULT(0))
            }
            WM_CLOSE => {
                action = Some(Action::Destroy);
                Some(LRESULT(0))
            }
            _ => None,
        };
        (result, action)
    }

    /// Tray owner window messages.
    fn handle_tray(&mut self, msg: u32, wparam: WPARAM, lparam: LPARAM) -> (Option<LRESULT>, Option<Action>) {
        if msg == WM_APP_TRAY {
            return match tray::decode(wparam, lparam) {
                TrayEvent::Select => {
                    self.toggle_visible();
                    (Some(LRESULT(0)), None)
                }
                TrayEvent::ContextMenu { x, y } => (Some(LRESULT(0)), Some(Action::ShowMenu { x, y })),
                TrayEvent::Other => (Some(LRESULT(0)), None),
            };
        }
        if let Some(t) = self.tray.as_mut() {
            if msg == t.taskbar_created_msg && msg != 0 {
                t.readd();
                return (Some(LRESULT(0)), None);
            }
        }
        (None, None)
    }
}

/// `SPI_GETHIGHCONTRAST` → (COLOR_WINDOW, COLOR_WINDOWTEXT) when a high-contrast theme is on.
fn high_contrast() -> Option<(D2D1_COLOR_F, D2D1_COLOR_F)> {
    let mut hc = HIGHCONTRASTW { cbSize: std::mem::size_of::<HIGHCONTRASTW>() as u32, ..Default::default() };
    // SAFETY: out-param sized for SPI_GETHIGHCONTRAST.
    let ok = unsafe {
        SystemParametersInfoW(
            SPI_GETHIGHCONTRAST,
            hc.cbSize,
            Some(&mut hc as *mut HIGHCONTRASTW as *mut std::ffi::c_void),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        )
        .is_ok()
    };
    if !ok || hc.dwFlags & HCF_HIGHCONTRASTON == Default::default() {
        return None;
    }
    let colorref = |c: u32| D2D1_COLOR_F {
        r: (c & 0xff) as f32 / 255.0,
        g: ((c >> 8) & 0xff) as f32 / 255.0,
        b: ((c >> 16) & 0xff) as f32 / 255.0,
        a: 1.0,
    };
    // SAFETY: plain queries.
    unsafe { Some((colorref(GetSysColor(COLOR_WINDOW)), colorref(GetSysColor(COLOR_WINDOWTEXT)))) }
}

/// Run an action with no `APP` borrow held (may re-enter the WndProc or block in a modal loop).
fn perform(action: Action, main_hwnd: HWND) {
    match action {
        Action::Destroy => {
            // SAFETY: our own window.
            unsafe {
                let _ = DestroyWindow(main_hwnd);
            }
        }
        Action::ShowMenu { x, y } => {
            let Some((cfg, visible, problem, applied, owner)) =
                with_app(|a| { let (c, v, p, ap) = a.menu_state_snapshot(); (c, v, p, ap, a.tray_hwnd) })
            else { return };
            let state = MenuState { cfg: &cfg, visible, hotkey_problem: problem.as_deref(), applied_backdrop: &applied };
            let Ok(hmenu) = menu::build(&state) else { return };
            if let Some(cmd) = menu::show(owner, x, y, hmenu) {
                if let Some(next) = with_app(|a| a.apply(cmd)).flatten() {
                    perform(next, main_hwnd);
                }
            }
        }
        Action::About => {
            let Some((text, owner)) = with_app(|a| (a.about_text(), a.tray_hwnd)) else { return };
            let wtext = util::wide(&text);
            // SAFETY: modal message box owned by the tray window; strings outlive the call.
            unsafe {
                let _ = MessageBoxW(Some(owner), PCWSTR(wtext.as_ptr()), w!("About PTMonitor 2"), MB_OK | MB_ICONINFORMATION);
            }
        }
        Action::OpenSettings => {
            let path = util::wide(&Config::path().to_string_lossy());
            // SAFETY: ShellExecute with a NUL-terminated path.
            unsafe {
                let _ = ShellExecuteW(None, w!("open"), PCWSTR(path.as_ptr()), None, None, SW_SHOWNORMAL);
            }
        }
    }
}

/// Main-window procedure.
///
/// # Safety
/// Called by the system on the UI thread with valid message arguments; `lparam` pointers are
/// only dereferenced for the messages that define them.
pub unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if msg == WM_DESTROY {
        // May arrive re-entrantly (DestroyWindow is synchronous): never borrow mutably here.
        let frames = APP.with(|a| a.try_borrow().ok().and_then(|g| g.as_ref().map(|app| app.frames)));
        crate::logf!("WM_DESTROY (frames rendered: {})", frames.unwrap_or(0));
        hotkey::unregister(hwnd);
        for id in [ID_TIMER_FAKE, ID_TIMER_TEST_HIDE, ID_TIMER_SAVE, ID_TIMER_RECLAMP, ID_TIMER_QUNS, ID_TIMER_FIRST_SHOW] {
            let _ = KillTimer(Some(hwnd), id);
        }
        PostQuitMessage(0);
        return LRESULT(0);
    }
    // Borrow → handle → release, then perform any action that re-enters the WndProc.
    let (handled, action) = APP.with(|a| {
        let mut guard = match a.try_borrow_mut() {
            Ok(g) => g,
            Err(_) => return (None, None), // re-entrant message during a borrow: default handling
        };
        match guard.as_mut() {
            Some(app) if app.hwnd == hwnd => app.handle(msg, wparam, lparam),
            _ => (None, None),
        }
    });
    if let Some(action) = action {
        perform(action, hwnd);
    }
    match handled {
        Some(r) => r,
        None => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// Tray-owner window procedure.
///
/// # Safety
/// Called by the system on the UI thread with valid message arguments.
pub unsafe extern "system" fn tray_wndproc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let (handled, action, main_hwnd) = APP.with(|a| {
        let mut guard = match a.try_borrow_mut() {
            Ok(g) => g,
            Err(_) => return (None, None, HWND::default()),
        };
        match guard.as_mut() {
            Some(app) if app.tray_hwnd == hwnd => {
                let main = app.hwnd;
                let (h, act) = app.handle_tray(msg, wparam, lparam);
                (h, act, main)
            }
            _ => (None, None, HWND::default()),
        }
    });
    if let Some(action) = action {
        perform(action, main_hwnd);
    }
    match handled {
        Some(r) => r,
        None => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
