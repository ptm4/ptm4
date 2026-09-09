//! Live taskbar readings: snapshot projection, formatting, and supervision of
//! the native `PTMonitor.TaskbarHost.exe` helper.
//!
//! The collector thread only ever drops a formatted payload into a
//! latest-value mailbox and returns; a dedicated writer thread owns the pipe
//! to the host so pipe I/O, process waits and Explorer calls never happen on
//! the sampling thread.

use std::io::Write;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::thread;

use crate::stats::Snapshot;

static SUPERVISOR: OnceLock<Option<TaskbarSupervisor>> = OnceLock::new();

/// Starts the taskbar integration once, at application startup.
pub fn init(enabled: bool, monitor_device_path: String, width_dip: u32) {
    let _ = SUPERVISOR.get_or_init(|| start(enabled, monitor_device_path, width_dip));
}

/// Called from the collector immediately after a snapshot is published, so the
/// panel updates regardless of whether the dashboard is visible.
pub fn publish_snapshot(snapshot: &Snapshot) {
    if let Some(Some(supervisor)) = SUPERVISOR.get() {
        supervisor.publish(snapshot, snapshot.sequence > 0);
    }
}

/// Pushes changed settings to the running host without restarting it.
pub fn reconfigure(enabled: bool, monitor_device_path: &str, width_dip: u32) {
    if let Some(Some(supervisor)) = SUPERVISOR.get() {
        supervisor.reconfigure(enabled, monitor_device_path, width_dip);
    }
}

pub fn shutdown() {
    if let Some(Some(supervisor)) = SUPERVISOR.get() {
        supervisor.stop();
    }
}

pub const PROTOCOL_VERSION: u32 = 1;
pub const DEFAULT_WIDTH_DIP: u32 = 220;
pub const SUPPORTED_WIDTHS_DIP: [u32; 3] = [220, 280, 340];

const EM_DASH: &str = "\u{2014}";
const MAX_CELL_UTF16: usize = 63;
const MAX_TOOLTIP_UTF16: usize = 511;

/// The six formatted cells plus the tooltip, exactly as the panel renders them.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct TaskbarPayload {
    pub source_sequence: String,
    pub cells: [String; 6],
    pub tooltip: String,
}

fn format_percent(value: Option<f64>) -> String {
    match value {
        Some(v) if v.is_finite() => format!("{}%", v.clamp(0.0, 100.0).round() as i64),
        _ => EM_DASH.to_string(),
    }
}

fn format_celsius(value: Option<f64>) -> String {
    match value {
        Some(v) if v.is_finite() => format!("{}\u{00B0}C", v.round() as i64),
        _ => EM_DASH.to_string(),
    }
}

/// Binary units, KiB/s with no decimals and larger units with one. A value
/// that would round to `1024.0` of the smaller unit is promoted instead.
fn format_rate(bytes_per_sec: Option<f64>) -> String {
    let Some(value) = bytes_per_sec else {
        return EM_DASH.to_string();
    };
    if !value.is_finite() || value < 0.0 {
        return EM_DASH.to_string();
    }

    const UNITS: [&str; 4] = ["KiB/s", "MiB/s", "GiB/s", "TiB/s"];
    let mut amount = value / 1024.0; // start in KiB/s
    let mut unit = 0usize;

    while unit < UNITS.len() - 1 {
        let rounded = if unit == 0 {
            amount.round()
        } else {
            (amount * 10.0).round() / 10.0
        };
        if rounded < 1024.0 {
            break;
        }
        amount /= 1024.0;
        unit += 1;
    }

    if unit == 0 {
        format!("{} {}", amount.round() as i64, UNITS[unit])
    } else {
        format!("{:.1} {}", amount, UNITS[unit])
    }
}

fn truncate_utf16(value: &str, max_units: usize) -> String {
    if value.encode_utf16().count() <= max_units {
        return value.to_string();
    }
    let mut out = String::new();
    let mut units = 0usize;
    for ch in value.chars() {
        let width = ch.len_utf16();
        if units + width > max_units {
            break; // never split a surrogate pair
        }
        out.push(ch);
        units += width;
    }
    out
}

