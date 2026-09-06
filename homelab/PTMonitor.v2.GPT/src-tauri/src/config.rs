use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const CONFIG_VERSION: u8 = 2;
pub const APP_DATA_DIR: &str = "PTMonitor-v2";
pub const RUN_VALUE_NAME: &str = "PTMonitorV2";

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
#[serde(default, rename_all = "camelCase")]
pub struct Thresholds {
    pub cpu_warn_pct: f64,
    pub cpu_critical_pct: f64,
    pub gpu_warn_pct: f64,
    pub gpu_critical_pct: f64,
    pub ram_warn_pct: f64,
    pub ram_critical_pct: f64,
    pub disk_warn_pct: f64,
    pub disk_critical_pct: f64,
    pub cpu_temp_warn_c: f64,
    pub cpu_temp_critical_c: f64,
    pub gpu_temp_warn_c: f64,
    pub gpu_temp_critical_c: f64,
    pub disk_temp_warn_c: f64,
    pub disk_temp_critical_c: f64,
}

impl Default for Thresholds {
    fn default() -> Self {
        Self {
            cpu_warn_pct: 85.0,
            cpu_critical_pct: 95.0,
            gpu_warn_pct: 95.0,
            gpu_critical_pct: 99.0,
            ram_warn_pct: 85.0,
            ram_critical_pct: 95.0,
            disk_warn_pct: 80.0,
            disk_critical_pct: 90.0,
            cpu_temp_warn_c: 85.0,
            cpu_temp_critical_c: 95.0,
            gpu_temp_warn_c: 82.0,
            gpu_temp_critical_c: 90.0,
            disk_temp_warn_c: 60.0,
            disk_temp_critical_c: 70.0,
        }
    }
}

impl Thresholds {
    fn normalise(&mut self) {
        for (warn, critical) in [
            (&mut self.cpu_warn_pct, &mut self.cpu_critical_pct),
            (&mut self.gpu_warn_pct, &mut self.gpu_critical_pct),
            (&mut self.ram_warn_pct, &mut self.ram_critical_pct),
            (&mut self.disk_warn_pct, &mut self.disk_critical_pct),
        ] {
            normalise_pair(warn, critical, 100.0);
        }
        for (warn, critical) in [
            (&mut self.cpu_temp_warn_c, &mut self.cpu_temp_critical_c),
            (&mut self.gpu_temp_warn_c, &mut self.gpu_temp_critical_c),
            (&mut self.disk_temp_warn_c, &mut self.disk_temp_critical_c),
        ] {
            normalise_pair(warn, critical, 150.0);
        }
    }
}

fn normalise_pair(warn: &mut f64, critical: &mut f64, maximum: f64) {
    if !warn.is_finite() {
        *warn = maximum * 0.8;
    }
    if !critical.is_finite() {
        *critical = maximum * 0.9;
    }
    *warn = warn.clamp(1.0, maximum - 1.0);
    *critical = critical.clamp(*warn + 1.0, maximum);
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct WindowPosition {
    /// Native physical pixels. Keeping this physical avoids cross-DPI drift.
    pub x: i32,
    pub y: i32,
}

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
#[serde(default, rename_all = "camelCase")]
pub struct Config {
    pub version: u8,
    pub position: Option<WindowPosition>,
    pub opacity: f64,
    /// Background tint is independent of foreground readability.
    pub background_opacity: f64,
    pub startup: bool,
    pub start_hidden: bool,
    pub click_through: bool,
    pub expanded: bool,
    pub selected_adapter: Option<String>,
    pub toast_alerts: bool,
    pub advanced_sensors: bool,
    pub thresholds: Thresholds,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            version: CONFIG_VERSION,
            position: None,
            opacity: 1.0,
            background_opacity: 0.9,
            startup: false,
            start_hidden: false,
            click_through: false,
            expanded: false,
            selected_adapter: None,
            toast_alerts: false,
            advanced_sensors: false,
            thresholds: Thresholds::default(),
        }
    }
}

impl Config {
    pub fn path() -> PathBuf {
        dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(APP_DATA_DIR)
            .join("settings.json")
    }

    pub fn load() -> Self {
        let Ok(raw) = std::fs::read_to_string(Self::path()) else {
            return Self::default();
        };

        // This directory belongs exclusively to v2. Never read or migrate v1's settings.
        let mut cfg = serde_json::from_str::<Config>(&raw).unwrap_or_default();
        cfg.normalise();
        cfg
    }

