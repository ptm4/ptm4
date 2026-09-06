//! Notification-area icon (Shell_NotifyIconW, NOTIFYICON_VERSION_4) owned by a real invisible
//! top-level window (never `HWND_MESSAGE`: the menu-dismiss pattern needs foreground rights).
//! Re-adds itself after an Explorer restart (`TaskbarCreated`). Tooltip updates only when the
//! text changes.

use windows::core::{w, Result, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::HiDpi::GetSystemMetricsForDpi;
use windows::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_SHOWTIP, NIF_TIP, NIM_ADD, NIM_DELETE, NIM_MODIFY,
    NIM_SETVERSION, NIN_SELECT, NOTIFYICONDATAW, NOTIFYICON_VERSION_4,
};
use windows::Win32::UI::WindowsAndMessaging::{
    DestroyIcon, LoadImageW, RegisterWindowMessageW, HICON, IMAGE_ICON, LR_DEFAULTCOLOR, SM_CXSMICON,
    WM_APP, WM_CONTEXTMENU, WM_LBUTTONDBLCLK, WM_LBUTTONUP,
};

/// Callback message for the icon (received by the tray owner window).
pub const WM_APP_TRAY: u32 = WM_APP + 2;
pub const TRAY_CLASS: PCWSTR = w!("PTMonitor2.Tray");
const ICON_RESOURCE_ID: u16 = 1;
/// `NIN_SELECT | NINF_KEY` — keyboard selection of the icon.
const NIN_KEYSELECT: u32 = NIN_SELECT | 0x1;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TrayEvent {
    /// Left click / keyboard select: toggle the widget.
    Select,
    /// Right click / Shift+F10: open the settings menu at the anchor point (screen px).
    ContextMenu { x: i32, y: i32 },
    Other,
}

/// Decode a v4 callback: LOWORD(lParam) = event, wParam = anchor (x = LOWORD, y = HIWORD).
pub fn decode(wparam: WPARAM, lparam: LPARAM) -> TrayEvent {
    let event = (lparam.0 as u32) & 0xFFFF;
    let x = (wparam.0 & 0xFFFF) as u16 as i16 as i32;
    let y = ((wparam.0 >> 16) & 0xFFFF) as u16 as i16 as i32;
    match event {
        NIN_SELECT | NIN_KEYSELECT | WM_LBUTTONUP | WM_LBUTTONDBLCLK => TrayEvent::Select,
        WM_CONTEXTMENU => TrayEvent::ContextMenu { x, y },
        _ => TrayEvent::Other,
    }
}

pub fn load_icon(dpi: u32) -> Option<HICON> {
    // SAFETY: loads the embedded icon resource at the small-icon size for this DPI.
    unsafe {
        let hinst = GetModuleHandleW(None).ok()?;
        let cx = GetSystemMetricsForDpi(SM_CXSMICON, dpi).max(16);
        let h = LoadImageW(Some(hinst.into()), PCWSTR(ICON_RESOURCE_ID as usize as *const u16), IMAGE_ICON, cx, cx, LR_DEFAULTCOLOR).ok()?;
        Some(HICON(h.0))
    }
}

pub struct Tray {
    nid: NOTIFYICONDATAW,
    icon: HICON,
    tip: String,
    /// `RegisterWindowMessageW("TaskbarCreated")` — Explorer restarted, re-add the icon.
    pub taskbar_created_msg: u32,
    added: bool,
}

impl Tray {
    pub fn new(owner: HWND, dpi: u32) -> Result<Tray> {
        let icon = load_icon(dpi).unwrap_or_default();
        let mut nid = NOTIFYICONDATAW {
            cbSize: std::mem::size_of::<NOTIFYICONDATAW>() as u32,
            hWnd: owner,
            uID: 1,
            uFlags: NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP,
            uCallbackMessage: WM_APP_TRAY,
            hIcon: icon,
            ..Default::default()
        };
        nid.Anonymous.uVersion = NOTIFYICON_VERSION_4;
        // SAFETY: registering a well-known broadcast message name.
        let taskbar_created_msg = unsafe { RegisterWindowMessageW(w!("TaskbarCreated")) };
        let mut t = Tray { nid, icon, tip: String::new(), taskbar_created_msg, added: false };
        t.set_tip_text("PTMonitor 2");
        let ok = t.add();
        crate::logf!("tray: icon added ok={ok} (icon handle valid={})", !icon.is_invalid());
        Ok(t)
    }

    fn set_tip_text(&mut self, text: &str) {
        let mut buf = [0u16; 128];
        for (i, u) in text.encode_utf16().take(127).enumerate() {
            buf[i] = u;
        }
        self.nid.szTip = buf;
        self.tip = text.to_string();
    }

    fn add(&mut self) -> bool {
        // SAFETY: fully initialized NOTIFYICONDATAW.
        unsafe {
            let ok = Shell_NotifyIconW(NIM_ADD, &self.nid).as_bool();
            if ok {
                let _ = Shell_NotifyIconW(NIM_SETVERSION, &self.nid);
            }
            self.added = ok;
            ok
        }
    }

    /// After `TaskbarCreated`: add again (fails harmlessly if the icon still exists).
    pub fn readd(&mut self) {
        let ok = self.add();
        crate::logf!("tray: re-added after TaskbarCreated (ok={ok})");
    }

    /// Live-stats tooltip (max 127 chars). Only calls the shell when the text changed.
    pub fn set_tooltip(&mut self, text: &str) {
        if text == self.tip {
            return;
        }
        self.set_tip_text(text);
        // SAFETY: modify with NIF_TIP set in uFlags.
        unsafe {
            let _ = Shell_NotifyIconW(NIM_MODIFY, &self.nid);
        }
    }

    pub fn remove(&mut self) {
        if self.added {
            // SAFETY: deleting our own icon.
            unsafe {
                let _ = Shell_NotifyIconW(NIM_DELETE, &self.nid);
            }
            self.added = false;
        }
    }
}

impl Drop for Tray {
    fn drop(&mut self) {
        self.remove();
        if !self.icon.is_invalid() {
            // SAFETY: icon we loaded.
            unsafe {
                let _ = DestroyIcon(self.icon);
            }
        }
    }
}
