//! Bounded, supervised JSON-lines IPC. The helper never opens a network listener.
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver},
        Arc,
    },
    thread::JoinHandle,
    time::{Duration, Instant},
};
const MAX_FRAME_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase", default)]
pub struct SensorReading {
    pub id: String,
    pub name: String,
    pub hardware: String,
    pub hardware_id: String,
    pub root_hardware_id: String,
    pub physical_disk_number: Option<u32>,
    pub hardware_type: String,
    pub sensor_type: String,
    pub unit: String,
    pub source: String,
    pub value: f64,
    pub min: Option<f64>,
    pub max: Option<f64>,
}
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SensorEnvelope {
    pub protocol_version: u32,
    pub timestamp_ms: u64,
    pub sensors: Vec<SensorReading>,
    pub status: String,
    pub detail: Option<String>,
}
#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SensorStatus {
    pub state: String,
    pub detail: Option<String>,
    pub last_seen_ms: Option<u64>,
}
impl SensorStatus {
    pub fn unavailable(detail: impl Into<String>) -> Self {
        Self {
            state: "unavailable".into(),
            detail: Some(detail.into()),
            last_seen_ms: None,
        }
    }
}
pub struct SensorBridge {
    child: Child,
    reader: Option<JoinHandle<()>>,
    receiver: Receiver<(Instant, SensorEnvelope)>,
    reader_ended: Arc<AtomicBool>,
    last_seen: Instant,
    received_frame: bool,
}
impl SensorBridge {
    pub fn start(advanced: bool) -> Result<Self, String> {
        let executable = resolve_sidecar().ok_or_else(||
            "Sensor helper is missing. Run npm run build:sensors or install the complete PTMonitor v2 release.".to_string())?;
        let mut command = Command::new(&executable);
        command.args(["--stdio", "--parent-pid", &std::process::id().to_string()]);
        if advanced {
            command.arg("--advanced");
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("Start sensor helper ({}): {e}", executable.display()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Sensor helper has no stdout".to_string())?;
        let (sender, receiver) = mpsc::sync_channel(2);
        let reader_ended = Arc::new(AtomicBool::new(false));
        let ended = reader_ended.clone();
        let reader = match std::thread::Builder::new()
            .name("ptmonitor-sensor-reader".into())
            .spawn(move || {
                let mut reader = BufReader::new(stdout);
                loop {
                    let mut frame = Vec::new();
                    let length = Read::by_ref(&mut reader)
                        .take(MAX_FRAME_BYTES + 1)
                        .read_until(b'\n', &mut frame);
                    match length {
                        Ok(0) | Err(_) => break,
                        Ok(n) if n as u64 > MAX_FRAME_BYTES => break,
                        _ => {}
                    }
                    if let Ok(mut envelope) = serde_json::from_slice::<SensorEnvelope>(&frame) {
                        if envelope.protocol_version != 1 || envelope.sensors.len() > 8192 {
                            break;
                        }
                        envelope.sensors.retain(|r| r.value.is_finite());
                        if let Err(mpsc::TrySendError::Disconnected(_)) =
                            sender.try_send((Instant::now(), envelope))
                        {
                            break;
                        }
                    }
                }
                ended.store(true, Ordering::Release);
            }) {
            Ok(reader) => reader,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Start sensor reader: {error}"));
            }
        };
        Ok(Self {
            child,
            reader: Some(reader),
            receiver,
            reader_ended,
            last_seen: Instant::now(),
            received_frame: false,
        })
    }
    pub fn latest(&mut self) -> Option<SensorEnvelope> {
        // A parent that is alive but no longer collecting must not leave sensor polling alive.
        if let Some(stdin) = self.child.stdin.as_mut() {
            let _ = stdin.write_all(b"ping\n");
        }
        let mut newest = None;
        while let Ok((received_at, envelope)) = self.receiver.try_recv() {
            self.last_seen = received_at;
            self.received_frame = true;
            newest = Some(envelope);
        }
        newest
    }
    pub fn stale(&self) -> bool {
        self.reader_ended.load(Ordering::Acquire)
            || self.last_seen.elapsed()
                > Duration::from_secs(if self.received_frame { 6 } else { 30 })
    }
}
impl Drop for SensorBridge {
    fn drop(&mut self) {
        // EOF requests graceful hardware disposal; kill/wait also handles hung vendor APIs.
        drop(self.child.stdin.take());
        for _ in 0..10 {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}
fn resolve_sidecar() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    // The installed application cannot execute an ambient environment override.
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("PTMONITOR_SENSOR_HOST") {
        candidates.push(PathBuf::from(path));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.join("PTMonitor.SensorHost.exe"));
        }
    }
    #[cfg(debug_assertions)]
    {
        candidates.push(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("binaries/PTMonitor.SensorHost-x86_64-pc-windows-msvc.exe"),
        );
    }
    candidates.into_iter().find(|path| path.is_file())
}
#[derive(Debug, Default, Clone)]
pub struct SensorSummary {
    pub gpu_name: Option<String>,
    pub gpu_hardware_id: Option<String>,
    pub gpu_load_pct: Option<f64>,
    pub cpu_temp_c: Option<f64>,
    pub cpu_clock_mhz: Option<f64>,
    pub cpu_power_w: Option<f64>,
    pub gpu_temp_c: Option<f64>,
    pub gpu_hotspot_c: Option<f64>,
    pub gpu_clock_mhz: Option<f64>,
    pub gpu_power_w: Option<f64>,
    pub gpu_vram_used_mb: Option<f64>,
    pub gpu_vram_total_mb: Option<f64>,
    pub fan_rpm: Vec<SensorReading>,
    pub storage_temps: Vec<SensorReading>,
}
fn hardware_key(reading: &SensorReading) -> &str {
    if !reading.root_hardware_id.is_empty() {
        &reading.root_hardware_id
    } else if !reading.hardware_id.is_empty() {
        &reading.hardware_id
    } else {
        &reading.hardware
    }
}
fn select<'a>(
    readings: &[&'a SensorReading],
    kind: &str,
    names: &[&str],
) -> Option<&'a SensorReading> {
    readings
        .iter()
        .copied()
        .filter(|r| r.sensor_type.eq_ignore_ascii_case(kind) && r.value.is_finite())
        .filter_map(|r| {
            let name = r.name.to_ascii_lowercase();
            names
                .iter()
                .position(|candidate| name.contains(candidate))
                .map(|rank| (rank, r))
        })
        .min_by(|(ar, a), (br, b)| {
            ar.cmp(br)
                .then_with(|| b.value.total_cmp(&a.value))
                .then_with(|| a.id.cmp(&b.id))
        })
        .map(|(_, r)| r)
}
fn mib(reading: Option<&SensorReading>) -> Option<f64> {
    reading
        .and_then(|r| match r.unit.as_str() {
            "MiB" | "MB" => Some(r.value),
            "GiB" | "GB" => Some(r.value * 1024.0),
            "B" => Some(r.value / 1_048_576.0),
            _ => None,
        })
        .filter(|value| value.is_finite() && *value >= 0.0)
}
pub fn summarise(readings: &[SensorReading]) -> SensorSummary {
    let valid = readings
        .iter()
        .filter(|r| r.value.is_finite())
        .collect::<Vec<_>>();
    let cpu = valid
        .iter()
        .copied()
        .filter(|r| r.hardware_type.eq_ignore_ascii_case("Cpu"))
        .collect::<Vec<_>>();
    let mut gpu_groups: BTreeMap<&str, Vec<&SensorReading>> = BTreeMap::new();
    for r in &valid {
        if r.hardware_type.to_ascii_lowercase().starts_with("gpu") {
            gpu_groups.entry(hardware_key(r)).or_default().push(r);
        }
    }
    // Select once for every GPU metric: discrete vendor, then stable hardware identifier.
    let gpu = gpu_groups
        .values()
        .min_by_key(|group| {
            let r = group[0];
            let rank = if r.hardware_type.eq_ignore_ascii_case("GpuNvidia") {
                0
            } else if r.hardware_type.eq_ignore_ascii_case("GpuAmd") {
                1
            } else {
                2
            };
            (rank, hardware_key(r))
        })
        .cloned()
        .unwrap_or_default();
    let mut summary = SensorSummary {
        cpu_temp_c: select(
            &cpu,
            "Temperature",
            &["package", "tctl/tdie", "tdie", "core max", "core"],
        )
        .map(|r| r.value),
        cpu_power_w: select(&cpu, "Power", &["package", "cores", "cpu"]).map(|r| r.value),
        gpu_name: gpu.first().map(|r| r.hardware.clone()),
        gpu_hardware_id: gpu.first().map(|r| hardware_key(r).to_string()),
        gpu_load_pct: select(
            &gpu,
            "Load",
            &["gpu core", "d3d 3d", "graphics", "gpu utilization"],
        )
        .map(|r| r.value.clamp(0.0, 100.0)),
        gpu_temp_c: select(
            &gpu,
            "Temperature",
            &["gpu core", "gpu temperature", "edge"],
        )
        .map(|r| r.value),
        gpu_hotspot_c: select(&gpu, "Temperature", &["hot spot", "hotspot", "junction"])
            .map(|r| r.value),
        gpu_clock_mhz: select(&gpu, "Clock", &["gpu core", "graphics"]).map(|r| r.value),
        gpu_power_w: select(
            &gpu,
            "Power",
            &["package", "board", "total", "gpu power", "gpu core"],
        )
        .map(|r| r.value),
        ..SensorSummary::default()
    };
    let clocks = cpu
        .iter()
        .filter(|r| r.sensor_type == "Clock" && r.name.to_ascii_lowercase().contains("core"))
        .map(|r| r.value)
        .collect::<Vec<_>>();
    if !clocks.is_empty() {
        summary.cpu_clock_mhz = Some(clocks.iter().sum::<f64>() / clocks.len() as f64);
    }
    summary.gpu_vram_used_mb = mib(
        select(&gpu, "SmallData", &["memory used", "dedicated memory"])
            .or_else(|| select(&gpu, "Data", &["memory used", "dedicated memory"])),
    );
    summary.gpu_vram_total_mb = mib(select(&gpu, "SmallData", &["memory total"])
        .or_else(|| select(&gpu, "Data", &["memory total"])));
    for r in valid {
        if r.sensor_type == "Fan" {
            summary.fan_rpm.push(r.clone());
        }
        if (r.hardware_type == "Storage" || r.hardware_type == "HDD")
            && r.sensor_type == "Temperature"
            && r.value > 0.0
            && !r.name.to_ascii_lowercase().contains("warning")
            && !r.name.to_ascii_lowercase().contains("critical")
        {
            summary.storage_temps.push(r.clone());
        }
    }
    summary
}
#[cfg(test)]
mod tests {
    use super::*;
    fn reading(
        id: &str,
        hardware_type: &str,
        sensor_type: &str,
        name: &str,
        value: f64,
    ) -> SensorReading {
        SensorReading {
            hardware_id: id.into(),
            hardware: id.into(),
            hardware_type: hardware_type.into(),
            sensor_type: sensor_type.into(),
            name: name.into(),
            value,
            ..SensorReading::default()
        }
    }
    #[test]
    fn package_priority_is_order_independent() {
        let mut readings = vec![
            reading("cpu", "Cpu", "Temperature", "CPU Package", 76.0),
            reading("cpu", "Cpu", "Temperature", "Core Max", 82.0),
        ];
        assert_eq!(summarise(&readings).cpu_temp_c, Some(76.0));
        readings.reverse();
        assert_eq!(summarise(&readings).cpu_temp_c, Some(76.0));
    }
    #[test]
    fn gpu_metrics_come_from_one_adapter() {
        let readings = vec![
            reading("igpu", "GpuIntel", "Load", "GPU Core", 98.0),
            reading("dgpu", "GpuNvidia", "Temperature", "GPU Core", 65.0),
            reading("dgpu", "GpuNvidia", "Temperature", "GPU Hot Spot", 78.0),
        ];
        let summary = summarise(&readings);
        assert_eq!(summary.gpu_hardware_id.as_deref(), Some("dgpu"));
        assert_eq!(summary.gpu_load_pct, None);
        assert_eq!(summary.gpu_temp_c, Some(65.0));
        assert_eq!(summary.gpu_hotspot_c, Some(78.0));
    }
    #[test]
    fn vram_units_and_non_finite_values() {
        let mut memory = reading("gpu", "GpuNvidia", "Data", "GPU Memory Total", 8.0);
        memory.unit = "GiB".into();
        assert_eq!(summarise(&[memory]).gpu_vram_total_mb, Some(8192.0));
        assert_eq!(
            summarise(&[reading(
                "cpu",
                "Cpu",
                "Temperature",
                "CPU Package",
                f64::NAN
            )])
            .cpu_temp_c,
            None
        );
    }
}
