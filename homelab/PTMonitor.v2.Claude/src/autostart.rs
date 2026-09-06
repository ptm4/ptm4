//! Launch on startup via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value
//! `PTMonitor2` = `"<current exe>"` (quoted). Never touches v1's `PTMonitor` value.

use windows::core::{w, PCWSTR};
use windows::Win32::System::Registry::{
    RegCloseKey, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW, HKEY,
    HKEY_CURRENT_USER, KEY_QUERY_VALUE, KEY_SET_VALUE, REG_SZ,
};

use crate::util::{from_wide, wide};

const RUN_KEY: PCWSTR = w!("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run");
const VALUE: PCWSTR = w!("PTMonitor2");

fn open(rights: windows::Win32::System::Registry::REG_SAM_FLAGS) -> Option<HKEY> {
    let mut key = HKEY::default();
    // SAFETY: opening a well-known key.
    if unsafe { RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, None, rights, &mut key) }.is_err() {
        return None;
    }
    Some(key)
}

fn quoted_exe() -> Option<String> {
    let exe = std::env::current_exe().ok()?;
    Some(format!("\"{}\"", exe.to_string_lossy()))
}

/// The stored command line, if the value exists.
pub fn current_value() -> Option<String> {
    let key = open(KEY_QUERY_VALUE)?;
    let mut buf = [0u16; 1024];
    let mut len = (buf.len() * 2) as u32;
    // SAFETY: bounded read.
    let ok = unsafe {
        RegQueryValueExW(key, VALUE, None, None, Some(buf.as_mut_ptr() as *mut u8), Some(&mut len)).is_ok()
    };
    // SAFETY: closing our handle.
    unsafe {
        let _ = RegCloseKey(key);
    }
    ok.then(|| from_wide(&buf))
}

pub fn is_enabled() -> bool {
    current_value().is_some()
}

/// Enable/disable. Returns false if the registry write failed.
pub fn set(enable: bool) -> bool {
    let Some(key) = open(KEY_SET_VALUE) else { return false };
    let ok = if enable {
        let Some(cmd) = quoted_exe() else { return false };
        let data = wide(&cmd);
        // SAFETY: REG_SZ with the NUL-terminated wide string (byte length incl. NUL).
        unsafe {
            RegSetValueExW(
                key,
                VALUE,
                None,
                REG_SZ,
                Some(std::slice::from_raw_parts(data.as_ptr() as *const u8, data.len() * 2)),
            )
            .is_ok()
        }
    } else {
        // SAFETY: deleting our own value; "not found" counts as success.
        unsafe { RegDeleteValueW(key, VALUE).is_ok() || current_value().is_none() }
    };
    // SAFETY: closing our handle.
    unsafe {
        let _ = RegCloseKey(key);
    }
    ok
}

/// If autostart is on but the exe moved, rewrite the value so it keeps working.
pub fn sync_path() {
    if let (Some(cur), Some(want)) = (current_value(), quoted_exe()) {
        if !cur.eq_ignore_ascii_case(&want) {
            crate::logf!("autostart path changed: {cur} -> {want}");
            let _ = set(true);
        }
    }
}
