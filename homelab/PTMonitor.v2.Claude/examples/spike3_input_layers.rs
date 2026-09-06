//! Spike 3 — drag, hit-test, layers, click-through, with live fake data and sparklines.
//!
//! Right-click steps: Normal layer → Desktop (pinned under windows) → Topmost → click-through
//! on → quit. Drag the card by any point; hover the header to reveal the gear; click it.
//! Pass: the OS move loop moves the window (no Snap Layouts, no maximize on top-edge drop),
//! WM_EXITSIZEMOVE fires once per drag with physical coordinates, the desktop layer stays
//! under newly focused windows, click-through lets clicks fall through to what is behind.

use ptmonitor2::app::{self, AppOptions, RightClick};
use ptmonitor2::config::Config;
use ptmonitor2::gfx::backdrop::BackdropMode;
use windows::Win32::UI::HiDpi::{SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2};

fn main() {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    println!("spike3: fake data every 2 s with sparklines; right-click cycles Normal → Desktop → Topmost → click-through → quit.");
    match app::run(AppOptions::spike(Config { backdrop: BackdropMode::Auto, ..Default::default() }, RightClick::CycleLayers)) {
        Ok(code) => println!("exit {code}"),
        Err(e) => eprintln!("FAILED: {e}"),
    }
}
