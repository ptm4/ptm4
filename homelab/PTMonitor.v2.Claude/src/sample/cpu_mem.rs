//! CPU % from `GetSystemTimes` deltas, RAM from `GlobalMemoryStatusEx`, uptime from `GetTickCount64`.

use windows::Win32::Foundation::FILETIME;
use windows::Win32::System::SystemInformation::{GetTickCount64, GlobalMemoryStatusEx, MEMORYSTATUSEX};
use windows::Win32::System::Threading::GetSystemTimes;

fn ft(f: FILETIME) -> u64 {
    ((f.dwHighDateTime as u64) << 32) | f.dwLowDateTime as u64
}

/// A Win32 sampling call failed.
#[derive(Debug, Clone, Copy)]
pub struct SampleError;

#[derive(Default)]
pub struct Cpu {
    /// (idle, total) at the previous sample.
    prev: Option<(u64, u64)>,
}

impl Cpu {
    /// Forget the baseline (after resume / a long gap) so the next sample reports `None`.
    pub fn reset(&mut self) {
        self.prev = None;
    }

    /// `Err` when the call fails; `Ok(None)` on the first sample after a reset.
    pub fn sample(&mut self) -> Result<Option<f32>, SampleError> {
        let (mut idle, mut kernel, mut user) = (FILETIME::default(), FILETIME::default(), FILETIME::default());
        // SAFETY: valid out-params.
        unsafe {
            GetSystemTimes(Some(&mut idle), Some(&mut kernel), Some(&mut user)).map_err(|_| SampleError)?;
        }
        let idle = ft(idle);
        let total = ft(kernel) + ft(user); // kernel time includes idle time
        let out = match self.prev {
            Some((pi, pt)) if total > pt => {
                let busy = (total - pt).saturating_sub(idle - pi) as f64;
                Some((busy / (total - pt) as f64 * 100.0).clamp(0.0, 100.0) as f32)
            }
            _ => None,
        };
        self.prev = Some((idle, total));
        Ok(out)
    }
}

/// (used bytes, total bytes)
pub fn memory() -> Option<(u64, u64)> {
    let mut m = MEMORYSTATUSEX { dwLength: std::mem::size_of::<MEMORYSTATUSEX>() as u32, ..Default::default() };
    // SAFETY: dwLength set; valid out-param.
    unsafe {
        GlobalMemoryStatusEx(&mut m).ok()?;
    }
    Some((m.ullTotalPhys.saturating_sub(m.ullAvailPhys), m.ullTotalPhys))
}

pub fn uptime_s() -> u64 {
    // SAFETY: no arguments.
    unsafe { GetTickCount64() / 1000 }
}