    pub fn normalise(&mut self) {
        self.version = CONFIG_VERSION;
        self.opacity = if self.opacity.is_finite() {
            self.opacity.clamp(0.25, 1.0)
        } else {
            1.0
        };
        self.background_opacity = if self.background_opacity.is_finite() {
            self.background_opacity.clamp(0.25, 1.0)
        } else {
            0.9
        };
        self.selected_adapter = self
            .selected_adapter
            .take()
            .filter(|name| !name.trim().is_empty())
            .map(|name| name.trim().to_string());
        self.thresholds.normalise();
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("create settings directory: {e}"))?;
        }

        let json =
            serde_json::to_vec_pretty(self).map_err(|e| format!("serialise settings: {e}"))?;
        let tmp = path.with_extension("json.tmp");
        let mut file =
            std::fs::File::create(&tmp).map_err(|e| format!("create temporary settings: {e}"))?;
        file.write_all(&json)
            .and_then(|_| file.sync_all())
            .map_err(|e| format!("write temporary settings: {e}"))?;
        drop(file);
        // NTFS replaces an existing file for rename in current Rust/Windows builds. If another
        // program has locked it, leave the last known-good file in place and report the error.
        std::fs::rename(&tmp, &path).map_err(|e| {
            let _ = std::fs::remove_file(&tmp);
            format!("replace settings: {e}")
        })
    }
}

pub fn quoted_startup_command(exe: &Path) -> String {
    format!("\"{}\"", exe.display())
}

pub fn set_startup(enable: bool) -> Result<(), String> {
    use winreg::enums::{HKEY_CURRENT_USER, KEY_SET_VALUE};
    use winreg::RegKey;

    let exe = std::env::current_exe().map_err(|e| format!("find PTMonitor v2 executable: {e}"))?;
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let key = hkcu
        .open_subkey_with_flags(
            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            KEY_SET_VALUE,
        )
        .map_err(|e| format!("open startup registry key: {e}"))?;

    if enable {
        key.set_value(RUN_VALUE_NAME, &quoted_startup_command(&exe))
            .map_err(|e| format!("enable startup: {e}"))?;
    } else {
        match key.delete_value(RUN_VALUE_NAME) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(format!("disable startup: {e}")),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_startup_path_with_spaces() {
        assert_eq!(
            quoted_startup_command(Path::new(r"C:\Program Files\PTMonitor v2\PTMonitor v2.exe")),
            r#""C:\Program Files\PTMonitor v2\PTMonitor v2.exe""#
        );
    }

    #[test]
    fn normalises_unsafe_settings() {
        let mut cfg = Config {
            opacity: 99.0,
            selected_adapter: Some("   ".into()),
            thresholds: Thresholds {
                cpu_warn_pct: 98.0,
                cpu_critical_pct: 20.0,
                ..Thresholds::default()
            },
            ..Config::default()
        };
        cfg.normalise();
        assert_eq!(cfg.opacity, 1.0);
        assert_eq!(cfg.selected_adapter, None);
        assert!(cfg.thresholds.cpu_critical_pct > cfg.thresholds.cpu_warn_pct);
    }

    #[test]
    fn rejects_nonfinite_and_percentage_overflow() {
        let mut cfg = Config {
            opacity: f64::NAN,
            background_opacity: f64::INFINITY,
            ..Config::default()
        };
        cfg.thresholds.gpu_warn_pct = 200.0;
        cfg.thresholds.gpu_critical_pct = 300.0;
        cfg.thresholds.cpu_temp_warn_c = f64::NAN;
        cfg.normalise();
        assert_eq!(cfg.opacity, 1.0);
        assert_eq!(cfg.background_opacity, 0.9);
        assert_eq!(cfg.thresholds.gpu_warn_pct, 99.0);
        assert_eq!(cfg.thresholds.gpu_critical_pct, 100.0);
        assert!(cfg.thresholds.cpu_temp_warn_c.is_finite());
        assert!(serde_json::to_string(&cfg).is_ok());
    }

    #[test]
    fn defaults_keep_monitor_quiet_and_v1_isolated() {
        let cfg: Config = serde_json::from_str("{}").unwrap();
        assert!(!cfg.startup && !cfg.toast_alerts && !cfg.advanced_sensors);
        assert_eq!(cfg.version, 2);
        assert!(Config::path().ends_with("PTMonitor-v2/settings.json"));
    }
}
