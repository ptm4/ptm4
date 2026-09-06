//! Monitor enumeration and geometry: device names, work areas, DPI, nearest monitor,
//! clamping a window rect on-screen, first-run placement. Physical pixels throughout.

use windows::core::BOOL;
use windows::Win32::Foundation::{LPARAM, POINT, RECT};
use windows::Win32::Graphics::Gdi::{
    EnumDisplayMonitors, GetMonitorInfoW, MonitorFromPoint, MonitorFromRect, HDC, HMONITOR,
    MONITORINFO, MONITORINFOEXW, MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTOPRIMARY,
};
use windows::Win32::UI::HiDpi::{GetDpiForMonitor, MDT_EFFECTIVE_DPI};

use crate::util::from_wide;

#[derive(Clone, Debug, PartialEq)]
pub struct Monitor {
    /// "DISPLAY1" (the `\\.\` prefix stripped).
    pub device: String,
    pub rect: RECT,
    pub work: RECT,
    pub dpi: u32,
    pub primary: bool,
}

fn info(h: HMONITOR) -> Option<Monitor> {
    let mut mi = MONITORINFOEXW::default();
    mi.monitorInfo.cbSize = std::mem::size_of::<MONITORINFOEXW>() as u32;
    // SAFETY: MONITORINFOEXW starts with MONITORINFO; cbSize set accordingly.
    let ok = unsafe { GetMonitorInfoW(h, &mut mi as *mut MONITORINFOEXW as *mut MONITORINFO) };
    if !ok.as_bool() {
        return None;
    }
    let (mut dx, mut dy) = (96u32, 96u32);
    // SAFETY: valid out-params.
    unsafe {
        let _ = GetDpiForMonitor(h, MDT_EFFECTIVE_DPI, &mut dx, &mut dy);
    }
    let device = from_wide(&mi.szDevice).trim_start_matches("\\\\.\\").to_string();
    Some(Monitor {
        device,
        rect: mi.monitorInfo.rcMonitor,
        work: mi.monitorInfo.rcWork,
        dpi: if dx == 0 { 96 } else { dx },
        primary: mi.monitorInfo.dwFlags & 1 == 1, // MONITORINFOF_PRIMARY
    })
}

unsafe extern "system" fn enum_cb(h: HMONITOR, _dc: HDC, _r: *mut RECT, l: LPARAM) -> BOOL {
    // SAFETY: lParam is the Vec we passed below.
    let list = &mut *(l.0 as *mut Vec<Monitor>);
    if let Some(m) = info(h) {
        list.push(m);
    }
    BOOL(1)
}

pub fn all() -> Vec<Monitor> {
    let mut list: Vec<Monitor> = Vec::new();
    // SAFETY: the callback only touches `list`, which outlives the call.
    unsafe {
        let _ = EnumDisplayMonitors(None, None, Some(enum_cb), LPARAM(&mut list as *mut Vec<Monitor> as isize));
    }
    list
}

pub fn primary() -> Option<Monitor> {
    // SAFETY: plain call.
    let h = unsafe { MonitorFromPoint(POINT { x: 0, y: 0 }, MONITOR_DEFAULTTOPRIMARY) };
    info(h)
}

pub fn by_device(device: &str) -> Option<Monitor> {
    all().into_iter().find(|m| m.device.eq_ignore_ascii_case(device))
}

pub fn nearest_to_rect(r: &RECT) -> Option<Monitor> {
    // SAFETY: plain call.
    let h = unsafe { MonitorFromRect(r, MONITOR_DEFAULTTONEAREST) };
    info(h)
}

pub fn nearest_to_point(x: i32, y: i32) -> Option<Monitor> {
    // SAFETY: plain call.
    let h = unsafe { MonitorFromPoint(POINT { x, y }, MONITOR_DEFAULTTONEAREST) };
    info(h)
}

/// Clamp a `w`×`h` window at (`x`,`y`) into `work` (all physical px).
pub fn clamp_into(work: &RECT, x: i32, y: i32, w: i32, h: i32) -> (i32, i32) {
    let max_x = (work.right - w).max(work.left);
    let max_y = (work.bottom - h).max(work.top);
    (x.clamp(work.left, max_x), y.clamp(work.top, max_y))
}

/// Bottom-right of the primary work area with a margin (DIP, scaled by that monitor's DPI).
pub fn first_run_position(w: i32, h: i32, margin_dip: f32) -> (i32, i32, u32) {
    let m = primary().unwrap_or(Monitor {
        device: "DISPLAY1".into(),
        rect: RECT { left: 0, top: 0, right: 1920, bottom: 1080 },
        work: RECT { left: 0, top: 0, right: 1920, bottom: 1040 },
        dpi: 96,
        primary: true,
    });
    let margin = (margin_dip * m.dpi as f32 / 96.0).round() as i32;
    let (x, y) = clamp_into(&m.work, m.work.right - w - margin, m.work.bottom - h - margin, w, h);
    (x, y, m.dpi)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamp() {
        let work = RECT { left: 0, top: 0, right: 2560, bottom: 1392 };
        assert_eq!(clamp_into(&work, 2400, 1300, 256, 308), (2304, 1084));
        assert_eq!(clamp_into(&work, -50, -50, 256, 308), (0, 0));
        assert_eq!(clamp_into(&work, 100, 100, 256, 308), (100, 100));
        // window larger than the work area: pin to top-left
        assert_eq!(clamp_into(&work, 10, 10, 4000, 4000), (0, 0));
    }
}
