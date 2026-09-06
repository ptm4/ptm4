//! PTMonitor 2 — native Win32 / Direct2D system-monitor widget for Windows 11.
//!
//! Library crate so the main binary, the icon generator and the spike examples
//! share one implementation. Module layout follows the approved plan.

pub mod app;
pub mod config;
pub mod autostart;
pub mod gfx;
pub mod menu;
pub mod hotkey;
pub mod model;
pub mod sample;
pub mod single_instance;
pub mod theme;
pub mod tray;
pub mod util;
pub mod win;
