//! Spike 1 — composition window + DirectWrite text over the desktop.
//!
//! Pass: wallpaper visible through the rounded corners and the card; text crisp at 100% and
//! 150% DPI; no black/white rectangle; WM_DPICHANGED handled when dragged across monitors.
//! Right-click the card to quit. Events are echoed to the log and this console.

use ptmonitor2::app::{self, AppOptions, RightClick};
use ptmonitor2::config::Config;
use ptmonitor2::gfx::backdrop::BackdropMode;
use windows::Win32::UI::HiDpi::{SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2};

fn main() {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    println!("spike1: flat glass card, no backdrop material. Drag it around; right-click to quit.");
    println!("log: {}", ptmonitor2::util::app_dir().join("ptmonitor2.log").display());
    match app::run(AppOptions::spike(Config { backdrop: BackdropMode::None, ..Default::default() }, RightClick::Quit)) {
        Ok(code) => println!("exit {code}"),
        Err(e) => eprintln!("FAILED: {e}"),
    }
}
