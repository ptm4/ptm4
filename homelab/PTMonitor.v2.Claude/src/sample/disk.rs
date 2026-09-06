//! Fixed volumes: `GetLogicalDrives` → `DRIVE_FIXED` → `GetDiskFreeSpaceExW` (+ volume label).
//! Called every ~30 s, not every tick.

use windows::core::PCWSTR;
use windows::Win32::Storage::FileSystem::{GetDiskFreeSpaceExW, GetDriveTypeW, GetLogicalDrives, GetVolumeInformationW};
use windows::Win32::System::WindowsProgramming::DRIVE_FIXED;

use crate::model::DiskStat;
use crate::util::{from_wide, wide};

const MIN_BYTES: u64 = 1 << 30; // skip volumes under 1 GiB (recovery, EFI, virtual)

/// `filter`: optional list of drive letters ("C", "E") to show; `None` = all fixed volumes.
pub fn scan(filter: Option<&[String]>) -> Vec<DiskStat> {
    // SAFETY: bitmask query, no pointers.
    let mask = unsafe { GetLogicalDrives() };
    let mut out = Vec::new();
    for i in 0..26u32 {
        if mask & (1 << i) == 0 {
            continue;
        }
        let letter = (b'A' + i as u8) as char;
        if let Some(f) = filter {
            if !f.iter().any(|s| s.trim_end_matches(':').eq_ignore_ascii_case(&letter.to_string())) {
                continue;
            }
        }
        let root = wide(&format!("{letter}:\\"));
        // SAFETY: NUL-terminated root path; valid out-params.
        unsafe {
            if GetDriveTypeW(PCWSTR(root.as_ptr())) != DRIVE_FIXED {
                continue;
            }
            let (mut avail, mut total, mut free) = (0u64, 0u64, 0u64);
            if GetDiskFreeSpaceExW(PCWSTR(root.as_ptr()), Some(&mut avail), Some(&mut total), Some(&mut free)).is_err() {
                continue;
            }
            if total < MIN_BYTES {
                continue;
            }
            let mut name = [0u16; 64];
            let _ = GetVolumeInformationW(PCWSTR(root.as_ptr()), Some(&mut name), None, None, None, None);
            out.push(DiskStat {
                letter: format!("{letter}:"),
                label: from_wide(&name),
                used_bytes: total.saturating_sub(free),
                total_bytes: total,
            });
        }
    }
    out.sort_by(|a, b| a.letter.cmp(&b.letter));
    out
}
