use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Serialize, Deserialize, Clone)]
pub struct Config {
    #[serde(default)]
    pub initialized: bool, // false on first ever launch → position to bottom-right
    pub x: f64,
    pub y: f64,
    pub opacity: f64,
    pub startup: bool,
    pub start_hidden: bool,
    pub click_through: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            initialized: false,
            x: 0.0,
            y: 0.0,
            opacity: 1.0,
            startup: false,
            start_hidden: false,
            click_through: false,
        }
    }
}

impl Config {
    fn path() -> PathBuf {
        dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("PTMonitor")
            .join("settings.json")
    }

    pub fn load() -> Self {
        std::fs::read_to_string(Self::path())
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }

    pub fn save(&self) {
        let path = Self::path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(json) = serde_json::to_string_pretty(self) {
            let _ = std::fs::write(path, json);
        }
    }
}

pub fn set_startup(enable: bool) {
    use winreg::enums::*;
    use winreg::RegKey;

    let Ok(exe) = std::env::current_exe() else { return };
    let exe_path = exe.to_string_lossy().to_string();
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let Ok(key) = hkcu.open_subkey_with_flags(
        "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
        KEY_WRITE,
    ) else { return };

    if enable {
        let _ = key.set_value("PTMonitor", &exe_path);
    } else {
        let _ = key.delete_value("PTMonitor");
    }
}
