//! Sampler thread: owns every metric source, ticks on a waitable event (so pause costs zero
//! wakeups), publishes a [`Snapshot`] and posts `WM_APP_SNAPSHOT` to the UI thread.

pub mod cpu_mem;
pub mod disk;
pub mod gpu_nvml;
pub mod gpu_pdh;
pub mod net;

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use windows::core::Result;
use windows::Win32::Foundation::{CloseHandle, HANDLE, HWND, LPARAM, WPARAM};
use windows::Win32::System::Threading::{CreateEventW, SetEvent, WaitForSingleObject, INFINITE};
use windows::Win32::UI::WindowsAndMessaging::{PostMessageW, WM_APP};

use crate::model::{GpuSource, GpuStat, Snapshot};

/// Posted to the main window after each published snapshot.
pub const WM_APP_SNAPSHOT: u32 = WM_APP + 1;

const DISK_EVERY_TICKS: u64 = 15;

/// Config `gpu_source`.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GpuPref {
    #[default]
    Auto,
    Nvml,
    Pdh,
    Off,
}

#[derive(Clone, Debug, Default)]
pub struct SamplerConfig {
    pub interval_ms: u32,
    pub gpu: GpuPref,
    pub disks: Option<Vec<String>>,
    pub net_adapters: Option<Vec<String>>,
}

struct SendHandle(HANDLE);
unsafe impl Send for SendHandle {}
unsafe impl Sync for SendHandle {}

struct SendHwnd(HWND);
unsafe impl Send for SendHwnd {}

struct Shared {
    snapshot: Mutex<Snapshot>,
    paused: AtomicBool,
    stop: AtomicBool,
    interval_ms: AtomicU32,
    wake: SendHandle,
}

pub struct Sampler {
    shared: Arc<Shared>,
    thread: Option<std::thread::JoinHandle<()>>,
}

enum Gpu {
    Nvml(gpu_nvml::Nvml),
    Pdh(gpu_pdh::Pdh),
    None,
}

impl Gpu {
    fn init(pref: GpuPref) -> Gpu {
        match pref {
            GpuPref::Off => Gpu::None,
            GpuPref::Nvml => gpu_nvml::Nvml::init().map(Gpu::Nvml).unwrap_or(Gpu::None),
            GpuPref::Pdh => gpu_pdh::Pdh::init().map(Gpu::Pdh).unwrap_or(Gpu::None),
            GpuPref::Auto => match gpu_nvml::Nvml::init() {
                Some(n) => Gpu::Nvml(n),
                None => gpu_pdh::Pdh::init().map(Gpu::Pdh).unwrap_or(Gpu::None),
            },
        }
    }

    fn label(&self) -> String {
        match self {
            Gpu::Nvml(n) => format!("NVML ({})", n.name),
            Gpu::Pdh(_) => "PDH GPU Engine counters".into(),
            Gpu::None => "none".into(),
        }
    }

    fn sample(&mut self) -> GpuStat {
        match self {
            Gpu::Nvml(n) => match n.sample() {
                Some(s) => s,
                None => {
                    if n.failures >= 3 {
                        crate::util::log("NVML failed 3 times; switching to PDH");
                        *self = gpu_pdh::Pdh::init().map(Gpu::Pdh).unwrap_or(Gpu::None);
                    }
                    GpuStat { source: GpuSource::Nvml, ..Default::default() }
                }
            },
            Gpu::Pdh(p) => p.sample().unwrap_or(GpuStat { source: GpuSource::Pdh, ..Default::default() }),
            Gpu::None => GpuStat::default(),
        }
    }
}

impl Sampler {
    pub fn start(hwnd: HWND, cfg: SamplerConfig) -> Result<Sampler> {
        // SAFETY: auto-reset, initially unsignaled, unnamed event.
        let wake = unsafe { CreateEventW(None, false, false, None)? };
        let shared = Arc::new(Shared {
            snapshot: Mutex::new(Snapshot::default()),
            paused: AtomicBool::new(false),
            stop: AtomicBool::new(false),
            interval_ms: AtomicU32::new(cfg.interval_ms.clamp(500, 60_000)),
            wake: SendHandle(wake),
        });
        let s2 = shared.clone();
        let hwnd = SendHwnd(hwnd);
        let thread = std::thread::Builder::new()
            .name("ptmonitor2-sampler".into())
            .spawn(move || run_loop(s2, hwnd, cfg))
            .expect("spawn sampler thread");
        Ok(Sampler { shared, thread: Some(thread) })
    }

    pub fn latest(&self) -> Snapshot {
        self.shared.snapshot.lock().unwrap_or_else(|p| p.into_inner()).clone()
    }

