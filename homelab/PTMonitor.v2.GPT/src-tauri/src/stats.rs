pub use crate::alerts::Alert;
use crate::{
    alerts::AlertEngine,
    config::Config,
    pdh::PdhGauge,
    sensor::{self, SensorBridge, SensorReading, SensorStatus},
};
use serde::Serialize;
use std::{
    cmp::Ordering,
    collections::{HashMap, VecDeque},
    sync::{
        atomic::{AtomicBool, Ordering as AtomicOrdering},
        Arc, Mutex, RwLock,
    },
    thread::{self, Thread},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use sysinfo::{ProcessRefreshKind, ProcessesToUpdate, System};
use tauri::{AppHandle, Emitter, Manager};
use windows_sys::Win32::NetworkManagement::{
    IpHelper::{FreeMibTable, GetIfTable2, IF_TYPE_SOFTWARE_LOOPBACK, MIB_IF_TABLE2},
    Ndis::IfOperStatusUp,
};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, GetDiskFreeSpaceExW, GetDriveTypeW, GetLogicalDrives, FILE_SHARE_READ,
    FILE_SHARE_WRITE, OPEN_EXISTING,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, INVALID_HANDLE_VALUE},
    System::{
        Ioctl::{DISK_EXTENT, VOLUME_DISK_EXTENTS},
        IO::DeviceIoControl,
    },
};

