//! Windows 11 chrome and backdrop material for an undecorated DirectComposition popup:
//! DWM rounded corners, no system border, dark immersive mode, and Acrylic/Mica via
//! `DWMWA_SYSTEMBACKDROP_TYPE` with the undocumented `SetWindowCompositionAttribute`
//! blur as a fallback (constants as used by window-vibrancy 0.6.0).

use std::ffi::c_void;

use windows::core::{s, w, BOOL};
use windows::Win32::Foundation::HWND;
use windows::Win32::Graphics::Dwm::{
    DwmExtendFrameIntoClientArea, DwmSetWindowAttribute, DWMSBT_MAINWINDOW, DWMSBT_NONE,
    DWMSBT_TRANSIENTWINDOW, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE, DWMWA_SYSTEMBACKDROP_TYPE,
    DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND,
    DWMWINDOWATTRIBUTE, DWM_SYSTEMBACKDROP_TYPE,
};
use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows::Win32::UI::Controls::MARGINS;

/// User preference (config `backdrop`).
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BackdropMode {
    #[default]
    Auto,
    Acrylic,
    Mica,
    Blur,
    None,
}

impl BackdropMode {
    pub const ALL: [BackdropMode; 5] = [
        BackdropMode::Auto,
        BackdropMode::Acrylic,
        BackdropMode::Mica,
        BackdropMode::Blur,
        BackdropMode::None,
    ];
    pub fn label(self) -> &'static str {
        match self {
            BackdropMode::Auto => "Auto",
            BackdropMode::Acrylic => "Acrylic",
            BackdropMode::Mica => "Mica",
            BackdropMode::Blur => "Blur (legacy)",
            BackdropMode::None => "None (flat glass)",
        }
    }
}

/// What actually got applied.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Applied {
    Acrylic,
    Mica,
    SwcaAcrylic,
    SwcaBlur,
    None,
}

impl Applied {
    /// True when a translucent material is behind the card, so the card fill should be lighter.
    pub fn is_material(self) -> bool {
        !matches!(self, Applied::None)
    }
    pub fn label(self) -> &'static str {
        match self {
            Applied::Acrylic => "Acrylic (DWM)",
            Applied::Mica => "Mica (DWM)",
            Applied::SwcaAcrylic => "Acrylic (SWCA)",
            Applied::SwcaBlur => "Blur (SWCA)",
            Applied::None => "none",
        }
    }
}

const BUILD_SYSTEMBACKDROP: u32 = 22523; // DWMWA_SYSTEMBACKDROP_TYPE
const BUILD_MICA_EFFECT: u32 = 22000; // undocumented DWMWA_MICA_EFFECT (1029)
const BUILD_SWCA: u32 = 17763; // SetWindowCompositionAttribute acrylic
const DWMWA_MICA_EFFECT: DWMWINDOWATTRIBUTE = DWMWINDOWATTRIBUTE(1029);

/// `HKCU\...\Themes\Personalize\EnableTransparency` — when off, DWM ignores backdrops anyway.
pub fn transparency_enabled() -> bool {
    use windows::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY, HKEY_CURRENT_USER, KEY_READ,
    };
    let mut key = HKEY::default();
    // SAFETY: bounded registry read.
    unsafe {
        if RegOpenKeyExW(
            HKEY_CURRENT_USER,
            w!("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"),
            None,
            KEY_READ,
            &mut key,
        )
        .is_err()
        {
            return true;
        }
        let mut value = 1u32;
        let mut len = 4u32;
        let ok = RegQueryValueExW(
            key,
            w!("EnableTransparency"),
            None,
            None,
            Some(&mut value as *mut u32 as *mut u8),
            Some(&mut len),
        )
        .is_ok();
        let _ = RegCloseKey(key);
        !ok || value != 0
    }
}

unsafe fn dwm_set<T>(hwnd: HWND, attr: DWMWINDOWATTRIBUTE, value: &T) -> bool {
    DwmSetWindowAttribute(
        hwnd,
        attr,
        value as *const T as *const c_void,
        std::mem::size_of::<T>() as u32,
    )
    .is_ok()
}

/// Rounded corners, no system border, dark mode. Call once after creating the window.
pub fn apply_chrome(hwnd: HWND) {
    // SAFETY: attribute writes with correctly sized values.
    unsafe {
        let _ = dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, &DWMWCP_ROUND);
        let _ = dwm_set(hwnd, DWMWA_BORDER_COLOR, &DWMWA_COLOR_NONE);
        let _ = dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &BOOL(1));
    }
}

