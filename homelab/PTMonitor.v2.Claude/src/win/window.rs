//! Win32 popup window helpers: class registration, creation with the widget's extended
//! styles, z-order layer, click-through, show/hide, DPI, work area, message loop.

use std::ffi::c_void;

use windows::core::{Result, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows::Win32::Graphics::Gdi::HBRUSH;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::HiDpi::GetDpiForWindow;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DispatchMessageW, GetMessageW, GetWindowLongPtrW, GetWindowRect,
    LoadCursorW, RegisterClassExW, SetWindowLongPtrW, SetWindowPos, ShowWindow,
    SystemParametersInfoW, TranslateMessage, GWL_EXSTYLE, HWND_BOTTOM, HWND_NOTOPMOST,
    HWND_TOPMOST, IDC_ARROW, MSG, SPI_GETWORKAREA, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE,
    SWP_NOSIZE, SWP_NOZORDER, SW_HIDE, SW_SHOWNOACTIVATE, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS,
    WINDOW_EX_STYLE, WNDCLASSEXW, WS_EX_NOACTIVATE, WS_EX_NOREDIRECTIONBITMAP, WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
};

pub type WndProc = unsafe extern "system" fn(HWND, u32, WPARAM, LPARAM) -> LRESULT;

/// Z-order layer (config `layer`).
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Layer {
    #[default]
    Topmost,
    Normal,
    Desktop,
}

pub fn register_class(class: PCWSTR, wndproc: WndProc) -> Result<()> {
    // SAFETY: the struct is fully initialized; strings are static.
    unsafe {
        let hinstance = GetModuleHandleW(None)?;
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            style: Default::default(),
            lpfnWndProc: Some(wndproc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: hinstance.into(),
            hIcon: Default::default(),
            hCursor: LoadCursorW(None, IDC_ARROW)?,
            hbrBackground: HBRUSH::default(),
            lpszMenuName: PCWSTR::null(),
            lpszClassName: class,
            hIconSm: Default::default(),
        };
        if RegisterClassExW(&wc) == 0 {
            return Err(windows::core::Error::from_win32());
        }
    }
    Ok(())
}

/// Create the (hidden) widget popup. `x, y, w, h` are device pixels.
pub fn create_popup(class: PCWSTR, title: PCWSTR, x: i32, y: i32, w: i32, h: i32, topmost: bool) -> Result<HWND> {
    let mut ex = WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
    if topmost {
        ex |= WS_EX_TOPMOST;
    }
    // SAFETY: valid class/strings; no lpParam.
    unsafe {
        let hinstance = GetModuleHandleW(None)?;
        CreateWindowExW(ex, class, title, WS_POPUP, x, y, w, h, None, None, Some(hinstance.into()), None)
    }
}

/// Create a 0×0 invisible top-level owner window (tray/menu owner). Not `HWND_MESSAGE`-parented,
/// because a message-only window can never become the foreground window.
pub fn create_hidden_owner(class: PCWSTR, title: PCWSTR) -> Result<HWND> {
    // SAFETY: as above.
    unsafe {
        let hinstance = GetModuleHandleW(None)?;
        CreateWindowExW(WS_EX_TOOLWINDOW, class, title, WS_POPUP, 0, 0, 0, 0, None, None, Some(hinstance.into()), None)
    }
}

pub fn show(hwnd: HWND) {
    // SAFETY: plain window call.
    unsafe {
        let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    }
}

pub fn hide(hwnd: HWND) {
    // SAFETY: plain window call.
    unsafe {
        let _ = ShowWindow(hwnd, SW_HIDE);
    }
}

pub fn dpi(hwnd: HWND) -> u32 {
    // SAFETY: plain window call.
    let d = unsafe { GetDpiForWindow(hwnd) };
    if d == 0 {
        96
    } else {
        d
    }
}

pub fn window_rect(hwnd: HWND) -> RECT {
    let mut r = RECT::default();
    // SAFETY: valid out-param.
    unsafe {
        let _ = GetWindowRect(hwnd, &mut r);
    }
    r
}

/// Primary monitor work area (excludes the taskbar), physical pixels.
pub fn primary_work_area() -> RECT {
    let mut r = RECT::default();
    // SAFETY: valid out-param sized for SPI_GETWORKAREA.
    unsafe {
        let _ = SystemParametersInfoW(
            SPI_GETWORKAREA,
            0,
            Some(&mut r as *mut RECT as *mut c_void),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        );
    }
    r
}

pub fn move_resize(hwnd: HWND, x: i32, y: i32, w: i32, h: i32) {
    // SAFETY: plain window call.
    unsafe {
        let _ = SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
    }
}

pub fn set_layer(hwnd: HWND, layer: Layer) {
    let after = match layer {
        Layer::Topmost => HWND_TOPMOST,
        Layer::Normal => HWND_NOTOPMOST,
        Layer::Desktop => HWND_NOTOPMOST,
    };
    // SAFETY: plain window calls.
    unsafe {
        let _ = SetWindowPos(hwnd, Some(after), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        if layer == Layer::Desktop {
            let _ = SetWindowPos(hwnd, Some(HWND_BOTTOM), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }
    }
}

pub fn set_click_through(hwnd: HWND, on: bool) {
    // SAFETY: style read-modify-write on our own window.
    unsafe {
        let ex = WINDOW_EX_STYLE(GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32);
        let ex = if on { ex | WS_EX_TRANSPARENT } else { WINDOW_EX_STYLE(ex.0 & !WS_EX_TRANSPARENT.0) };
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex.0 as isize);
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        );
    }
}

/// Standard message loop; returns the `WM_QUIT` exit code.
pub fn run_message_loop() -> i32 {
    let mut msg = MSG::default();
    // SAFETY: standard loop with a valid MSG.
    unsafe {
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    msg.wParam.0 as i32
}