/// Projects only what the panel displays. No process lists, sensor inventories
/// or history are cloned or transmitted.
pub fn project(snapshot: &Snapshot, has_sampled: bool) -> TaskbarPayload {
    let cpu_usage = if has_sampled {
        Some(snapshot.cpu.usage_pct)
    } else {
        None
    };
    let ram_usage = if has_sampled {
        Some(snapshot.memory.usage_pct)
    } else {
        None
    };

    let cpu_cell = format!(
        "CPU {}  {}",
        format_percent(cpu_usage),
        format_celsius(snapshot.cpu.temp_c)
    );
    let ram_cell = format!("RAM {}", format_percent(ram_usage));
    let gpu_cell = format!("GPU {}", format_percent(snapshot.gpu.usage_pct));
    let gpu_temp_cell = format_celsius(snapshot.gpu.temp_c);

    let (rx, tx) = if snapshot.network.available {
        (
            Some(snapshot.network.rx_bytes_per_sec),
            Some(snapshot.network.tx_bytes_per_sec),
        )
    } else {
        (None, None)
    };
    let down_cell = format!("\u{2193} {}", format_rate(rx));
    let up_cell = format!("\u{2191} {}", format_rate(tx));

    let tooltip = format!(
        "PTMonitor \u{2014} CPU {} ({}), RAM {}, GPU {} ({}), down {}, up {}",
        format_percent(cpu_usage),
        format_celsius(snapshot.cpu.temp_c),
        format_percent(ram_usage),
        format_percent(snapshot.gpu.usage_pct),
        format_celsius(snapshot.gpu.temp_c),
        format_rate(rx),
        format_rate(tx)
    );

    TaskbarPayload {
        // Decimal string: JSON numbers would lose precision on large sequences.
        source_sequence: snapshot.sequence.to_string(),
        cells: [
            truncate_utf16(&cpu_cell, MAX_CELL_UTF16),
            truncate_utf16(&ram_cell, MAX_CELL_UTF16),
            truncate_utf16(&gpu_cell, MAX_CELL_UTF16),
            truncate_utf16(&gpu_temp_cell, MAX_CELL_UTF16),
            truncate_utf16(&down_cell, MAX_CELL_UTF16),
            truncate_utf16(&up_cell, MAX_CELL_UTF16),
        ],
        tooltip: truncate_utf16(&tooltip, MAX_TOOLTIP_UTF16),
    }
}

fn json_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