#[repr(C)]
struct AccentPolicy {
    accent_state: u32,
    accent_flags: u32,
    gradient_color: u32,
    animation_id: u32,
}

#[repr(C)]
struct WindowCompositionAttribData {
    attrib: u32,
    data: *mut c_void,
    size: usize,
}

const ACCENT_DISABLED: u32 = 0;
const ACCENT_ENABLE_BLURBEHIND: u32 = 3;
const ACCENT_ENABLE_ACRYLICBLURBEHIND: u32 = 4;
const WCA_ACCENT_POLICY: u32 = 0x13;
/// ABGR tint used with SWCA acrylic/blur: alpha 0x99 over rgb(10,12,20).
const SWCA_TINT_ABGR: u32 = 0x9914_0c0a;

type SwcaFn = unsafe extern "system" fn(HWND, *mut WindowCompositionAttribData) -> BOOL;

fn swca() -> Option<SwcaFn> {
    // SAFETY: GetProcAddress on an always-loaded system module; the signature matches the
    // undocumented export used by many shells.
    unsafe {
        let user32 = GetModuleHandleW(w!("user32.dll")).ok()?;
        let p = GetProcAddress(user32, s!("SetWindowCompositionAttribute"))?;
        Some(std::mem::transmute::<unsafe extern "system" fn() -> isize, SwcaFn>(p))
    }
}

fn set_accent(hwnd: HWND, state: u32) -> bool {
    let Some(f) = swca() else { return false };
    let mut policy = AccentPolicy {
        accent_state: state,
        accent_flags: if state == ACCENT_ENABLE_ACRYLICBLURBEHIND { 0 } else { 2 },
        gradient_color: if state == ACCENT_DISABLED { 0 } else { SWCA_TINT_ABGR },
        animation_id: 0,
    };
    let mut data = WindowCompositionAttribData {
        attrib: WCA_ACCENT_POLICY,
        data: &mut policy as *mut AccentPolicy as *mut c_void,
        size: std::mem::size_of::<AccentPolicy>(),
    };
    // SAFETY: both structs outlive the call.
    unsafe { f(hwnd, &mut data).as_bool() }
}

unsafe fn set_dwm_backdrop(hwnd: HWND, kind: DWM_SYSTEMBACKDROP_TYPE) -> bool {
    let margins = MARGINS { cxLeftWidth: -1, cxRightWidth: -1, cyTopHeight: -1, cyBottomHeight: -1 };
    let _ = DwmExtendFrameIntoClientArea(hwnd, &margins);
    dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &kind)
}

/// Remove any material.
pub fn clear(hwnd: HWND, build: u32) {
    // SAFETY: attribute writes only.
    unsafe {
        if build >= BUILD_SYSTEMBACKDROP {
            let _ = dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_NONE);
        } else if build >= BUILD_MICA_EFFECT {
            let _ = dwm_set(hwnd, DWMWA_MICA_EFFECT, &BOOL(0));
        }
    }
    let _ = set_accent(hwnd, ACCENT_DISABLED);
}

/// Apply `mode` (re-entrant: clears first). Returns what is actually in effect.
pub fn apply(hwnd: HWND, mode: BackdropMode, build: u32) -> Applied {
    clear(hwnd, build);
    if !transparency_enabled() {
        return Applied::None;
    }
    let order: &[Applied] = match mode {
        BackdropMode::None => &[],
        BackdropMode::Auto | BackdropMode::Acrylic => &[Applied::Acrylic, Applied::SwcaAcrylic],
        BackdropMode::Mica => &[Applied::Mica],
        BackdropMode::Blur => &[Applied::SwcaBlur],
    };
    for &candidate in order {
        // SAFETY: attribute writes only.
        let ok = unsafe {
            match candidate {
                Applied::Acrylic => build >= BUILD_SYSTEMBACKDROP && set_dwm_backdrop(hwnd, DWMSBT_TRANSIENTWINDOW),
                Applied::Mica => {
                    if build >= BUILD_SYSTEMBACKDROP {
                        set_dwm_backdrop(hwnd, DWMSBT_MAINWINDOW)
                    } else if build >= BUILD_MICA_EFFECT {
                        dwm_set(hwnd, DWMWA_MICA_EFFECT, &BOOL(1))
                    } else {
                        false
                    }
                }
                Applied::SwcaAcrylic => build >= BUILD_SWCA && set_accent(hwnd, ACCENT_ENABLE_ACRYLICBLURBEHIND),
                Applied::SwcaBlur => set_accent(hwnd, ACCENT_ENABLE_BLURBEHIND),
                Applied::None => false,
            }
        };
        if ok {
            return candidate;
        }
    }
    Applied::None
}
