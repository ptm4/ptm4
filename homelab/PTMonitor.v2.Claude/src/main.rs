#![windows_subsystem = "windows"]
//! PTMonitor 2 entry point.

use ptmonitor2::app::{self, AppOptions, RightClick};
use ptmonitor2::config::{Config, LoadSource};
use ptmonitor2::{single_instance, util};
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};

fn main() {
    // Belt and braces with app.manifest: per-monitor DPI v2 before any window exists.
    // SAFETY: no pointers involved.
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }

    let _guard = match single_instance::acquire() {
        single_instance::Instance::Secondary => {
            single_instance::notify_primary();
            return;
        }
        single_instance::Instance::Primary(guard) => guard,
    };

    util::install_panic_hook();
    ptmonitor2::logf!(
        "start ptmonitor2 {} (windows build {})",
        env!("CARGO_PKG_VERSION"),
        util::os_build()
    );

    let (config, source) = Config::load();
    ptmonitor2::logf!("settings: {:?} from {}", source, Config::path().display());
    if matches!(source, LoadSource::ImportedV1 | LoadSource::Defaults | LoadSource::CorruptReset) {
        // Persist immediately so a v1 import never repeats and the file exists for "Open settings".
        if let Err(e) = config.save() {
            ptmonitor2::logf!("initial settings save failed: {e}");
        }
        if source == LoadSource::ImportedV1 {
            util::log("imported legacy PTMonitor settings (autostart left off; enable it from the menu when retiring v1)");
        }
    }

    let code = app::run(AppOptions { config, right_click: RightClick::Menu, fake_data: false, tray: true });
    match code {
        Ok(c) => ptmonitor2::logf!("exit {c}"),
        Err(e) => ptmonitor2::logf!("fatal: {e}"),
    }
}
