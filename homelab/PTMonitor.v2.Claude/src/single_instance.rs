//! One running copy of PTMonitor 2 at a time. A second launch pokes the first
//! (so launching the shortcut while hidden reveals the widget) and exits.

use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS, HANDLE, LPARAM, WPARAM};
use windows::Win32::System::Threading::CreateMutexW;
use windows::Win32::UI::WindowsAndMessaging::{FindWindowW, PostMessageW, WM_APP};

/// Window class of the main widget window (also used by `FindWindowW` here).
pub const MAIN_CLASS: PCWSTR = w!("PTMonitor2.Main");
/// Posted to the main window by a second instance: show + bring the widget back.
pub const WM_APP_SHOW: u32 = WM_APP + 3;

const MUTEX_NAME: PCWSTR = w!("Local\\PTMonitor2.SingleInstance");

/// Held for the process lifetime; the mutex is released when the process exits.
pub struct InstanceGuard {
    _handle: HANDLE,
}

pub enum Instance {
    Primary(InstanceGuard),
    Secondary,
}

pub fn acquire() -> Instance {
    // SAFETY: CreateMutexW with no security attributes; the handle is kept alive by the guard.
    unsafe {
        match CreateMutexW(None, false, MUTEX_NAME) {
            Ok(handle) => {
                if GetLastError() == ERROR_ALREADY_EXISTS {
                    Instance::Secondary
                } else {
                    Instance::Primary(InstanceGuard { _handle: handle })
                }
            }
            // Could not create a mutex at all: run anyway rather than refuse to start.
            Err(_) => Instance::Primary(InstanceGuard {
                _handle: HANDLE::default(),
            }),
        }
    }
}

/// Ask the already-running instance to show itself. Silent if it has no window yet.
pub fn notify_primary() {
    // SAFETY: FindWindowW/PostMessageW take no pointers we own.
    unsafe {
        if let Ok(hwnd) = FindWindowW(MAIN_CLASS, PCWSTR::null()) {
            let _ = PostMessageW(Some(hwnd), WM_APP_SHOW, WPARAM(0), LPARAM(0));
        }
    }
}
