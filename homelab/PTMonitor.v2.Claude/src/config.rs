//! Settings v2: `%LOCALAPPDATA%\PTMonitor2\settings.json`. Every field has a default so new
//! keys never reset a user's file; unknown keys are ignored; writes are atomic; a corrupt file
//! is set aside as `.bak-<stamp>`. The legacy v1 file (`%LOCALAPPDATA%\PTMonitor\settings.json`)
//! is imported read-only exactly once and never written.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::gfx::backdrop::BackdropMode;
use crate::sample::GpuPref;
use crate::util;
use crate::win::window::Layer;

pub const SCHEMA: u32 = 2;
pub const OPACITY_PRESETS: [f32; 4] = [1.0, 0.75, 0.5, 0.25];

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct WindowPos {
    /// False → first-run placement (replaces v1 `initialized`).
    pub placed: bool,
    /// Physical px, virtual-screen coordinates.
    pub x: i32,
    pub y: i32,
    /// "DISPLAY1"
    pub monitor: String,
    pub dpi: u32,
}

impl Default for WindowPos {
    fn default() -> Self {
        WindowPos { placed: false, x: 0, y: 0, monitor: String::new(), dpi: 96 }
    }
}

/// `warp` (default): software D3D11 rasterizer — ~30 MB private, 15 threads, GPU untouched.
/// `hardware`: the vendor D3D11 driver — measured ~79 MB private and 59 threads on an RTX 4070 Ti.
#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum Renderer {
    #[default]
    Warp,
    Hardware,
}

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum UptimeMode {
    #[default]
    System,
    App,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct Config {
    pub schema: u32,
    pub window: WindowPos,
    pub opacity: f32,
    pub layer: Layer,
    pub backdrop: BackdropMode,
    pub click_through: bool,
    pub start_hidden: bool,
    pub autostart: bool,
    pub hotkey: String,
    pub game_mode: bool,
    pub sparklines: bool,
    pub interval_ms: u32,
    pub disks: Option<Vec<String>>,
    pub net_adapters: Option<Vec<String>>,
    pub gpu_source: GpuPref,
    pub uptime: UptimeMode,
    pub renderer: Renderer,
    pub migrated_from_v1: Option<String>,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            schema: SCHEMA,
            window: WindowPos::default(),
            opacity: 1.0,
            layer: Layer::Topmost,
            backdrop: BackdropMode::Auto,
            click_through: false,
            start_hidden: false,
            autostart: false,
            hotkey: "Ctrl+Alt+P".into(),
            game_mode: true,
            sparklines: true,
            interval_ms: 2000,
            disks: None,
            net_adapters: None,
            gpu_source: GpuPref::Auto,
            uptime: UptimeMode::System,
            renderer: Renderer::Warp,
            migrated_from_v1: None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LoadSource {
    V2,
    ImportedV1,
    Defaults,
    /// A v2 file existed but could not be parsed; it was renamed to `.bak-<stamp>`.
    CorruptReset,
}

impl Config {
    pub fn path() -> PathBuf {
        util::app_dir().join("settings.json")
    }

    /// Legacy PTMonitor v1 settings (read-only).
    pub fn legacy_path() -> PathBuf {
        util::local_app_data().join("PTMonitor").join("settings.json")
    }

    pub fn load() -> (Config, LoadSource) {
        Self::load_from(&Self::path(), &Self::legacy_path())
    }

    pub fn load_from(path: &Path, legacy: &Path) -> (Config, LoadSource) {
        if let Ok(text) = std::fs::read_to_string(path) {
            match serde_json::from_str::<Config>(&text) {
                Ok(mut cfg) => {
                    cfg.validate();
                    return (cfg, LoadSource::V2);
                }
                Err(e) => {
                    let bak = path.with_extension(format!("json.bak-{}", util::iso_now().replace([':', 'T'], "")));
                    let _ = std::fs::rename(path, &bak);
                    crate::logf!("settings.json unreadable ({e}); moved to {}", bak.display());
                    let mut cfg = Config::default();
                    cfg.validate();
                    return (cfg, LoadSource::CorruptReset);
                }
            }
        }
        if let Ok(text) = std::fs::read_to_string(legacy) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                let mut cfg = Config::from_v1(&v);
                cfg.validate();
                return (cfg, LoadSource::ImportedV1);
            }
        }
        let mut cfg = Config::default();
        cfg.validate();
        (cfg, LoadSource::Defaults)
    }

    /// Map the v1 shape `{initialized, x, y, opacity, startup, start_hidden, click_through}`.
    /// `startup` is deliberately NOT imported: v1's own Run entry may still exist.
    pub fn from_v1(v: &serde_json::Value) -> Config {
        let mut cfg = Config::default();
        let b = |k: &str| v.get(k).and_then(|x| x.as_bool()).unwrap_or(false);
        let f = |k: &str| v.get(k).and_then(|x| x.as_f64());
        cfg.window.placed = b("initialized");
        cfg.window.x = f("x").unwrap_or(0.0).round() as i32;
        cfg.window.y = f("y").unwrap_or(0.0).round() as i32;
        cfg.window.dpi = 96;
        cfg.opacity = f("opacity").unwrap_or(1.0) as f32;
        cfg.start_hidden = b("start_hidden");
        cfg.click_through = b("click_through");
        cfg.autostart = false;
        cfg.migrated_from_v1 = Some(util::iso_now());
        cfg
    }

    /// Clamp / snap everything to legal values.
    pub fn validate(&mut self) {
        self.schema = SCHEMA;
        self.opacity = OPACITY_PRESETS
            .iter()
            .copied()
            .min_by(|a, b| (a - self.opacity).abs().partial_cmp(&(b - self.opacity).abs()).unwrap())
            .unwrap_or(1.0);
        self.interval_ms = self.interval_ms.clamp(1000, 10_000);
        if self.window.dpi == 0 {
            self.window.dpi = 96;
        }
        if let Some(d) = &mut self.disks {
            d.retain(|s| !s.trim().is_empty());
            if d.is_empty() {
                self.disks = None;
            }
        }
        if let Some(n) = &mut self.net_adapters {
            n.retain(|s| !s.trim().is_empty());
            if n.is_empty() {
                self.net_adapters = None;
            }
        }
        self.hotkey = self.hotkey.trim().to_string();
    }

    pub fn save(&self) -> std::io::Result<()> {
        self.save_to(&Self::path())
    }

    /// Atomic: write `settings.json.tmp`, keep the previous file as `.bak`, rename over.
    pub fn save_to(&self, path: &Path) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let json = serde_json::to_string_pretty(self).map_err(std::io::Error::other)?;
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, json)?;
        if path.exists() {
            let _ = std::fs::copy(path, path.with_extension("json.bak"));
        }
        std::fs::rename(&tmp, path)
    }

    /// Ring capacity so sparklines span ~2 minutes at the configured interval.
    pub fn ring_capacity(&self) -> usize {
        (120_000 / self.interval_ms.max(500)).clamp(30, 240) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("ptm2-cfg-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn imports_v1_without_autostart() {
        let d = tmpdir("v1");
        let legacy = d.join("v1.json");
        std::fs::write(
            &legacy,
            r#"{"initialized":true,"x":2575.0,"y":886.0,"opacity":0.75,"startup":true,"start_hidden":false,"click_through":false}"#,
        )
        .unwrap();
        let (cfg, src) = Config::load_from(&d.join("missing.json"), &legacy);
        assert_eq!(src, LoadSource::ImportedV1);
        assert!(cfg.window.placed);
        assert_eq!((cfg.window.x, cfg.window.y), (2575, 886));
        assert_eq!(cfg.opacity, 0.75);
        assert!(!cfg.autostart, "v1 startup must not be imported");
        assert!(cfg.migrated_from_v1.is_some());
        // the legacy file is untouched
        assert!(legacy.exists());
    }

    #[test]
    fn defaults_when_nothing_exists() {
        let d = tmpdir("none");
        let (cfg, src) = Config::load_from(&d.join("a.json"), &d.join("b.json"));
        assert_eq!(src, LoadSource::Defaults);
        assert_eq!(cfg, { let mut c = Config::default(); c.validate(); c });
    }

    #[test]
    fn tolerates_unknown_keys_and_clamps() {
        let d = tmpdir("unknown");
        let p = d.join("settings.json");
        std::fs::write(&p, r#"{"schema":2,"opacity":0.6,"interval_ms":50,"future_key":{"x":1},"hotkey":"  Ctrl+Alt+P  "}"#).unwrap();
        let (cfg, src) = Config::load_from(&p, &d.join("none.json"));
        assert_eq!(src, LoadSource::V2);
        assert_eq!(cfg.opacity, 0.5);
        assert_eq!(cfg.interval_ms, 1000);
        assert_eq!(cfg.hotkey, "Ctrl+Alt+P");
        assert!(cfg.sparklines); // default kept
    }

    #[test]
    fn corrupt_file_is_set_aside() {
        let d = tmpdir("corrupt");
        let p = d.join("settings.json");
        std::fs::write(&p, "{ not json").unwrap();
        let (_, src) = Config::load_from(&p, &d.join("none.json"));
        assert_eq!(src, LoadSource::CorruptReset);
        assert!(!p.exists());
        assert!(std::fs::read_dir(&d).unwrap().any(|e| e.unwrap().file_name().to_string_lossy().contains(".bak-")));
    }

    #[test]
    fn save_roundtrip_and_backup() {
        let d = tmpdir("save");
        let p = d.join("settings.json");
        let mut cfg = Config {
            window: WindowPos { placed: true, x: 10, y: 20, monitor: "DISPLAY2".into(), dpi: 120 },
            layer: Layer::Desktop,
            backdrop: BackdropMode::Mica,
            ..Default::default()
        };
        cfg.save_to(&p).unwrap();
        cfg.opacity = 0.5;
        cfg.save_to(&p).unwrap();
        assert!(d.join("settings.json.bak").exists());
        assert!(!d.join("settings.json.tmp").exists());
        let (back, src) = Config::load_from(&p, &d.join("none.json"));
        assert_eq!(src, LoadSource::V2);
        assert_eq!(back, cfg);
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(text.contains("\"layer\": \"desktop\""));
        assert!(text.contains("\"backdrop\": \"mica\""));
    }
}