    fn wake(&self) {
        // SAFETY: valid event handle owned by `shared`.
        unsafe {
            let _ = SetEvent(self.shared.wake.0);
        }
    }

    /// Park the thread (zero wakeups) — used while the widget is hidden.
    pub fn pause(&self) {
        self.shared.paused.store(true, Ordering::SeqCst);
        self.wake();
    }

    /// Resume with an immediate tick; rates re-baseline (they show carried-forward values once).
    pub fn resume(&self) {
        self.shared.paused.store(false, Ordering::SeqCst);
        self.wake();
    }

    pub fn is_paused(&self) -> bool {
        self.shared.paused.load(Ordering::SeqCst)
    }

    pub fn set_interval(&self, ms: u32) {
        self.shared.interval_ms.store(ms.clamp(500, 60_000), Ordering::SeqCst);
        self.wake();
    }
}

impl Drop for Sampler {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::SeqCst);
        self.wake();
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
        // SAFETY: the thread has exited; nobody else uses the event.
        unsafe {
            let _ = CloseHandle(self.shared.wake.0);
        }
    }
}

fn run_loop(shared: Arc<Shared>, hwnd: SendHwnd, cfg: SamplerConfig) {
    let mut cpu = cpu_mem::Cpu::default();
    let mut net = net::Net::new(cfg.net_adapters.clone());
    let mut gpu = Gpu::init(cfg.gpu);
    crate::logf!("sampler: gpu source = {}", gpu.label());
    let mut disks = disk::scan(cfg.disks.as_deref());
    let mut tick: u64 = 0;
    let mut seq: u64 = 0;
    let mut last = Instant::now();
    let mut first = true;

    loop {
        if !first {
            let interval = shared.interval_ms.load(Ordering::SeqCst);
            // SAFETY: valid event handle.
            unsafe {
                let _ = WaitForSingleObject(shared.wake.0, interval);
            }
        }
        first = false;
        if shared.stop.load(Ordering::SeqCst) {
            break;
        }
        if shared.paused.load(Ordering::SeqCst) {
            // SAFETY: valid event handle; sleeps with zero wakeups until resume/stop.
            unsafe {
                let _ = WaitForSingleObject(shared.wake.0, INFINITE);
            }
            if shared.stop.load(Ordering::SeqCst) {
                break;
            }
            if shared.paused.load(Ordering::SeqCst) {
                continue; // spurious wake (interval change) while paused
            }
            cpu.reset();
            net.reset();
            last = Instant::now();
            disks = disk::scan(cfg.disks.as_deref());
        }

        let now = Instant::now();
        let elapsed = now.duration_since(last).as_secs_f64();
        last = now;
        let interval_s = shared.interval_ms.load(Ordering::SeqCst) as f64 / 1000.0;
        if elapsed > 3.0 * interval_s && tick > 0 {
            // Implicit resume (Modern Standby, missed power event): re-baseline.
            crate::logf!("sampler: gap of {elapsed:.1}s, re-baselining");
            cpu.reset();
            net.reset();
            disks = disk::scan(cfg.disks.as_deref());
        }

        let mut ok = true;
        let cpu_pct = match cpu.sample() {
            Ok(v) => v,
            Err(_) => {
                ok = false;
                None
            }
        };
        let (ram_used, ram_total) = cpu_mem::memory().unwrap_or_else(|| {
            ok = false;
            (0, 0)
        });
        let n = match net.sample(elapsed) {
            Ok(n) => n,
            Err(_) => {
                ok = false;
                net::NetSample { rx_bps: None, tx_bps: None, link_bps: None }
            }
        };
        if tick > 0 && tick.is_multiple_of(DISK_EVERY_TICKS) {
            disks = disk::scan(cfg.disks.as_deref());
        }
        let gpu_stat = gpu.sample();
        seq += 1;
        let snap = Snapshot {
            seq,
            ok,
            cpu_pct,
            ram_used,
            ram_total,
            gpu: gpu_stat,
            disks: disks.clone(),
            net_rx_bps: n.rx_bps,
            net_tx_bps: n.tx_bps,
            net_link_bps: n.link_bps,
            uptime_s: cpu_mem::uptime_s(),
        };
        *shared.snapshot.lock().unwrap_or_else(|p| p.into_inner()) = snap;
        // SAFETY: posting to the UI thread's window; harmless if it is gone.
        unsafe {
            let _ = PostMessageW(Some(hwnd.0), WM_APP_SNAPSHOT, WPARAM(0), LPARAM(0));
        }
        tick += 1;
    }
    crate::util::log("sampler: stopped");
}
