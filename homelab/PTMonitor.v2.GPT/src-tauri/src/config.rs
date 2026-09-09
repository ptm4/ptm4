use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const CONFIG_VERSION: u8 = 3;
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
pub struct TaskbarConfig {
    pub enabled: bool,
    /// Persisted monitor identity. Never an HMONITOR, window handle, index or
    /// desktop coordinate — those do not survive reconnection.
    pub monitor_device_path: String,
    pub width_dip: u32,
    /// Set once the one-time first-run initialisation has fully succeeded, so
    /// startup and hidden-dashboard defaults are never re-applied on later runs.
    pub initialized: bool,
}

impl Default for TaskbarConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            monitor_device_path: String::new(),
            width_dip: crate::taskbar::DEFAULT_WIDTH_DIP,
            initialized: false,
        }
    }
}

impl TaskbarConfig {
    fn normalise(&mut self) {
        if !crate::taskbar::SUPPORTED_WIDTHS_DIP.contains(&self.width_dip) {
            self.width_dip = crate::taskbar::DEFAULT_WIDTH_DIP;
        }
        self.monitor_device_path = self.monitor_device_path.trim().to_string();
    }
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
    pub taskbar: TaskbarConfig,
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
            taskbar: TaskbarConfig::default(),
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
        self.taskbar.normalise();
    }

    /// One-time initialisation for the taskbar feature (plan Section 4). Runs
    /// only while `taskbar.initialized` is false, and is marked complete only
    /// after both the startup registration and the settings save succeed — so
    /// a failure retries next launch instead of silently half-applying.
    ///
    /// Later user changes to startup or dashboard visibility are preserved,
    /// because this never runs again once the flag is set.
    pub fn apply_taskbar_first_run(&mut self) -> Result<(), String> {
        if self.taskbar.initialized {
            return Ok(());
        }

        let previous_startup = self.startup;
        let previous_hidden = self.start_hidden;

        self.taskbar.enabled = true;
        // The monitor identity itself is resolved and persisted by the host,
        // which is the side that can enumerate display device paths.
        self.startup = true;
        self.start_hidden = true;

        if let Err(error) = set_startup(true) {
            self.startup = previous_startup;
            self.start_hidden = previous_hidden;
            return Err(error);
        }

        self.taskbar.initialized = true;
        if let Err(error) = self.save() {
            self.taskbar.initialized = false;
            self.startup = previous_startup;
            self.start_hidden = previous_hidden;
            let _ = set_startup(previous_startup);
            return Err(error);
        }
        Ok(())
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
        assert_eq!(cfg.version, CONFIG_VERSION);
        assert!(Config::path().ends_with("PTMonitor-v2/settings.json"));
    }

    #[test]
    fn v2_settings_migrate_to_v3_without_losing_user_choices() {
        // A realistic v2 file: no taskbar section at all.
        let raw = r#"{
            "version": 2,
            "opacity": 0.8,
            "startup": false,
            "startHidden": false,
            "selectedAdapter": "Ethernet",
            "toastAlerts": true
        }"#;
        let mut cfg: Config = serde_json::from_str(raw).unwrap();
        cfg.normalise();

        // Existing preferences survive untouched.
        assert_eq!(cfg.version, 3);
        assert_eq!(cfg.selected_adapter.as_deref(), Some("Ethernet"));
        assert!(cfg.toast_alerts);
        assert!((cfg.opacity - 0.8).abs() < f64::EPSILON);

        // The taskbar section materialises with defaults, not yet initialised.
        assert!(cfg.taskbar.enabled);
        assert!(!cfg.taskbar.initialized);
        assert_eq!(cfg.taskbar.width_dip, crate::taskbar::DEFAULT_WIDTH_DIP);
        assert!(cfg.taskbar.monitor_device_path.is_empty());
    }

    #[test]
    fn first_run_never_reapplies_over_later_user_choices() {
        // Once initialisation has completed, a user who later turns startup and
        // hidden-dashboard back off must keep those choices.
        let mut cfg = Config {
            startup: false,
            start_hidden: false,
            taskbar: TaskbarConfig {
                enabled: false,
                initialized: true,
                ..TaskbarConfig::default()
            },
            ..Config::default()
        };

        let before = cfg.clone();
        cfg.apply_taskbar_first_run()
            .expect("no-op when initialised");

        assert_eq!(cfg, before, "first-run must not run twice");
        assert!(!cfg.startup);
        assert!(!cfg.start_hidden);
        assert!(!cfg.taskbar.enabled);
    }

    #[test]
    fn taskbar_width_falls_back_to_a_supported_value() {
        let mut cfg = Config {
            taskbar: TaskbarConfig {
                width_dip: 999,
                ..TaskbarConfig::default()
            },
            ..Config::default()
        };
        cfg.normalise();
        assert_eq!(cfg.taskbar.width_dip, crate::taskbar::DEFAULT_WIDTH_DIP);

        for width in crate::taskbar::SUPPORTED_WIDTHS_DIP {
            let mut cfg = Config {
                taskbar: TaskbarConfig {
                    width_dip: width,
                    ..TaskbarConfig::default()
                },
                ..Config::default()
            };
            cfg.normalise();
            assert_eq!(cfg.taskbar.width_dip, width);
        }
    }
}
