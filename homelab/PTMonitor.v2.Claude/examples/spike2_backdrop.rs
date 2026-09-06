//! Spike 2 — backdrop material behind a NOACTIVATE DirectComposition popup.
//!
//! Starts in `Auto`; each right-click advances Auto → Acrylic → Mica → Blur → None and prints
//! what was actually applied; a right-click on None quits. Keep another app focused and a busy
//! wallpaper/window behind the card. Pass: at least one mode visibly blurs what is behind,
//! clipped to the rounded corners, and survives idle / hide-show / drag.

use ptmonitor2::app::{self, AppOptions, RightClick};
use ptmonitor2::config::Config;
use ptmonitor2::gfx::backdrop::BackdropMode;
use windows::Win32::UI::HiDpi::{SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2};

fn main() {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    println!("spike2: right-click cycles backdrop modes (Auto, Acrylic, Mica, Blur, None); last click quits.");
    println!("transparency effects enabled in Settings: {}", ptmonitor2::gfx::backdrop::transparency_enabled());
    match app::run(AppOptions::spike(Config { backdrop: BackdropMode::Auto, ..Default::default() }, RightClick::CycleBackdrop)) {
        Ok(code) => println!("exit {code}"),
        Err(e) => eprintln!("FAILED: {e}"),
    }
}