const SAMPLE_INTERVAL: Duration = Duration::from_secs(1);
const PROCESS_INTERVAL: Duration = Duration::from_secs(3);
const DISK_INTERVAL: Duration = Duration::from_secs(20);

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CpuStat {
    pub name: String,
    pub logical_cores: u32,
    pub usage_pct: f64,
    pub temp_c: Option<f64>,
    pub clock_mhz: Option<f64>,
    pub clock_source: String,
    pub power_w: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct MemoryStat {
    pub used_bytes: u64,
    pub total_bytes: u64,
    pub usage_pct: f64,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct GpuStat {
    pub name: Option<String>,
    pub hardware_id: Option<String>,
    pub usage_pct: Option<f64>,
    pub temp_c: Option<f64>,
    pub hotspot_c: Option<f64>,
    pub clock_mhz: Option<f64>,
    pub power_w: Option<f64>,
    pub vram_used_mb: Option<f64>,
    pub vram_total_mb: Option<f64>,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct DiskStat {
    pub id: String,
    pub label: String,
    pub used_bytes: u64,
    pub total_bytes: u64,
    pub usage_pct: f64,
    /// Hottest measured component drive; null if Windows/LHM cannot map the volume.
    pub temp_c: Option<f64>,
    pub physical_disk_numbers: Vec<u32>,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct NetworkStat {
    pub adapter: String,
    pub available: bool,
    pub rx_bytes_per_sec: f64,
    pub tx_bytes_per_sec: f64,
    pub available_adapters: Vec<String>,
    pub details: Option<AdapterDetails>,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct AdapterDetails {
    pub description: String,
    pub mac_address: Option<String>,
    pub receive_link_speed_bps: u64,
    pub transmit_link_speed_bps: u64,
    pub received_bytes: u64,
    pub transmitted_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct IoStat {
    pub read_bytes_per_sec: Option<f64>,
    pub write_bytes_per_sec: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ProcessStat {
    pub name: String,
    pub pid: String,
    /// Percentage of the entire machine, consistent with the aggregate CPU card.
    pub cpu_pct: f64,
    pub memory_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub sequence: u64,
    pub captured_at_ms: u64,
    pub sample_duration_ms: f64,
    pub cpu: CpuStat,
    pub memory: MemoryStat,
    pub gpu: GpuStat,
    pub disks: Vec<DiskStat>,
    pub disks_captured_at_ms: Option<u64>,
    pub network: NetworkStat,
    pub disk_io: IoStat,
    pub uptime_secs: u64,
    pub top_cpu_processes: Vec<ProcessStat>,
    pub top_memory_processes: Vec<ProcessStat>,
    pub fans: Vec<SensorReading>,
    pub storage_temps: Vec<SensorReading>,
    pub sensors: Vec<SensorReading>,
    pub sensor_status: SensorStatus,
    pub alerts: Vec<Alert>,
    pub alert_history: Vec<Alert>,
}

impl Default for Snapshot {
    fn default() -> Self {
        Self {
            sequence: 0,
            captured_at_ms: now_ms(),
            sample_duration_ms: 0.0,
            cpu: CpuStat::default(),
            memory: MemoryStat::default(),
            gpu: GpuStat {
                source: "unavailable".into(),
                ..GpuStat::default()
            },
            disks: Vec::new(),
            disks_captured_at_ms: None,
            network: NetworkStat::default(),
            disk_io: IoStat::default(),
            uptime_secs: 0,
            top_cpu_processes: Vec::new(),
            top_memory_processes: Vec::new(),
            fans: Vec::new(),
            storage_temps: Vec::new(),
            sensors: Vec::new(),
            sensor_status: SensorStatus::unavailable("Sensor host is starting"),
            alerts: Vec::new(),
            alert_history: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoryPoint {
    pub captured_at_ms: u64,
    pub cpu_pct: f64,
    pub memory_pct: f64,
    pub gpu_pct: Option<f64>,
    pub rx_bytes_per_sec: Option<f64>,
    pub tx_bytes_per_sec: Option<f64>,
    pub cpu_temp_c: Option<f64>,
    pub gpu_temp_c: Option<f64>,
}
impl From<&Snapshot> for HistoryPoint {
    fn from(value: &Snapshot) -> Self {
        Self {
            captured_at_ms: value.captured_at_ms,
            cpu_pct: value.cpu.usage_pct,
            memory_pct: value.memory.usage_pct,
            gpu_pct: value.gpu.usage_pct,
            rx_bytes_per_sec: value
                .network
                .available
                .then_some(value.network.rx_bytes_per_sec),
            tx_bytes_per_sec: value
                .network
                .available
                .then_some(value.network.tx_bytes_per_sec),
            cpu_temp_c: value.cpu.temp_c,
            gpu_temp_c: value.gpu.temp_c,
        }
    }
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Inventory {
    pub hostname: String,
    pub os_name: String,
    pub cpu_name: String,
    pub logical_cores: u32,
    pub total_memory_bytes: u64,
    pub gpu_names: Vec<String>,
    pub volumes: Vec<DiskStat>,
    pub adapters: Vec<String>,
    pub sensor_count: usize,
}

#[derive(Clone)]
pub struct AppState {
    shared: Arc<Shared>,
}
struct Shared {
    snapshot: RwLock<Snapshot>,
    history: Mutex<VecDeque<HistoryPoint>>,
    inventory: RwLock<Inventory>,
    diagnostics: Mutex<Diagnostics>,
    stop: AtomicBool,
    refresh_requested: AtomicBool,
    collector_thread: Mutex<Option<Thread>>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostics {
    pub collector_state: String,
    pub ticks: u64,
    pub last_error: Option<String>,
    pub sensor_detail: Option<String>,
    pub sample_duration_ms: f64,
    pub max_sample_duration_ms: f64,
    pub last_sample_at_ms: Option<u64>,
    pub disk_age_secs: Option<f64>,
    pub disk_detail: Option<String>,
    pub network_detail: Option<String>,
    pub gpu_counter_detail: Option<String>,
    pub disk_counter_detail: Option<String>,
    pub self_cpu_pct: f64,
    pub self_memory_bytes: u64,
}
impl Default for Diagnostics {
    fn default() -> Self {
        Self {
            collector_state: "starting".into(),
            ticks: 0,
            last_error: None,
            sensor_detail: None,
            sample_duration_ms: 0.0,
            max_sample_duration_ms: 0.0,
            last_sample_at_ms: None,
            disk_age_secs: None,
            disk_detail: None,
            network_detail: None,
            gpu_counter_detail: None,
            disk_counter_detail: None,
            self_cpu_pct: 0.0,
            self_memory_bytes: 0,
        }
    }
}

impl AppState {
    pub fn new() -> Self {
        Self {
            shared: Arc::new(Shared {
                snapshot: RwLock::new(Snapshot::default()),
                history: Mutex::new(VecDeque::with_capacity(60)),
                inventory: RwLock::new(Inventory::default()),
                diagnostics: Mutex::new(Diagnostics::default()),
                stop: AtomicBool::new(false),
                refresh_requested: AtomicBool::new(false),
                collector_thread: Mutex::new(None),
            }),
        }
    }
    pub fn snapshot(&self) -> Snapshot {
        self.shared
            .snapshot
            .read()
            .map(|s| s.clone())
            .unwrap_or_default()
    }
    pub fn diagnostics(&self) -> Diagnostics {
        self.shared
            .diagnostics
            .lock()
            .map(|s| s.clone())
            .unwrap_or_default()
    }
    pub fn inventory(&self) -> Inventory {
        self.shared
            .inventory
            .read()
            .map(|s| s.clone())
            .unwrap_or_default()
    }
    pub fn history(&self) -> Vec<HistoryPoint> {
        self.shared
            .history
            .lock()
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default()
    }
    pub fn stop(&self) {
        self.shared.stop.store(true, AtomicOrdering::Release);
        if let Ok(thread) = self.shared.collector_thread.lock() {
            if let Some(thread) = thread.as_ref() {
                thread.unpark();
            }
        }
    }
    pub fn request_refresh(&self) {
        // Keep exactly one sampler and preserve its one-second rate baselines.
        self.shared
            .refresh_requested
            .store(true, AtomicOrdering::Release);
    }
    fn publish(&self, snapshot: Snapshot) {
        if let Ok(mut history) = self.shared.history.lock() {
            history.push_back(HistoryPoint::from(&snapshot));
            while history.len() > 60
                || history.front().is_some_and(|point| {
                    snapshot.captured_at_ms.saturating_sub(point.captured_at_ms) > 60_000
                })
            {
                history.pop_front();
            }
        }
        if let Ok(mut current) = self.shared.snapshot.write() {
            *current = snapshot;
        }
    }
}

pub fn start_collector(app: AppHandle, state: AppState) {
    let startup_state = state.clone();
    let result = thread::Builder::new()
        .name("ptmonitor-collector".into())
        .spawn(move || {
            let mut collector = Collector::new();
            // Baseline first, then sample on monotonic deadlines. Time spent collecting
            // does not accumulate into cadence drift, and resume never causes catch-up bursts.
            let mut deadline = Instant::now() + SAMPLE_INTERVAL;
            while !state.shared.stop.load(AtomicOrdering::Acquire) {
                let now = Instant::now();
                if now < deadline {
                    thread::park_timeout(deadline - now);
                    continue;
                }
                let started = Instant::now();
                let config = app
                    .state::<Mutex<Config>>()
                    .lock()
                    .map(|cfg| cfg.clone())
                    .unwrap_or_default();
                if state
                    .shared
                    .refresh_requested
                    .swap(false, AtomicOrdering::AcqRel)
                {
                    collector.disks.refresh();
                    collector.last_process_refresh = Instant::now() - PROCESS_INTERVAL;
                    collector.next_sensor_retry = Instant::now();
                }
                let mut snapshot = collector.tick(&config);
                snapshot.sample_duration_ms = started.elapsed().as_secs_f64() * 1000.0;
                if let Ok(mut inventory) = state.shared.inventory.write() {
                    *inventory = collector.inventory(&snapshot);
                }
                if let Ok(mut diagnostics) = state.shared.diagnostics.lock() {
                    diagnostics.collector_state = "running".into();
                    diagnostics.ticks = snapshot.sequence;
                    diagnostics.last_error = collector.last_error.clone();
                    diagnostics.sensor_detail = collector.sensor_status.detail.clone();
                    diagnostics.sample_duration_ms = snapshot.sample_duration_ms;
                    diagnostics.max_sample_duration_ms = diagnostics
                        .max_sample_duration_ms
                        .max(snapshot.sample_duration_ms);
                    diagnostics.last_sample_at_ms = Some(snapshot.captured_at_ms);
                    diagnostics.disk_age_secs = snapshot.disks_captured_at_ms.map(|timestamp| {
                        snapshot.captured_at_ms.saturating_sub(timestamp) as f64 / 1000.0
                    });
                    diagnostics.disk_detail = collector.disks.latest().error;
                    diagnostics.network_detail = collector.network_error.clone();
                    diagnostics.gpu_counter_detail = collector
                        .gpu_pdh
                        .as_ref()
                        .and_then(|g| g.last_error.clone())
                        .or_else(|| collector.gpu_pdh_error.clone());
                    diagnostics.disk_counter_detail = collector
                        .disk_read_pdh
                        .as_ref()
                        .and_then(|g| g.last_error.clone())
                        .or_else(|| {
                            collector
                                .disk_write_pdh
                                .as_ref()
                                .and_then(|g| g.last_error.clone())
                        })
                        .or_else(|| collector.disk_pdh_error.clone());
                    if let Some(process) = collector
                        .system
                        .process(sysinfo::Pid::from_u32(std::process::id()))
                    {
                        diagnostics.self_cpu_pct = normalised_cpu(
                            process.cpu_usage() as f64,
                            collector.system.cpus().len(),
                        );
                        diagnostics.self_memory_bytes = process.memory();
                    }
                }
                state.publish(snapshot.clone());
                if !state.shared.stop.load(AtomicOrdering::Acquire) {
                    if app
                        .get_webview_window("main")
                        .is_some_and(|window| window.is_visible().unwrap_or(false))
                    {
                        let _ = app.emit("ptmonitor://snapshot", &snapshot);
                    }
                    crate::tray::update(&app, &snapshot);
                }
                deadline += SAMPLE_INTERVAL;
                if deadline <= Instant::now() {
                    deadline = Instant::now() + SAMPLE_INTERVAL;
                }
            }
            // Collector owns the sensor bridge; dropping it terminates the bundled child.
            drop(collector);
            if let Ok(mut diagnostics) = state.shared.diagnostics.lock() {
                diagnostics.collector_state = "stopped".into();
            }
        });
    match result {
        Ok(handle) => {
            if let Ok(mut thread) = startup_state.shared.collector_thread.lock() {
                *thread = Some(handle.thread().clone());
            }
        }
        Err(error) => {
            if let Ok(mut diagnostics) = startup_state.shared.diagnostics.lock() {
                diagnostics.collector_state = "failed".into();
                diagnostics.last_error = Some(format!("start native sampler: {error}"));
            }
        }
    }
}

struct Collector {
    system: System,
    hostname: String,
    os_name: String,
    network_error: Option<String>,
    network_tracker: NetworkTracker,
    last_network_tick: Instant,
    last_process_refresh: Instant,
    top_cpu_processes: Vec<ProcessStat>,
    top_memory_processes: Vec<ProcessStat>,
    disks: DiskWorker,
    gpu_pdh: Option<PdhGauge>,
    gpu_pdh_error: Option<String>,
    disk_read_pdh: Option<PdhGauge>,
    disk_write_pdh: Option<PdhGauge>,
    disk_pdh_error: Option<String>,
    sensor: Option<SensorBridge>,
    sensor_advanced: bool,
    next_sensor_retry: Instant,
    sensor_retry_seconds: u64,
    sensor_readings: Vec<SensorReading>,
    sensor_status: SensorStatus,
    last_error: Option<String>,
    alert_engine: AlertEngine,
    started: Instant,
    sequence: u64,
}

impl Collector {
    fn new() -> Self {
        let mut system = System::new();
        system.refresh_cpu_usage();
        system.refresh_cpu_frequency();
        system.refresh_memory();
        refresh_processes(&mut system);
        let mut network_tracker = NetworkTracker::default();
        let networks = network_totals();
        let network_error = networks.as_ref().err().cloned();
        network_tracker.sample(networks.unwrap_or_default(), 1.0, None);
        let now = Instant::now();
        let gpu_pdh = PdhGauge::new(r"\GPU Engine(*)\Utilization Percentage");
        let disk_read_pdh = PdhGauge::new(r"\PhysicalDisk(_Total)\Disk Read Bytes/sec");
        let disk_write_pdh = PdhGauge::new(r"\PhysicalDisk(_Total)\Disk Write Bytes/sec");
        let disk_pdh_error = disk_read_pdh
            .as_ref()
            .err()
            .cloned()
            .or_else(|| disk_write_pdh.as_ref().err().cloned());
        Self {
            system,
            hostname: System::host_name().unwrap_or_default(),
            os_name: System::long_os_version().unwrap_or_default(),
            network_error,
            network_tracker,
            last_network_tick: now,
            last_process_refresh: now,
            top_cpu_processes: Vec::new(),
            top_memory_processes: Vec::new(),
            disks: DiskWorker::start(),
            gpu_pdh_error: gpu_pdh.as_ref().err().cloned(),
            gpu_pdh: gpu_pdh.ok(),
            disk_read_pdh: disk_read_pdh.ok(),
            disk_write_pdh: disk_write_pdh.ok(),
            disk_pdh_error,
            sensor: None,
            sensor_advanced: false,
            next_sensor_retry: now,
            sensor_retry_seconds: 2,
            sensor_readings: Vec::new(),
            sensor_status: SensorStatus::unavailable("Sensor host has not been started"),
            last_error: None,
            alert_engine: AlertEngine::default(),
            started: now,
            sequence: 0,
        }
    }

    fn tick(&mut self, config: &Config) -> Snapshot {
        self.sequence += 1;
        self.system.refresh_cpu_usage();
        self.system.refresh_memory();
        if self.last_process_refresh.elapsed() >= PROCESS_INTERVAL {
            refresh_processes(&mut self.system);
            self.system.refresh_cpu_frequency();
            self.top_cpu_processes = ranked_processes(&self.system, true);
            self.top_memory_processes = ranked_processes(&self.system, false);
            self.last_process_refresh = Instant::now();
        }
        let networks = network_totals();
        self.network_error = networks.as_ref().err().cloned();
        let elapsed = self.last_network_tick.elapsed().as_secs_f64();
        let network = self.network_tracker.sample(
            networks.unwrap_or_default(),
            elapsed,
            config.selected_adapter.as_deref(),
        );
        self.last_network_tick = Instant::now();
        self.refresh_sensor_host(config.advanced_sensors);
        let summary = sensor::summarise(&self.sensor_readings);
        let pdh_usage = self.gpu_pdh.as_mut().and_then(PdhGauge::sample_gpu);
        // A selected sensor GPU's missing load must not be filled with a different
        // adapter's PDH aggregate on hybrid/multi-GPU workstations.
        let gpu_usage = choose_gpu_usage(
            summary.gpu_hardware_id.as_deref(),
            summary.gpu_load_pct,
            pdh_usage,
        );
        let gpu_source = if summary.gpu_hardware_id.is_some() {
            "sensor-host"
        } else if pdh_usage.is_some() {
            "windows-pdh (busiest engine across adapters)"
        } else {
            "unavailable"
        };
        let memory_total = self.system.total_memory();
        let memory_used = self.system.used_memory();
        let mut disks = self.disks.latest();
        assign_disk_temperatures(&mut disks.volumes, &summary.storage_temps);
        let mut snapshot = Snapshot {
            sequence: self.sequence,
            captured_at_ms: now_ms(),
            sample_duration_ms: 0.0,
            cpu: CpuStat {
                name: self
                    .system
                    .cpus()
                    .first()
                    .map(|cpu| cpu.brand().to_string())
                    .unwrap_or_default(),
                logical_cores: self.system.cpus().len() as u32,
                usage_pct: self.system.global_cpu_usage().clamp(0.0, 100.0) as f64,
                temp_c: summary.cpu_temp_c,
                clock_source: if summary.cpu_clock_mhz.is_some() {
                    "sensor-host"
                } else {
                    "windows"
                }
                .into(),
                clock_mhz: summary.cpu_clock_mhz.or_else(|| {
                    let frequencies: Vec<_> = self
                        .system
                        .cpus()
                        .iter()
                        .map(|cpu| cpu.frequency())
                        .filter(|frequency| *frequency > 0)
                        .collect();
                    (!frequencies.is_empty())
                        .then(|| frequencies.iter().sum::<u64>() as f64 / frequencies.len() as f64)
                }),
                power_w: summary.cpu_power_w,
            },
            memory: MemoryStat {
                used_bytes: memory_used,
                total_bytes: memory_total,
                usage_pct: percent(memory_used as f64, memory_total as f64),
            },
            gpu: GpuStat {
                name: summary.gpu_name,
                hardware_id: summary.gpu_hardware_id,
                usage_pct: gpu_usage,
                temp_c: summary.gpu_temp_c,
                hotspot_c: summary.gpu_hotspot_c,
                clock_mhz: summary.gpu_clock_mhz,
                power_w: summary.gpu_power_w,
                vram_used_mb: summary.gpu_vram_used_mb,
                vram_total_mb: summary.gpu_vram_total_mb,
                source: gpu_source.into(),
            },
            disks: disks.volumes,
            disks_captured_at_ms: disks.captured_at_ms,
            network,
            disk_io: IoStat {
                read_bytes_per_sec: self.disk_read_pdh.as_mut().and_then(PdhGauge::sample_sum),
                write_bytes_per_sec: self.disk_write_pdh.as_mut().and_then(PdhGauge::sample_sum),
            },
            uptime_secs: System::uptime(),
            top_cpu_processes: self.top_cpu_processes.clone(),
            top_memory_processes: self.top_memory_processes.clone(),
            fans: summary.fan_rpm,
            storage_temps: summary.storage_temps,
            sensors: self.sensor_readings.clone(),
            sensor_status: self.sensor_status.clone(),
            alerts: Vec::new(),
            alert_history: Vec::new(),
        };
        snapshot.alerts = self.alert_engine.evaluate(
            &snapshot,
            &config.thresholds,
            self.started.elapsed().as_millis() as u64,
        );
        snapshot.alert_history = self.alert_engine.history();
        snapshot
    }

    fn inventory(&self, snapshot: &Snapshot) -> Inventory {
        let mut gpu_names: Vec<_> = snapshot
            .sensors
            .iter()
            .filter(|s| s.hardware_type.to_ascii_lowercase().contains("gpu"))
            .map(|s| s.hardware.clone())
            .collect();
        gpu_names.sort();
        gpu_names.dedup();
        Inventory {
            hostname: self.hostname.clone(),
            os_name: self.os_name.clone(),
            cpu_name: snapshot.cpu.name.clone(),
            logical_cores: snapshot.cpu.logical_cores,
            total_memory_bytes: snapshot.memory.total_bytes,
            gpu_names,
            volumes: snapshot.disks.clone(),
            adapters: snapshot.network.available_adapters.clone(),
            sensor_count: snapshot.sensors.len(),
        }
    }

    fn refresh_sensor_host(&mut self, advanced: bool) {
        if self.sensor_advanced != advanced {
            self.sensor = None;
            self.sensor_readings.clear();
            self.sensor_advanced = advanced;
            self.sensor_retry_seconds = 2;
            self.next_sensor_retry = Instant::now();
        }
        if self.sensor.is_none() && Instant::now() >= self.next_sensor_retry {
            match SensorBridge::start(advanced) {
                Ok(bridge) => {
                    self.sensor = Some(bridge);
                    self.sensor_status = SensorStatus {
                        state: "starting".into(),
                        detail: None,
                        last_seen_ms: None,
                    };
                }
                Err(error) => self.sensor_failed(error),
            }
        }
        if let Some(bridge) = self.sensor.as_mut() {
            let newest = bridge.latest();
            // Test liveness even when a final envelope was queued before process exit.
            if bridge.stale() {
                self.sensor_failed("Sensor host stopped or its heartbeat timed out".into());
            } else if let Some(envelope) = newest {
                self.sensor_readings = envelope.sensors;
                self.sensor_retry_seconds = 2;
                self.last_error = None;
                self.sensor_status = SensorStatus {
                    state: if envelope.status.is_empty() {
                        "online".into()
                    } else {
                        envelope.status
                    },
                    detail: envelope.detail,
                    last_seen_ms: Some(envelope.timestamp_ms),
                };
            }
        }
    }

    fn sensor_failed(&mut self, error: String) {
        self.sensor = None;
        self.sensor_readings.clear();
        self.sensor_status = SensorStatus::unavailable(format!(
            "{error}; retrying in {} seconds",
            self.sensor_retry_seconds
        ));
        self.last_error = Some(error);
        self.next_sensor_retry = Instant::now() + Duration::from_secs(self.sensor_retry_seconds);
        self.sensor_retry_seconds = (self.sensor_retry_seconds * 2).min(60);
    }
}

#[derive(Clone, Default)]
struct DiskCache {
    volumes: Vec<DiskStat>,
    captured_at_ms: Option<u64>,
    error: Option<String>,
}
struct DiskWorker {
    cache: Arc<Mutex<DiskCache>>,
    stop: Arc<AtomicBool>,
    thread: Option<Thread>,
}
impl DiskWorker {
    fn start() -> Self {
        let cache = Arc::new(Mutex::new(DiskCache::default()));
        let stop = Arc::new(AtomicBool::new(false));
        let worker_cache = cache.clone();
        let worker_stop = stop.clone();
        let result = thread::Builder::new()
            .name("ptmonitor-volumes".into())
            .spawn(move || {
                while !worker_stop.load(AtomicOrdering::Acquire) {
                    let result = collect_disks();
                    if let Ok(mut cache) = worker_cache.lock() {
                        *cache = result;
                    }
                    thread::park_timeout(DISK_INTERVAL);
                }
            });
        let thread = match result {
            Ok(handle) => Some(handle.thread().clone()),
            Err(error) => {
                if let Ok(mut cache) = cache.lock() {
                    cache.error = Some(format!("start disk collector: {error}"));
                }
                None
            }
        };
        Self {
            cache,
            stop,
            thread,
        }
    }
    fn latest(&self) -> DiskCache {
        self.cache.lock().map(|v| v.clone()).unwrap_or_default()
    }
    fn refresh(&self) {
        if let Some(thread) = &self.thread {
            thread.unpark();
        }
    }
}
impl Drop for DiskWorker {
    fn drop(&mut self) {
        self.stop.store(true, AtomicOrdering::Release);
        self.refresh();
        // Never hold up shutdown waiting for a failed disk controller's OS call.
    }
}

fn collect_disks() -> DiskCache {
    let mask = unsafe { GetLogicalDrives() };
    if mask == 0 {
        return DiskCache {
            error: Some(format!(
                "enumerate volumes: {}",
                std::io::Error::last_os_error()
            )),
            ..DiskCache::default()
        };
    }
    let mut volumes = Vec::new();
    let mut errors = Vec::new();
    for index in 0..26 {
        if mask & (1 << index) == 0 {
            continue;
        }
        let label = format!("{}:", (b'A' + index) as char);
        let root = format!("{label}\\");
        let wide: Vec<u16> = root.encode_utf16().chain(std::iter::once(0)).collect();
        // Filter BEFORE querying capacity. Offline mapped SMB drives must never be
        // queried by the local workstation monitor. DRIVE_FIXED is 3 in WinBase.h.
        if unsafe { GetDriveTypeW(wide.as_ptr()) } != 3 {
            continue;
        }
        let mut available = 0;
        let mut total = 0;
        let mut free = 0;
        if unsafe { GetDiskFreeSpaceExW(wide.as_ptr(), &mut available, &mut total, &mut free) } == 0
        {
            errors.push(format!("{label}: {}", std::io::Error::last_os_error()));
            continue;
        }
        if total == 0 {
            continue;
        }
        let used = total.saturating_sub(free);
        let physical_disk_numbers = volume_disk_numbers(&label);
        volumes.push(DiskStat {
            id: root,
            label,
            used_bytes: used,
            total_bytes: total,
            usage_pct: percent(used as f64, total as f64),
            temp_c: None,
            physical_disk_numbers,
        });
    }
    priority_disks(
        &mut volumes,
        &std::env::var("SystemDrive").unwrap_or_else(|_| "C:".into()),
    );
    DiskCache {
        volumes,
        captured_at_ms: Some(now_ms()),
        error: (!errors.is_empty()).then(|| errors.join("; ")),
    }
}

fn assign_disk_temperatures(disks: &mut [DiskStat], readings: &[SensorReading]) {
    for disk in disks {
        disk.temp_c = readings
            .iter()
            .filter(|reading| {
                reading
                    .physical_disk_number
                    .is_some_and(|number| disk.physical_disk_numbers.contains(&number))
            })
            .map(|reading| reading.value)
            .filter(|value| value.is_finite() && *value > 0.0)
            .reduce(f64::max);
    }
}

fn volume_disk_numbers(label: &str) -> Vec<u32> {
    let path: Vec<u16> = format!(r"\\.\{label}")
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    // This metadata IOCTL uses FILE_ANY_ACCESS; no administrative handle or writes.
    let handle = unsafe {
        CreateFileW(
            path.as_ptr(),
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            std::ptr::null(),
            OPEN_EXISTING,
            0,
            std::ptr::null_mut(),
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Vec::new();
    }
    let mut buffer = vec![0u64; 512];
    let mut returned = 0;
    // CTL_CODE('V', 0, METHOD_BUFFERED, FILE_ANY_ACCESS), from winioctl.h.
    let success = unsafe {
        DeviceIoControl(
            handle,
            0x0056_0000,
            std::ptr::null(),
            0,
            buffer.as_mut_ptr().cast(),
            (buffer.len() * 8) as u32,
            &mut returned,
            std::ptr::null_mut(),
        )
    };
    unsafe { CloseHandle(handle) };
    let offset = std::mem::offset_of!(VOLUME_DISK_EXTENTS, Extents);
    if success == 0 || (returned as usize) < offset || returned as usize > buffer.len() * 8 {
        return Vec::new();
    }
    let extents = buffer.as_ptr().cast::<VOLUME_DISK_EXTENTS>();
    let count = unsafe { (*extents).NumberOfDiskExtents } as usize;
    if count > (returned as usize - offset) / std::mem::size_of::<DISK_EXTENT>() {
        return Vec::new();
    }
    let rows = unsafe { std::slice::from_raw_parts((*extents).Extents.as_ptr(), count) };
    let mut numbers: Vec<_> = rows.iter().map(|row| row.DiskNumber).collect();
    numbers.sort_unstable();
    numbers.dedup();
    numbers
}

fn priority_disks(disks: &mut [DiskStat], system_drive: &str) {
    disks.sort_by(|a, b| {
        let system_a = a.label.eq_ignore_ascii_case(system_drive);
        let system_b = b.label.eq_ignore_ascii_case(system_drive);
        system_b
            .cmp(&system_a)
            .then_with(|| b.usage_pct.total_cmp(&a.usage_pct))
            .then_with(|| a.label.cmp(&b.label))
    });
}

#[derive(Default)]
struct NetworkTracker {
    previous: HashMap<String, (u64, u64, u64)>,
    selected: Option<String>,
    challenger: Option<String>,
    challenger_ticks: u8,
}
impl NetworkTracker {
    fn sample(
        &mut self,
        totals: Vec<NetworkCounters>,
        elapsed: f64,
        configured: Option<&str>,
    ) -> NetworkStat {
        let elapsed = if elapsed.is_finite() && elapsed > 0.0 {
            elapsed
        } else {
            1.0
        };
        let mut rates = Vec::new();
        let mut next = HashMap::new();
        let details: HashMap<_, _> = totals
            .iter()
            .map(|c| (c.name.clone(), c.details.clone()))
            .collect();
        for NetworkCounters {
            name,
            identity,
            rx,
            tx,
            ..
        } in totals
        {
            let old = self
                .previous
                .get(&name)
                .copied()
                .filter(|old| old.0 == identity)
                .unwrap_or((identity, rx, tx));
            // New/hotplugged adapters establish a baseline. Counter rollover/reset
            // yields zero for that direction rather than a total-since-boot spike.
            rates.push((
                name.clone(),
                rx.saturating_sub(old.1) as f64 / elapsed,
                tx.saturating_sub(old.2) as f64 / elapsed,
            ));
            next.insert(name, (identity, rx, tx));
        }
        self.previous = next;
        rates.sort_by(|a, b| a.0.cmp(&b.0));
        let available_adapters: Vec<_> = rates.iter().map(|(name, _, _)| name.clone()).collect();
        let best = rates.iter().max_by(|a, b| {
            (a.1 + a.2)
                .total_cmp(&(b.1 + b.2))
                .then_with(|| b.0.cmp(&a.0))
        });
        if configured.is_none() {
            let current = self
                .selected
                .as_ref()
                .and_then(|selected| rates.iter().find(|r| &r.0 == selected));
            match (current, best) {
                (None, Some(best)) => {
                    self.selected = Some(best.0.clone());
                    self.challenger = None;
                }
                (Some(current), Some(best))
                    if current.0 != best.0
                        && best.1 + best.2
                            > ((current.1 + current.2) * 1.5)
                                .max(current.1 + current.2 + 1024.0) =>
                {
                    if self.challenger.as_deref() == Some(&best.0) {
                        self.challenger_ticks += 1;
                    } else {
                        self.challenger = Some(best.0.clone());
                        self.challenger_ticks = 1;
                    }
                    if self.challenger_ticks >= 3 {
                        self.selected = Some(best.0.clone());
                        self.challenger = None;
                        self.challenger_ticks = 0;
                    }
                }
                _ => {
                    self.challenger = None;
                    self.challenger_ticks = 0;
                }
            }
        }
        let selected_name = configured.or(self.selected.as_deref());
        let selected = selected_name.and_then(|name| rates.iter().find(|r| r.0 == name));
        match selected {
            Some((adapter, rx, tx)) => NetworkStat {
                adapter: adapter.clone(),
                available: true,
                rx_bytes_per_sec: *rx,
                tx_bytes_per_sec: *tx,
                available_adapters,
                details: details.get(adapter).cloned(),
            },
            None => NetworkStat {
                adapter: selected_name.unwrap_or("No active adapter").into(),
                available_adapters,
                ..NetworkStat::default()
            },
        }
    }
}

struct NetworkCounters {
    name: String,
    identity: u64,
    rx: u64,
    tx: u64,
    details: AdapterDetails,
}

fn network_totals() -> Result<Vec<NetworkCounters>, String> {
    let mut table: *mut MIB_IF_TABLE2 = std::ptr::null_mut();
    let status = unsafe { GetIfTable2(&mut table) };
    if status != 0 || table.is_null() {
        return Err(format!("read network adapters ({status:#x})"));
    }
    struct Table(*mut MIB_IF_TABLE2);
    impl Drop for Table {
        fn drop(&mut self) {
            unsafe { FreeMibTable(self.0.cast()) };
        }
    }
    let table = Table(table);
    let count = unsafe { (*table.0).NumEntries } as usize;
    if count > 65536 {
        return Err("Invalid network interface count".into());
    }
    let rows = unsafe { std::slice::from_raw_parts((*table.0).Table.as_ptr(), count) };
    Ok(rows
        .iter()
        .filter(|row| row.OperStatus == IfOperStatusUp && row.Type != IF_TYPE_SOFTWARE_LOOPBACK)
        .map(|row| {
            let len = row
                .Alias
                .iter()
                .position(|value| *value == 0)
                .unwrap_or(row.Alias.len());
            NetworkCounters {
                name: String::from_utf16_lossy(&row.Alias[..len]),
                identity: unsafe { row.InterfaceLuid.Value },
                rx: row.InOctets,
                tx: row.OutOctets,
                details: AdapterDetails {
                    description: String::from_utf16_lossy(
                        &row.Description[..row
                            .Description
                            .iter()
                            .position(|c| *c == 0)
                            .unwrap_or(row.Description.len())],
                    ),
                    mac_address: (row.PhysicalAddressLength > 0).then(|| {
                        row.PhysicalAddress
                            [..(row.PhysicalAddressLength as usize).min(row.PhysicalAddress.len())]
                            .iter()
                            .map(|b| format!("{b:02X}"))
                            .collect::<Vec<_>>()
                            .join(":")
                    }),
                    receive_link_speed_bps: row.ReceiveLinkSpeed,
                    transmit_link_speed_bps: row.TransmitLinkSpeed,
                    received_bytes: row.InOctets,
                    transmitted_bytes: row.OutOctets,
                },
            }
        })
        .collect())
}
fn refresh_processes(system: &mut System) {
    system.refresh_processes_specifics(
        ProcessesToUpdate::All,
        true,
        ProcessRefreshKind::nothing().with_cpu().with_memory(),
    );
}
fn normalised_cpu(cpu: f64, logical_cores: usize) -> f64 {
    if cpu.is_finite() {
        (cpu / logical_cores.max(1) as f64).clamp(0.0, 100.0)
    } else {
        0.0
    }
}

fn choose_gpu_usage(
    sensor_hardware_id: Option<&str>,
    sensor_load: Option<f64>,
    aggregate_pdh: Option<f64>,
) -> Option<f64> {
    if sensor_hardware_id.is_some() {
        sensor_load
    } else {
        aggregate_pdh
    }
}
fn ranked_processes(system: &System, by_cpu: bool) -> Vec<ProcessStat> {
    let mut list = system
        .processes()
        .iter()
        .filter_map(|(pid, process)| {
            // Windows idle/system PID 0 is not a useful user workload.
            if pid.as_u32() == 0 {
                return None;
            }
            let cpu = normalised_cpu(process.cpu_usage() as f64, system.cpus().len());
            let memory = process.memory();
            (cpu > 0.0 || memory > 0).then(|| ProcessStat {
                name: process.name().to_string_lossy().to_string(),
                pid: pid.to_string(),
                cpu_pct: cpu,
                memory_bytes: memory,
            })
        })
        .collect::<Vec<_>>();
    list.sort_by(|a, b| {
        let primary = if by_cpu {
            b.cpu_pct.partial_cmp(&a.cpu_pct).unwrap_or(Ordering::Equal)
        } else {
            b.memory_bytes.cmp(&a.memory_bytes)
        };
        primary
            .then_with(|| a.name.cmp(&b.name))
            .then_with(|| a.pid.cmp(&b.pid))
    });
    list.truncate(5);
    list
}
fn percent(value: f64, total: f64) -> f64 {
    if value.is_finite() && total.is_finite() && total > 0.0 {
        (value / total * 100.0).clamp(0.0, 100.0)
    } else {
        0.0
    }
}
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[tauri::command]
pub fn get_snapshot(state: tauri::State<'_, AppState>) -> Snapshot {
    state.snapshot()
}
#[tauri::command]
pub fn get_diagnostics(state: tauri::State<'_, AppState>) -> Diagnostics {
    state.diagnostics()
}
#[tauri::command]
pub fn get_inventory(state: tauri::State<'_, AppState>) -> Inventory {
    state.inventory()
}
#[tauri::command]
pub fn get_history(state: tauri::State<'_, AppState>) -> Vec<HistoryPoint> {
    state.history()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn net(name: &str, rx: u64, tx: u64) -> NetworkCounters {
        NetworkCounters {
            name: name.into(),
            identity: 1,
            rx,
            tx,
            details: AdapterDetails::default(),
        }
    }
    #[test]
    fn hotplug_and_counter_resets_never_spike() {
        let mut tracker = NetworkTracker::default();
        assert_eq!(
            tracker
                .sample(vec![net("LAN", 100_000, 4000)], 1.0, None)
                .rx_bytes_per_sec,
            0.0
        );
        assert_eq!(
            tracker
                .sample(vec![net("LAN", 104_000, 6000)], 2.0, None)
                .rx_bytes_per_sec,
            2000.0
        );
        assert_eq!(
            tracker
                .sample(vec![net("LAN", 100, 10)], 1.0, None)
                .rx_bytes_per_sec,
            0.0
        );
        tracker.sample(vec![], 1.0, None);
        assert_eq!(
            tracker
                .sample(vec![net("LAN", 900_000, 9000)], 1.0, None)
                .rx_bytes_per_sec,
            0.0
        );
    }
    #[test]
    fn explicit_missing_adapter_does_not_silently_show_other_traffic() {
        let mut tracker = NetworkTracker::default();
        let value = tracker.sample(vec![net("LAN", 0, 0)], 1.0, Some("VPN"));
        assert!(!value.available);
        assert_eq!(value.adapter, "VPN");
    }

    #[test]
    fn replaced_adapter_with_same_name_establishes_new_baseline() {
        let mut tracker = NetworkTracker::default();
        tracker.sample(vec![net("LAN", 2000, 0)], 1.0, None);
        let replacement = NetworkCounters {
            name: "LAN".into(),
            identity: 2,
            rx: 900_000,
            tx: 100_000,
            details: AdapterDetails::default(),
        };
        let result = tracker.sample(vec![replacement], 1.0, None);
        assert_eq!(result.rx_bytes_per_sec, 0.0);
        assert_eq!(result.tx_bytes_per_sec, 0.0);
    }

    #[test]
    fn disk_temperature_mapping_uses_physical_identity_and_clears_missing_data() {
        let mut disks = vec![
            DiskStat {
                physical_disk_numbers: vec![2, 3],
                ..DiskStat::default()
            },
            DiskStat {
                physical_disk_numbers: vec![4],
                ..DiskStat::default()
            },
        ];
        assign_disk_temperatures(
            &mut disks,
            &[
                SensorReading {
                    physical_disk_number: Some(2),
                    value: 42.0,
                    ..SensorReading::default()
                },
                SensorReading {
                    physical_disk_number: Some(3),
                    value: 49.0,
                    ..SensorReading::default()
                },
                SensorReading {
                    physical_disk_number: None,
                    value: 99.0,
                    ..SensorReading::default()
                },
            ],
        );
        assert_eq!(disks[0].temp_c, Some(49.0));
        assert_eq!(disks[1].temp_c, None);
        assign_disk_temperatures(&mut disks, &[]);
        assert_eq!(disks[0].temp_c, None);
    }
    #[test]
    fn auto_adapter_stable_when_idle_and_switches_after_sustained_activity() {
        let mut tracker = NetworkTracker::default();
        tracker.sample(vec![net("A", 0, 0), net("B", 0, 0)], 1.0, None);
        assert_eq!(
            tracker
                .sample(vec![net("A", 0, 0), net("B", 5000, 0)], 1.0, None)
                .adapter,
            "A"
        );
        tracker.sample(vec![net("A", 0, 0), net("B", 10000, 0)], 1.0, None);
        assert_eq!(
            tracker
                .sample(vec![net("A", 0, 0), net("B", 15000, 0)], 1.0, None)
                .adapter,
            "B"
        );
        assert_eq!(
            tracker
                .sample(vec![net("A", 0, 0), net("B", 15000, 0)], 1.0, None)
                .adapter,
            "B"
        );
    }
    #[test]
    fn process_cpu_is_normalised_to_machine_capacity() {
        assert_eq!(normalised_cpu(800.0, 16), 50.0);
        assert_eq!(normalised_cpu(2000.0, 16), 100.0);
        assert_eq!(normalised_cpu(f64::NAN, 16), 0.0);
    }

    #[test]
    fn gpu_fallback_never_combines_other_adapter_load_with_selected_sensor_gpu() {
        assert_eq!(
            choose_gpu_usage(Some("/gpu-nvidia/0"), None, Some(99.0)),
            None
        );
        assert_eq!(
            choose_gpu_usage(Some("/gpu-nvidia/0"), Some(12.0), Some(99.0)),
            Some(12.0)
        );
        assert_eq!(choose_gpu_usage(None, None, Some(99.0)), Some(99.0));
    }
    #[test]
    fn system_volume_precedes_most_full_volumes() {
        let mut disks = vec![
            DiskStat {
                label: "E:".into(),
                usage_pct: 95.0,
                ..DiskStat::default()
            },
            DiskStat {
                label: "C:".into(),
                usage_pct: 30.0,
                ..DiskStat::default()
            },
            DiskStat {
                label: "D:".into(),
                usage_pct: 80.0,
                ..DiskStat::default()
            },
        ];
        priority_disks(&mut disks, "c:");
        assert_eq!(
            disks.iter().map(|d| d.label.as_str()).collect::<Vec<_>>(),
            ["C:", "E:", "D:"]
        );
    }
    #[test]
    fn native_history_is_bounded_and_missing_rates_are_null() {
        let state = AppState::new();
        for timestamp in 0..75 {
            state.publish(Snapshot {
                captured_at_ms: timestamp,
                ..Snapshot::default()
            });
        }
        let history = state.history();
        assert_eq!(history.len(), 60);
        assert_eq!(history[0].captured_at_ms, 15);
        assert_eq!(history[59].captured_at_ms, 74);
        assert_eq!(history[0].rx_bytes_per_sec, None);
    }
    #[test]
    fn percentage_is_finite_and_bounded() {
        assert_eq!(percent(20.0, 0.0), 0.0);
        assert_eq!(percent(200.0, 100.0), 100.0);
        assert_eq!(percent(f64::INFINITY, 100.0), 0.0);
    }

    #[test]
    #[ignore = "Read-only hardware probe; explicitly run on the target Windows workstation"]
    fn native_windows_sampling_smoke() {
        let mut collector = Collector::new();
        for _ in 0..5 {
            thread::sleep(SAMPLE_INTERVAL);
            let started = Instant::now();
            let snapshot = collector.tick(&Config::default());
            assert!(snapshot.cpu.logical_cores > 0);
            assert!(snapshot.memory.total_bytes > 0);
            assert!(snapshot.cpu.usage_pct.is_finite());
            assert!(snapshot.uptime_secs > 0);
            println!("sequence={} sample_ms={:.1} cpu={:.1}% memory={:.1}% gpu={:?} GPU-source={} local-volumes={} adapter={} sensors={} sensor-state={}",
                snapshot.sequence, started.elapsed().as_secs_f64() * 1000.0,
                snapshot.cpu.usage_pct, snapshot.memory.usage_pct, snapshot.gpu.usage_pct,
                snapshot.gpu.source, snapshot.disks.len(), snapshot.network.adapter,
                snapshot.sensors.len(), snapshot.sensor_status.state);
            if snapshot.sequence == 5 {
                println!(
                    "volume_mapping={:?}",
                    snapshot
                        .disks
                        .iter()
                        .map(|disk| (&disk.label, &disk.physical_disk_numbers, disk.temp_c))
                        .collect::<Vec<_>>()
                );
                println!(
                    "pdh_gpu_sample={:?} error={:?}",
                    collector.gpu_pdh.as_mut().and_then(PdhGauge::sample_gpu),
                    collector
                        .gpu_pdh
                        .as_ref()
                        .and_then(|p| p.last_error.as_deref())
                );
            }
        }
    }
}
