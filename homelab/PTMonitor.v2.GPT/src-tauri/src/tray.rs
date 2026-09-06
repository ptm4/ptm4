use crate::{
    config::Config,
    stats::{Alert, Snapshot},
    TrayControls,
};
use std::{
    collections::BTreeMap,
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::{image::Image, AppHandle, Manager};
use tauri_plugin_notification::NotificationExt;

pub const TRAY_ID: &str = "ptmonitor-v2";
#[derive(Default)]
pub struct TrayState(Mutex<Cache>);
#[derive(Default)]
struct Cache {
    icon: Option<Signature>,
    tooltip: String,
    readings: String,
    previous_alerts: BTreeMap<String, String>,
    last_toast: Option<Instant>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Signature {
    bars: [Option<u8>; 3],
    fault: u8,
}

fn fault_alert(alert: &Alert) -> bool {
    alert.key.contains("temp") || alert.key.starts_with("disk_")
}
fn severity(level: &str) -> u8 {
    match level {
        "critical" => 2,
        "warning" => 1,
        _ => 0,
    }
}
fn signature(snapshot: &Snapshot) -> Signature {
    let bin = |value: Option<f64>| {
        value
            .filter(|v| v.is_finite())
            .map(|v| (v.clamp(0.0, 100.0) * 0.16).round() as u8)
    };
    Signature {
        bars: [
            bin((snapshot.sequence > 0).then_some(snapshot.cpu.usage_pct)),
            bin((snapshot.sequence > 0).then_some(snapshot.memory.usage_pct)),
            bin(snapshot.gpu.usage_pct),
        ],
        fault: snapshot
            .alerts
            .iter()
            .filter(|a| fault_alert(a))
            .map(|a| severity(&a.level))
            .max()
            .unwrap_or(0),
    }
}

pub fn update(app: &AppHandle, snapshot: &Snapshot) {
    let Some(icon) = app.tray_by_id(TRAY_ID) else {
        return;
    };
    let state = app.state::<TrayState>();
    let Ok(mut cache) = state.0.lock() else {
        return;
    };
    let next = signature(snapshot);
    if cache.icon != Some(next) && icon.set_icon(Some(render(next))).is_ok() {
        cache.icon = Some(next);
    }
    let tip = tooltip(snapshot);
    if cache.tooltip != tip && icon.set_tooltip(Some(&tip)).is_ok() {
        cache.tooltip = tip;
    }
    let readings = format!(
        "CPU {} · RAM {} · GPU {}",
        pct(Some(snapshot.cpu.usage_pct)),
        pct(Some(snapshot.memory.usage_pct)),
        pct(snapshot.gpu.usage_pct)
    );
    if cache.readings != readings {
        if let Some(controls) = app.try_state::<TrayControls>() {
            let _ = controls.readings.set_text(&readings);
        }
        cache.readings = readings;
    }
    let enabled = app
        .state::<Mutex<Config>>()
        .lock()
        .map(|c| c.toast_alerts)
        .unwrap_or(false);
    let new_alerts: Vec<_> = snapshot
        .alerts
        .iter()
        .filter(|a|
        // Busy CPU/GPU is expected during games; only visual load alerts.
        a.key!="cpu" && a.key!="gpu" && cache.previous_alerts.get(&a.key)!=Some(&a.level))
        .collect();
    if enabled
        && !new_alerts.is_empty()
        && cache
            .last_toast
            .is_none_or(|t| t.elapsed() >= Duration::from_secs(60))
    {
        let body = new_alerts
            .iter()
            .take(3)
            .map(|a| a.message.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        cache.last_toast = Some(Instant::now());
        if let Err(error) = app
            .notification()
            .builder()
            .title("PTMonitor v2 · workstation alert")
            .body(body)
            .show()
        {
            crate::report_error(app,format!("Windows notification unavailable (install the app to register notifications): {error}"));
        }
    }
    cache.previous_alerts = snapshot
        .alerts
        .iter()
        .map(|a| (a.key.clone(), a.level.clone()))
        .collect();
}

fn pct(value: Option<f64>) -> String {
    value
        .filter(|v| v.is_finite())
        .map(|v| format!("{:.0}%", v.clamp(0.0, 100.0)))
        .unwrap_or_else(|| "—".into())
}
fn temp(value: Option<f64>) -> String {
    value
        .filter(|v| v.is_finite())
        .map(|v| format!("{v:.0}°C"))
        .unwrap_or_else(|| "—".into())
}

pub fn tooltip(snapshot: &Snapshot) -> String {
    if snapshot.sequence == 0 {
        return "PTMonitor v2 · collecting first readings…".into();
    }
    let mut tip = format!(
        "PTMonitor v2\nCPU {} {} · RAM {}\nGPU {} {}\n↓ {} · ↑ {}",
        pct(Some(snapshot.cpu.usage_pct)),
        temp(snapshot.cpu.temp_c),
        pct(Some(snapshot.memory.usage_pct)),
        pct(snapshot.gpu.usage_pct),
        temp(snapshot.gpu.temp_c),
        if snapshot.network.available {
            format_rate(snapshot.network.rx_bytes_per_sec)
        } else {
            "—".into()
        },
        if snapshot.network.available {
            format_rate(snapshot.network.tx_bytes_per_sec)
        } else {
            "—".into()
        }
    );
    if let Some(alert) = snapshot.alerts.iter().max_by_key(|a| severity(&a.level)) {
        tip.push_str(&format!("\n! {}", alert.message));
    }
    // NOTIFYICONDATA.szTip is 128 UTF-16 code units, including its NUL terminator.
    bounded_tooltip(&tip)
}
fn bounded_tooltip(value: &str) -> String {
    let mut result = String::new();
    let mut used = 0;
    for character in value.chars() {
        if used + character.len_utf16() > 126 {
            result.push('…');
            break;
        }
        used += character.len_utf16();
        result.push(character);
    }
    result
}

fn render(signature: Signature) -> Image<'static> {
    // A 64px RGBA source remains sharp on 100–300% notification-area DPI.
    const SIZE: usize = 64;
    let mut pixels = vec![0u8; SIZE * SIZE * 4];
    let border = match signature.fault {
        2 => [255, 102, 114, 255],
        1 => [255, 193, 100, 255],
        _ => [111, 136, 158, 255],
    };
    for y in 0..SIZE {
        for x in 0..SIZE {
            let px = x as f64 / 2.0;
            let py = y as f64 / 2.0;
            let distance = |inset: f64, radius: f64| {
                let cx = px.clamp(inset + radius, 32.0 - inset - radius);
                let cy = py.clamp(inset + radius, 32.0 - inset - radius);
                ((px - cx).powi(2) + (py - cy).powi(2)).sqrt() <= radius
            };
            let mut color = if distance(1.5, 5.0) {
                border
            } else {
                [0, 0, 0, 0]
            };
            if distance(3.0, 3.5) {
                color = [12, 20, 29, 255];
            }
            for (i, bar) in signature.bars.iter().enumerate() {
                let left = 6.0 + i as f64 * 7.0;
                if px >= left && px < left + 5.0 && (8.0..24.0).contains(&py) {
                    color = match bar {
                        Some(height) if py >= 24.0 - *height as f64 => [
                            [103, 186, 255, 255],
                            [101, 230, 186, 255],
                            [180, 157, 255, 255],
                        ][i],
                        None if (16.0..18.0).contains(&py) => [134, 148, 164, 255],
                        _ => [37, 49, 64, 255],
                    };
                }
            }
            pixels[(y * SIZE + x) * 4..(y * SIZE + x) * 4 + 4].copy_from_slice(&color);
        }
    }
    Image::new_owned(pixels, SIZE as u32, SIZE as u32)
}

fn format_rate(bytes: f64) -> String {
    let bytes = if bytes.is_finite() {
        bytes.max(0.0)
    } else {
        0.0
    };
    if bytes >= 1_073_741_824.0 {
        format!("{:.1}GiB/s", bytes / 1_073_741_824.0)
    } else if bytes >= 1_048_576.0 {
        format!("{:.1}MiB/s", bytes / 1_048_576.0)
    } else {
        format!("{:.0}KiB/s", bytes / 1024.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tooltip_has_exact_values_and_fits_windows_buffer() {
        let mut s = Snapshot {
            sequence: 1,
            ..Default::default()
        };
        s.cpu.usage_pct = 42.0;
        s.gpu.temp_c = Some(67.0);
        s.alerts.push(Alert {
            key: "cpu_temp".into(),
            level: "critical".into(),
            message: "🌡".repeat(100),
            ..Default::default()
        });
        let text = tooltip(&s);
        assert!(text.contains("CPU 42%"));
        assert!(text.contains("67°C"));
        assert!(text.encode_utf16().count() <= 127);
    }
    #[test]
    fn critical_fault_beats_warning_and_busy_gpu_is_not_thermal_fault() {
        let mut s = Snapshot::default();
        for (key, level) in [
            ("gpu", "critical"),
            ("cpu_temp", "critical"),
            ("disk_C", "warning"),
        ] {
            s.alerts.push(Alert {
                key: key.into(),
                level: level.into(),
                ..Default::default()
            });
        }
        assert_eq!(signature(&s).fault, 2);
        s.alerts.retain(|a| a.key == "gpu");
        assert_eq!(signature(&s).fault, 0);
    }
    #[test]
    fn absent_gpu_is_not_zero_and_signature_ignores_subpixel_changes() {
        let mut s = Snapshot {
            sequence: 1,
            ..Default::default()
        };
        let a = signature(&s);
        s.cpu.usage_pct = 0.1;
        assert_eq!(a, signature(&s));
        s.gpu.usage_pct = Some(0.0);
        assert_ne!(a, signature(&s));
        assert_ne!(render(a).rgba(), render(signature(&s)).rgba());
    }
    #[test]
    fn raster_has_transparent_corners_and_high_dpi_dimensions() {
        let icon = render(signature(&Snapshot::default()));
        assert_eq!((icon.width(), icon.height()), (64, 64));
        assert_eq!(icon.rgba().len(), 64 * 64 * 4);
        assert_eq!(&icon.rgba()[0..4], &[0, 0, 0, 0]);
        assert_eq!(icon.rgba()[(32 * 64 + 32) * 4 + 3], 255);
    }
    #[test]
    fn formats_binary_rates_consistently() {
        assert_eq!(format_rate(1_048_576.0), "1.0MiB/s");
        assert_eq!(format_rate(-1.0), "0KiB/s");
    }
}
