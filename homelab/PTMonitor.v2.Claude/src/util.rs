//! Small shared helpers: wide strings, app paths, an append-only log, panic hook.

use std::ffi::OsStr;
use std::io::Write;
use std::os::windows::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::Mutex;

use windows::Win32::System::SystemInformation::GetLocalTime;

/// NUL-terminated UTF-16 for Win32 `PCWSTR` parameters.
pub fn wide(s: &str) -> Vec<u16> {
    OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect()
}

/// UTF-16 buffer (NUL-terminated or not) to `String`.
pub fn from_wide(buf: &[u16]) -> String {
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

pub fn local_app_data() -> PathBuf {
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// `%LOCALAPPDATA%\PTMonitor2` — settings and log. Never the legacy `PTMonitor` folder.
pub fn app_dir() -> PathBuf {
    local_app_data().join("PTMonitor2")
}

const LOG_CAP_BYTES: u64 = 256 * 1024;
static LOG: Mutex<Option<std::fs::File>> = Mutex::new(None);

fn timestamp() -> String {
    // SAFETY: GetLocalTime has no pointer parameters.
    let t = unsafe { GetLocalTime() };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond
    )
}

/// Local time as `YYYY-MM-DDTHH:MM:SS` (config stamps).
pub fn iso_now() -> String {
    timestamp().replacen(' ', "T", 1)
}

/// Append one line to `%LOCALAPPDATA%\PTMonitor2\ptmonitor2.log` (rotated once at 256 KB).
/// Lifecycle and errors only — never per tick.
pub fn log(msg: &str) {
    if cfg!(test) {
        return; // unit tests must not write into the user's log
    }
    let mut guard = LOG.lock().unwrap_or_else(|p| p.into_inner());
    if guard.is_none() {
        let dir = app_dir();
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("ptmonitor2.log");
        if let Ok(meta) = std::fs::metadata(&path) {
            if meta.len() > LOG_CAP_BYTES {
                let _ = std::fs::rename(&path, dir.join("ptmonitor2.log.old"));
            }
        }
        *guard = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .ok();
    }
    if let Some(f) = guard.as_mut() {
        let _ = writeln!(f, "{} {}", timestamp(), msg);
    }
}

#[macro_export]
macro_rules! logf {
    ($($arg:tt)*) => { $crate::util::log(&format!($($arg)*)) };
}

/// Write the panic message to the log before `panic = "abort"` terminates the process.
pub fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        log(&format!("PANIC: {info}"));
    }));
}

/// Windows build number from the registry (e.g. 26200); 0 if unavailable.
pub fn os_build() -> u32 {
    use windows::core::w;
    use windows::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY, HKEY_LOCAL_MACHINE, KEY_READ,
    };
    let mut key = HKEY::default();
    // SAFETY: plain registry reads into a bounded buffer.
    unsafe {
        if RegOpenKeyExW(
            HKEY_LOCAL_MACHINE,
            w!("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"),
            None,
            KEY_READ,
            &mut key,
        )
        .is_err()
        {
            return 0;
        }
        let mut buf = [0u16; 32];
        let mut len = (buf.len() * 2) as u32;
        let ok = RegQueryValueExW(
            key,
            w!("CurrentBuildNumber"),
            None,
            None,
            Some(buf.as_mut_ptr() as *mut u8),
            Some(&mut len),
        )
        .is_ok();
        let _ = RegCloseKey(key);
        if !ok {
            return 0;
        }
        from_wide(&buf).trim().parse().unwrap_or(0)
    }
}