pub fn snapshot_frame(payload: &TaskbarPayload) -> String {
    let cells = payload
        .cells
        .iter()
        .map(|c| format!("\"{}\"", json_escape(c)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "{{\"protocolVersion\":{},\"type\":\"snapshot\",\"sourceSequence\":\"{}\",\"cells\":[{}],\"tooltip\":\"{}\"}}",
        PROTOCOL_VERSION,
        json_escape(&payload.source_sequence),
        cells,
        json_escape(&payload.tooltip)
    )
}

pub fn configure_frame(enabled: bool, monitor_device_path: &str, width_dip: u32) -> String {
    format!(
        "{{\"protocolVersion\":{},\"type\":\"configure\",\"enabled\":{},\"monitorDevicePath\":\"{}\",\"widthDip\":{}}}",
        PROTOCOL_VERSION,
        enabled,
        json_escape(monitor_device_path),
        width_dip
    )
}

/// Latest-value mailbox: the sampler overwrites the pending payload and
/// returns immediately. A slow writer may miss intermediate samples but never
/// the newest one.
#[derive(Default)]
struct Mailbox {
    pending: Mutex<Option<TaskbarPayload>>,
    signal: Condvar,
}

impl Mailbox {
    fn put(&self, payload: TaskbarPayload) {
        if let Ok(mut slot) = self.pending.lock() {
            *slot = Some(payload);
        }
        self.signal.notify_one();
    }

    fn take_blocking(&self, stop: &AtomicBool) -> Option<TaskbarPayload> {
        let mut slot = self.pending.lock().ok()?;
        loop {
            if stop.load(Ordering::Acquire) {
                return None;
            }
            if let Some(payload) = slot.take() {
                return Some(payload);
            }
            let (next, _) = self
                .signal
                .wait_timeout(slot, std::time::Duration::from_millis(500))
                .ok()?;
            slot = next;
        }
    }
}

/// Configuration the writer thread applies, and re-sends whenever the host is
/// (re)started so a restarted host never runs with stale settings.
#[derive(Debug, Clone, PartialEq, Eq)]
struct HostConfig {
    enabled: bool,
    monitor_device_path: String,
    width_dip: u32,
}

pub struct TaskbarSupervisor {
    mailbox: Arc<Mailbox>,
    stop: Arc<AtomicBool>,
    config: Arc<Mutex<HostConfig>>,
    config_dirty: Arc<AtomicBool>,
}

impl TaskbarSupervisor {
    /// Publishes a snapshot. Called from the sampling thread; never blocks on
    /// pipe I/O.
    pub fn publish(&self, snapshot: &Snapshot, has_sampled: bool) {
        self.mailbox.put(project(snapshot, has_sampled));
    }

    fn reconfigure(&self, enabled: bool, monitor_device_path: &str, width_dip: u32) {
        if let Ok(mut config) = self.config.lock() {
            *config = HostConfig {
                enabled,
                monitor_device_path: monitor_device_path.to_string(),
                width_dip,
            };
        }
        self.config_dirty.store(true, Ordering::Release);
        self.mailbox.signal.notify_all();
    }

    pub fn stop(&self) {
        self.stop.store(true, Ordering::Release);
        self.mailbox.signal.notify_all();
    }
}

fn host_executable_path() -> Option<std::path::PathBuf> {
    // Resolve only from the installed application directory; a development
    // fallback is permitted in debug builds alone (plan Section 5).
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let candidate = dir.join("PTMonitor.TaskbarHost.exe");
    if candidate.exists() {
        return Some(candidate);
    }
    #[cfg(debug_assertions)]
    {
        let dev = dir
            .join("..")
            .join("..")
            .join("..")
            .join("taskbar-native")
            .join("build")
            .join("PTMonitor.TaskbarHost.exe");
        if dev.exists() {
            return Some(dev);
        }
    }
    None
}

fn spawn_host() -> Option<Child> {
    let path = host_executable_path()?;
    let mut command = Command::new(path);
    command.stdin(Stdio::piped()).stdout(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command.spawn().ok()
}

/// Starts the writer/supervisor thread. Returns `None` when the host binary is
/// not present, in which case PTMonitor runs exactly as it did before.
pub fn start(
    enabled: bool,
    monitor_device_path: String,
    width_dip: u32,
) -> Option<TaskbarSupervisor> {
    host_executable_path()?;

    let mailbox = Arc::new(Mailbox::default());
    let stop = Arc::new(AtomicBool::new(false));
    let config = Arc::new(Mutex::new(HostConfig {
        enabled,
        monitor_device_path,
        width_dip,
    }));
    let config_dirty = Arc::new(AtomicBool::new(false));

    let writer_mailbox = Arc::clone(&mailbox);
    let writer_stop = Arc::clone(&stop);
    let writer_config = Arc::clone(&config);
    let writer_dirty = Arc::clone(&config_dirty);
    thread::Builder::new()
        .name("ptmonitor-taskbar".into())
        .spawn(move || {
            let mut child: Option<Child> = None;
            let mut last_payload: Option<TaskbarPayload> = None;

            let current_config = |config: &Mutex<HostConfig>| {
                config
                    .lock()
                    .map(|c| c.clone())
                    .unwrap_or_else(|_| HostConfig {
                        enabled: true,
                        monitor_device_path: String::new(),
                        width_dip: DEFAULT_WIDTH_DIP,
                    })
            };

            while !writer_stop.load(Ordering::Acquire) {
                // (Re)start the host if it is missing or has exited.
                let needs_start = match child.as_mut() {
                    None => true,
                    Some(c) => matches!(c.try_wait(), Ok(Some(_)) | Err(_)),
                };
                if needs_start {
                    child = spawn_host();
                    if let Some(c) = child.as_mut() {
                        let cfg = current_config(&writer_config);
                        if let Some(stdin) = c.stdin.as_mut() {
                            let _ = writeln!(
                                stdin,
                                "{}",
                                configure_frame(
                                    cfg.enabled,
                                    &cfg.monitor_device_path,
                                    cfg.width_dip
                                )
                            );
                            // Send the newest reading immediately after
                            // configuration so the panel is never blank.
                            if let Some(payload) = last_payload.as_ref() {
                                let _ = writeln!(stdin, "{}", snapshot_frame(payload));
                            }
                            let _ = stdin.flush();
                        }
                        writer_dirty.store(false, Ordering::Release);
                    } else {
                        thread::sleep(std::time::Duration::from_secs(5));
                        continue;
                    }
                }

                // Settings changed while the host is running: re-send them.
                if writer_dirty.swap(false, Ordering::AcqRel) {
                    let cfg = current_config(&writer_config);
                    if let Some(c) = child.as_mut() {
                        if let Some(stdin) = c.stdin.as_mut() {
                            let _ = writeln!(
                                stdin,
                                "{}",
                                configure_frame(
                                    cfg.enabled,
                                    &cfg.monitor_device_path,
                                    cfg.width_dip
                                )
                            );
                            let _ = stdin.flush();
                        }
                    }
                }

                let Some(payload) = writer_mailbox.take_blocking(&writer_stop) else {
                    continue;
                };
                last_payload = Some(payload.clone());

                if let Some(c) = child.as_mut() {
                    if let Some(stdin) = c.stdin.as_mut() {
                        if writeln!(stdin, "{}", snapshot_frame(&payload)).is_err()
                            || stdin.flush().is_err()
                        {
                            let _ = c.kill();
                            child = None;
                        }
                    }
                }
            }

            // Closing stdin asks the host to shut down; reap it afterwards.
            if let Some(mut c) = child {
                drop(c.stdin.take());
                let _ = c.wait();
            }
        })
        .ok()?;

    Some(TaskbarSupervisor {
        mailbox,
        stop,
        config,
        config_dirty,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::stats::Snapshot;

    fn sample() -> Snapshot {
        Snapshot {
            cpu: crate::stats::CpuStat {
                usage_pct: 47.0,
                temp_c: None,
                ..Default::default()
            },
            memory: crate::stats::MemoryStat {
                usage_pct: 59.0,
                ..Default::default()
            },
            gpu: crate::stats::GpuStat {
                usage_pct: Some(38.0),
                temp_c: Some(44.0),
                ..Default::default()
            },
            network: crate::stats::NetworkStat {
                available: true,
                rx_bytes_per_sec: 4.0 * 1024.0,
                tx_bytes_per_sec: 6.0 * 1024.0,
                ..Default::default()
            },
            ..Snapshot::default()
        }
    }

    #[test]
    fn formats_the_supplied_screenshot_values_exactly() {
        let payload = project(&sample(), true);
        assert_eq!(payload.cells[0], "CPU 47%  \u{2014}");
        assert_eq!(payload.cells[1], "RAM 59%");
        assert_eq!(payload.cells[2], "GPU 38%");
        assert_eq!(payload.cells[3], "44\u{00B0}C");
        assert_eq!(payload.cells[4], "\u{2193} 4 KiB/s");
        assert_eq!(payload.cells[5], "\u{2191} 6 KiB/s");
    }

    #[test]
    fn missing_sensors_differ_from_genuine_zero() {
        let mut s = sample();
        s.gpu.usage_pct = None;
        assert_eq!(project(&s, true).cells[2], "GPU \u{2014}");

        s.gpu.usage_pct = Some(0.0);
        assert_eq!(project(&s, true).cells[2], "GPU 0%");

        s.network.available = true;
        s.network.rx_bytes_per_sec = 0.0;
        assert_eq!(project(&s, true).cells[4], "\u{2193} 0 KiB/s");

        s.network.available = false;
        assert_eq!(project(&s, true).cells[4], "\u{2193} \u{2014}");
    }

    #[test]
    fn usage_is_unavailable_before_the_first_snapshot() {
        let payload = project(&sample(), false);
        assert_eq!(payload.cells[0], "CPU \u{2014}  \u{2014}");
        assert_eq!(payload.cells[1], "RAM \u{2014}");
    }

    #[test]
    fn nonfinite_input_is_rejected() {
        let mut s = sample();
        s.cpu.usage_pct = f64::NAN;
        s.gpu.temp_c = Some(f64::INFINITY);
        s.network.rx_bytes_per_sec = f64::NAN;
        let payload = project(&s, true);
        assert_eq!(payload.cells[0], "CPU \u{2014}  \u{2014}");
        assert_eq!(payload.cells[3], "\u{2014}");
        assert_eq!(payload.cells[4], "\u{2193} \u{2014}");
    }

    #[test]
    fn rounding_and_network_unit_boundaries() {
        assert_eq!(format_rate(Some(0.0)), "0 KiB/s");
        assert_eq!(format_rate(Some(1023.0 * 1024.0)), "1023 KiB/s");
        // Rounding to 1024.0 of the smaller unit promotes instead.
        assert_eq!(format_rate(Some(1023.7 * 1024.0)), "1.0 MiB/s");
        assert_eq!(format_rate(Some(1024.0 * 1024.0)), "1.0 MiB/s");
        assert_eq!(format_rate(Some(1536.0 * 1024.0)), "1.5 MiB/s");
        assert_eq!(format_rate(Some(1024.0 * 1024.0 * 1024.0)), "1.0 GiB/s");
        assert_eq!(
            format_rate(Some(1024.0 * 1024.0 * 1024.0 * 1024.0)),
            "1.0 TiB/s"
        );
        assert_eq!(format_percent(Some(99.5)), "100%");
        assert_eq!(format_percent(Some(150.0)), "100%");
        assert_eq!(format_percent(Some(-5.0)), "0%");
        assert_eq!(format_celsius(Some(44.4)), "44\u{00B0}C");
        assert_eq!(format_celsius(Some(44.6)), "45\u{00B0}C");
    }

    #[test]
    fn cells_stay_within_protocol_limits_without_splitting_surrogates() {
        // An astral-plane character occupies two UTF-16 units.
        let emoji = "\u{1F600}".repeat(40);
        let truncated = truncate_utf16(&emoji, MAX_CELL_UTF16);
        let units = truncated.encode_utf16().count();
        assert!(units <= MAX_CELL_UTF16);
        assert_eq!(units % 2, 0, "a surrogate pair was split");
    }

    #[test]
    fn mailbox_replacement_keeps_the_newest_sample() {
        let mailbox = Mailbox::default();
        let stop = AtomicBool::new(false);

        let first = TaskbarPayload {
            source_sequence: "1".into(),
            ..TaskbarPayload::default()
        };
        let second = TaskbarPayload {
            source_sequence: "2".into(),
            ..TaskbarPayload::default()
        };

        mailbox.put(first);
        mailbox.put(second); // slow consumer: the older sample is replaced

        let taken = mailbox.take_blocking(&stop).expect("payload");
        assert_eq!(taken.source_sequence, "2");
    }

    #[test]
    fn frames_are_valid_single_line_json_within_the_size_limit() {
        let payload = project(&sample(), true);
        let frame = snapshot_frame(&payload);
        assert!(!frame.contains('\n'));
        assert!(frame.len() <= 16 * 1024);
        assert!(frame.starts_with("{\"protocolVersion\":1,\"type\":\"snapshot\""));

        let configure = configure_frame(true, "\\\\?\\DISPLAY#ABC", 220);
        assert!(!configure.contains('\n'));
        assert!(configure.contains("\\\\\\\\?\\\\DISPLAY#ABC"));
    }
}
