use serde::Serialize;
use std::sync::Mutex;
use std::time::Instant;
use sysinfo::{Disks, Networks, System};

#[derive(Serialize, Clone)]
pub struct DiskStat {
    pub label: String,
    pub used_gb: f64,
    pub total_gb: f64,
    pub pct: f64,
}

#[derive(Serialize, Clone)]
pub struct Stats {
    pub cpu_pct: f64,
    pub ram_used_gb: f64,
    pub ram_total_gb: f64,
    pub ram_pct: f64,
    pub net_rx_mbps: f64,
    pub net_tx_mbps: f64,
    pub disks: Vec<DiskStat>,
    pub gpu_pct: f64,
}

pub struct AppState {
    sys: System,
    networks: Networks,
    last_tick: Instant,
    prev_rx: u64,
    prev_tx: u64,
}

static GPU_USAGE: Mutex<f64> = Mutex::new(0.0);

// Polls GPU via Windows Performance Counters in a background thread every 4s.
// PowerShell startup cost is ~400ms so we run it off the UI path.
pub fn start_gpu_poll() {
    std::thread::spawn(|| loop {
        if let Some(v) = query_gpu() {
            *GPU_USAGE.lock().unwrap() = v.min(100.0);
        }
        std::thread::sleep(std::time::Duration::from_secs(4));
    });
}

fn query_gpu() -> Option<f64> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let out = std::process::Command::new("powershell")
        .creation_flags(CREATE_NO_WINDOW)
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum",
        ])
        .output()
        .ok()?;
    String::from_utf8(out.stdout).ok()?.trim().parse::<f64>().ok()
}

impl AppState {
    pub fn new() -> Self {
        let sys = System::new_all();
        let networks = Networks::new_with_refreshed_list();
        let (prev_rx, prev_tx) = net_totals(&networks);
        AppState { sys, networks, last_tick: Instant::now(), prev_rx, prev_tx }
    }
}

fn net_totals(networks: &Networks) -> (u64, u64) {
    networks
        .iter()
        .fold((0, 0), |(rx, tx), (_, d)| (rx + d.total_received(), tx + d.total_transmitted()))
}

fn all_disks() -> Vec<DiskStat> {
    let disks = Disks::new_with_refreshed_list();
    let mut result: Vec<DiskStat> = disks
        .iter()
        .filter(|d| d.total_space() > 1_073_741_824) // skip drives < 1 GB (virtual/CD)
        .map(|d| {
            let label = d.mount_point()
                .to_str()
                .and_then(|s| s.split(':').next())
                .unwrap_or("?")
                .to_uppercase();
            let total_gb = d.total_space() as f64 / 1_073_741_824.0;
            let avail_gb = d.available_space() as f64 / 1_073_741_824.0;
            let used_gb = (total_gb - avail_gb).max(0.0);
            let pct = if total_gb > 0.0 { used_gb / total_gb * 100.0 } else { 0.0 };
            DiskStat { label, used_gb, total_gb, pct }
        })
        .collect();
    result.sort_by(|a, b| a.label.cmp(&b.label));
    result
}

#[tauri::command]
pub fn get_stats(state: tauri::State<'_, std::sync::Mutex<AppState>>) -> Stats {
    let mut s = state.lock().unwrap();

    s.sys.refresh_cpu_all();
    s.sys.refresh_memory();
    s.networks.refresh(false);

    let elapsed = s.last_tick.elapsed().as_secs_f64().max(0.001);
    let (rx, tx) = net_totals(&s.networks);

    let net_rx_mbps = rx.saturating_sub(s.prev_rx) as f64 / elapsed / 1_048_576.0;
    let net_tx_mbps = tx.saturating_sub(s.prev_tx) as f64 / elapsed / 1_048_576.0;

    s.prev_rx = rx;
    s.prev_tx = tx;
    s.last_tick = Instant::now();

    let ram_used = s.sys.used_memory();
    let ram_total = s.sys.total_memory();

    Stats {
        cpu_pct: s.sys.global_cpu_usage() as f64,
        ram_used_gb: ram_used as f64 / 1_073_741_824.0,
        ram_total_gb: ram_total as f64 / 1_073_741_824.0,
        ram_pct: if ram_total > 0 { ram_used as f64 / ram_total as f64 * 100.0 } else { 0.0 },
        net_rx_mbps,
        net_tx_mbps,
        disks: all_disks(),
        gpu_pct: *GPU_USAGE.lock().unwrap(),
    }
}
