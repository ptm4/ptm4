//! Global hotkey: parse `[Ctrl+][Alt+][Shift+][Win+]<A-Z|0-9|F1-F12>` and register it on the
//! main window. `RegisterHotKey` is exclusive system-wide, so a conflict is reported, not fatal.

use windows::Win32::Foundation::HWND;
use windows::Win32::UI::Input::KeyboardAndMouse::{
    RegisterHotKey, UnregisterHotKey, HOT_KEY_MODIFIERS, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN,
};

pub const HOTKEY_ID: i32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Spec {
    pub mods: HOT_KEY_MODIFIERS,
    pub vk: u32,
}

/// `None` for an empty string (hotkey disabled) or an unparsable one.
pub fn parse(s: &str) -> Option<Spec> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    let mut mods = HOT_KEY_MODIFIERS(0);
    let mut vk = None;
    for part in s.split('+') {
        let p = part.trim();
        match p.to_ascii_lowercase().as_str() {
            "ctrl" | "control" => mods |= MOD_CONTROL,
            "alt" => mods |= MOD_ALT,
            "shift" => mods |= MOD_SHIFT,
            "win" | "windows" | "super" => mods |= MOD_WIN,
            key => {
                let k = key.to_ascii_uppercase();
                let code = if k.len() == 1 && (k.as_bytes()[0].is_ascii_uppercase() || k.as_bytes()[0].is_ascii_digit()) {
                    k.as_bytes()[0] as u32
                } else if let Some(n) = k.strip_prefix('F').and_then(|n| n.parse::<u32>().ok()).filter(|n| (1..=24).contains(n)) {
                    0x70 + n - 1
                } else {
                    return None;
                };
                if vk.replace(code).is_some() {
                    return None; // two keys
                }
            }
        }
    }
    let vk = vk?;
    if mods.0 == 0 {
        return None; // refuse to grab an unmodified key system-wide
    }
    Some(Spec { mods, vk })
}

/// Human form for the menu, e.g. "Ctrl+Alt+P".
pub fn display(s: &str) -> String {
    match parse(s) {
        Some(spec) => {
            let mut parts = Vec::new();
            if spec.mods.0 & MOD_CONTROL.0 != 0 {
                parts.push("Ctrl".to_string());
            }
            if spec.mods.0 & MOD_ALT.0 != 0 {
                parts.push("Alt".to_string());
            }
            if spec.mods.0 & MOD_SHIFT.0 != 0 {
                parts.push("Shift".to_string());
            }
            if spec.mods.0 & MOD_WIN.0 != 0 {
                parts.push("Win".to_string());
            }
            let key = if (0x70..=0x87).contains(&spec.vk) { format!("F{}", spec.vk - 0x70 + 1) } else { (spec.vk as u8 as char).to_string() };
            parts.push(key);
            parts.join("+")
        }
        None => String::new(),
    }
}

/// Register on `hwnd`; `Err` carries a user-facing reason.
pub fn register(hwnd: HWND, s: &str) -> Result<Option<Spec>, String> {
    let Some(spec) = parse(s) else {
        return if s.trim().is_empty() { Ok(None) } else { Err(format!("hotkey '{s}' is not valid")) };
    };
    // SAFETY: our own window.
    unsafe {
        RegisterHotKey(Some(hwnd), HOTKEY_ID, spec.mods | MOD_NOREPEAT, spec.vk)
            .map_err(|e| format!("hotkey '{}' is taken by another app ({e})", display(s)))?;
    }
    Ok(Some(spec))
}

pub fn unregister(hwnd: HWND) {
    // SAFETY: our own window.
    unsafe {
        let _ = UnregisterHotKey(Some(hwnd), HOTKEY_ID);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses() {
        let p = parse("Ctrl+Alt+P").unwrap();
        assert_eq!(p.vk, 'P' as u32);
        assert_eq!(p.mods.0, (MOD_CONTROL | MOD_ALT).0);
        assert_eq!(parse("ctrl + shift + f5").unwrap().vk, 0x74);
        assert_eq!(parse("Win+1").unwrap().vk, '1' as u32);
        assert!(parse("").is_none());
        assert!(parse("P").is_none(), "unmodified keys are refused");
        assert!(parse("Ctrl+Alt+P+Q").is_none());
        assert!(parse("Ctrl+Foo").is_none());
        assert_eq!(display("ctrl+alt+p"), "Ctrl+Alt+P");
        assert_eq!(display("shift+f12"), "Shift+F12");
    }
}
