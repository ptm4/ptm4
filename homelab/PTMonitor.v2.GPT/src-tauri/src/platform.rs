//! Elevation is only invoked by an explicit, confirmed user action.
use std::os::windows::ffi::OsStrExt;
use windows_sys::Win32::{
    Foundation::CloseHandle,
    System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE},
    UI::{
        Shell::{ShellExecuteExW, SEE_MASK_NOCLOSEPROCESS, SHELLEXECUTEINFOW},
        WindowsAndMessaging::SW_SHOWNORMAL,
    },
};

pub fn wait_for_handoff() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).is_some_and(|s| s == "--elevated-handoff") {
        if let Some(pid) = args.get(2).and_then(|s| s.parse::<u32>().ok()) {
            unsafe {
                let handle = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
                if !handle.is_null() {
                    WaitForSingleObject(handle, 15_000);
                    CloseHandle(handle);
                }
            }
        }
    }
}

pub fn launch_elevated() -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let file: Vec<u16> = exe.as_os_str().encode_wide().chain(Some(0)).collect();
    let verb: Vec<u16> = "runas\0".encode_utf16().collect();
    let args: Vec<u16> = format!("--elevated-handoff {}\0", std::process::id())
        .encode_utf16()
        .collect();
    unsafe {
        let mut info: SHELLEXECUTEINFOW = std::mem::zeroed();
        info.cbSize = std::mem::size_of::<SHELLEXECUTEINFOW>() as u32;
        info.fMask = SEE_MASK_NOCLOSEPROCESS;
        info.lpVerb = verb.as_ptr();
        info.lpFile = file.as_ptr();
        info.lpParameters = args.as_ptr();
        info.nShow = SW_SHOWNORMAL;
        if ShellExecuteExW(&mut info) == 0 {
            return Err(format!(
                "Administrator restart cancelled or unavailable: {}",
                std::io::Error::last_os_error()
            ));
        }
        if !info.hProcess.is_null() {
            CloseHandle(info.hProcess);
        }
    }
    Ok(())
}
