//! NVIDIA telemetry without a child process: `nvml.dll` loaded by name, symbols resolved with
//! `GetProcAddress`, a hand-declared C ABI. Every call returns `Option`; the sampler switches
//! to the PDH fallback after repeated failures.

use std::ffi::c_void;

use windows::core::{s, w};
use windows::Win32::Foundation::{FreeLibrary, HMODULE};
use windows::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};

use crate::model::{GpuSource, GpuStat};

#[repr(C)]
#[derive(Default)]
struct Utilization {
    gpu: u32,
    memory: u32,
}

#[repr(C)]
#[derive(Default)]
struct Memory {
    total: u64,
    free: u64,
    used: u64,
}

type FnInit = unsafe extern "C" fn() -> u32;
type FnShutdown = unsafe extern "C" fn() -> u32;
type FnHandle = unsafe extern "C" fn(u32, *mut *mut c_void) -> u32;
type FnUtil = unsafe extern "C" fn(*mut c_void, *mut Utilization) -> u32;
type FnMem = unsafe extern "C" fn(*mut c_void, *mut Memory) -> u32;
type FnTemp = unsafe extern "C" fn(*mut c_void, u32, *mut u32) -> u32;
type FnPower = unsafe extern "C" fn(*mut c_void, *mut u32) -> u32;
type FnName = unsafe extern "C" fn(*mut c_void, *mut u8, u32) -> u32;

pub struct Nvml {
    lib: HMODULE,
    shutdown: FnShutdown,
    util: FnUtil,
    mem: FnMem,
    temp: FnTemp,
    power: FnPower,
    dev: *mut c_void,
    pub name: String,
    pub failures: u32,
}

// The device handle is only used from the sampler thread that created it.
unsafe impl Send for Nvml {}

macro_rules! sym {
    ($lib:expr, $name:literal, $t:ty) => {{
        // SAFETY: symbol lookup by name; the transmute matches the documented NVML C signature.
        let p = unsafe { GetProcAddress($lib, s!($name)) }?;
        unsafe { std::mem::transmute::<unsafe extern "system" fn() -> isize, $t>(p) }
    }};
}

impl Nvml {
    /// Load nvml.dll and open device 0. `None` when there is no NVIDIA driver.
    pub fn init() -> Option<Nvml> {
        // SAFETY: standard DLL search order; nvml.dll ships in System32 with the NVIDIA driver.
        let lib = unsafe { LoadLibraryW(w!("nvml.dll")) }.ok()?;
        let init: FnInit = sym!(lib, "nvmlInit_v2", FnInit);
        let shutdown: FnShutdown = sym!(lib, "nvmlShutdown", FnShutdown);
        let handle: FnHandle = sym!(lib, "nvmlDeviceGetHandleByIndex_v2", FnHandle);
        let util: FnUtil = sym!(lib, "nvmlDeviceGetUtilizationRates", FnUtil);
        let mem: FnMem = sym!(lib, "nvmlDeviceGetMemoryInfo", FnMem);
        let temp: FnTemp = sym!(lib, "nvmlDeviceGetTemperature", FnTemp);
        let power: FnPower = sym!(lib, "nvmlDeviceGetPowerUsage", FnPower);
        let name_fn: Option<FnName> = unsafe { GetProcAddress(lib, s!("nvmlDeviceGetName")) }
            .map(|p| unsafe { std::mem::transmute::<unsafe extern "system" fn() -> isize, FnName>(p) });
        // SAFETY: NVML C calls with valid out-params.
        unsafe {
            if init() != 0 {
                let _ = FreeLibrary(lib);
                return None;
            }
            let mut dev: *mut c_void = std::ptr::null_mut();
            if handle(0, &mut dev) != 0 || dev.is_null() {
                let _ = shutdown();
                let _ = FreeLibrary(lib);
                return None;
            }
            let mut name = String::from("NVIDIA GPU");
            if let Some(f) = name_fn {
                let mut buf = [0u8; 96];
                if f(dev, buf.as_mut_ptr(), buf.len() as u32) == 0 {
                    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
                    name = String::from_utf8_lossy(&buf[..end]).to_string();
                }
            }
            Some(Nvml { lib, shutdown, util, mem, temp, power, dev, name, failures: 0 })
        }
    }

    pub fn sample(&mut self) -> Option<GpuStat> {
        let mut u = Utilization::default();
        // SAFETY: NVML C calls with valid out-params on the device handle we own.
        unsafe {
            if (self.util)(self.dev, &mut u) != 0 {
                self.failures += 1;
                return None;
            }
            self.failures = 0;
            let mut m = Memory::default();
            let mem_ok = (self.mem)(self.dev, &mut m) == 0;
            let mut t = 0u32;
            let temp_ok = (self.temp)(self.dev, 0, &mut t) == 0;
            let mut p = 0u32;
            let power_ok = (self.power)(self.dev, &mut p) == 0;
            Some(GpuStat {
                source: GpuSource::Nvml,
                util_pct: Some(u.gpu as f32),
                vram_used: mem_ok.then_some(m.used),
                vram_total: mem_ok.then_some(m.total),
                temp_c: temp_ok.then_some(t),
                power_w: power_ok.then_some(p as f32 / 1000.0),
            })
        }
    }
}

impl Drop for Nvml {
    fn drop(&mut self) {
        // SAFETY: matching shutdown + unload.
        unsafe {
            let _ = (self.shutdown)();
            let _ = FreeLibrary(self.lib);
        }
    }
}
