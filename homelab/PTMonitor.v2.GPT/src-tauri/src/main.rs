#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod alerts;
mod config;
mod pdh;
mod placement;
mod platform;
mod sensor;
mod stats;
mod taskbar;
mod tray;

use config::{Config, Thresholds};
use serde::{Deserialize, Deserializer};
use std::sync::Mutex;
use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, LogicalSize, Manager,
};

const COLLAPSED_SIZE: (f64, f64) = (312.0, 452.0);
const EXPANDED_SIZE: (f64, f64) = (580.0, 720.0);

struct TrayControls {
    readings: MenuItem<tauri::Wry>,
    startup: CheckMenuItem<tauri::Wry>,
    start_hidden: CheckMenuItem<tauri::Wry>,
    click_through: CheckMenuItem<tauri::Wry>,
    toast_alerts: CheckMenuItem<tauri::Wry>,
    taskbar_readings: CheckMenuItem<tauri::Wry>,
    taskbar_width: MenuItem<tauri::Wry>,
}

// serde's ordinary nested Option collapses explicit null and missing fields.
fn nullable<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<Option<String>>, D::Error> {
    Option::<String>::deserialize(deserializer).map(Some)
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SettingsPatch {
    opacity: Option<f64>,
    background_opacity: Option<f64>,
    startup: Option<bool>,
    start_hidden: Option<bool>,
    click_through: Option<bool>,
    expanded: Option<bool>,
    #[serde(default, deserialize_with = "nullable")]
    selected_adapter: Option<Option<String>>,
    toast_alerts: Option<bool>,
    advanced_sensors: Option<bool>,
    thresholds: Option<Thresholds>,
}

fn main() {
    platform::wait_for_handoff();
    let mut initial_config = Config::load();
    // First run of the taskbar feature enables it, starts at login and keeps
    // the dashboard hidden. Marked complete only on success, so a failure
    // retries next launch rather than half-applying.
    if let Err(error) = initial_config.apply_taskbar_first_run() {
        eprintln!("taskbar first-run initialisation deferred: {error}");
    }
    let initial_config = initial_config;
    let app_state = stats::AppState::new();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Err(error) = mutate_config(app, |c| c.click_through = false) {
                report_error(app, error);
            }
            show_dashboard(app.clone());
        }))
        .plugin(tauri_plugin_notification::init())
        .manage(Mutex::new(initial_config.clone()))
        .manage(app_state.clone())
        .manage(placement::Placement::default())
        .manage(tray::TrayState::default())
        .setup(move |app| {
            let window = app.get_webview_window("main").expect("main window");
            apply_window_state(&window, &initial_config).map_err(std::io::Error::other)?;
            if initial_config.position.is_some() {
                placement::recover(&window, initial_config.position);
            } else {
                placement::snap(&window);
            }
            // Native acrylic falls back to the readable CSS tint if unavailable/disabled by Windows.
            apply_window_state(&window, &initial_config).map_err(std::io::Error::other)?;
            let _ = window.set_effects(tauri::utils::config::WindowEffectsConfig {
                effects: vec![tauri::utils::WindowEffect::Acrylic],
                ..Default::default()
            });
            let controls = build_tray(app, &initial_config)?;
            app.manage(controls);
            placement::attach(&window);
            if !initial_config.start_hidden {
                window.show()?;
            }
            taskbar::init(
                initial_config.taskbar.enabled,
                initial_config.taskbar.monitor_device_path.clone(),
                initial_config.taskbar.width_dip,
            );
            stats::start_collector(app.handle().clone(), app_state.clone());
            Ok(())
        })
        .on_menu_event(|app, event| handle_menu(app, event.id.as_ref()))
        .on_tray_icon_event(|app, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_dashboard(app);
            }
        })
        .invoke_handler(tauri::generate_handler![
            stats::get_snapshot,
            stats::get_inventory,
            stats::get_history,
            stats::get_diagnostics,
            get_settings,
            update_settings,
            show_dashboard,
            hide_dashboard,
            set_interaction_mode,
            snap_to_current_monitor,
            refresh_snapshot,
            restart_elevated,
            quit_app,
        ])
        .build(tauri::generate_context!())
        .expect("error while building PTMonitor v2");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            placement::flush(app);
            app.state::<stats::AppState>().stop();
            // Closing the host's stdin makes it remove the panel and restore
            // the taskbar's original layout.
            taskbar::shutdown();
        }
    });
}

fn build_tray(app: &tauri::App, config: &Config) -> tauri::Result<TrayControls> {
    let readings = MenuItem::with_id(
        app,
        "readings",
        "Collecting workstation readings…",
        false,
        None::<&str>,
    )?;
    let show = MenuItem::with_id(
        app,
        "toggle",
        "Show / Hide PTMonitor v2",
        true,
        None::<&str>,
    )?;
    let settings = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
    let refresh = MenuItem::with_id(app, "refresh", "Refresh readings", true, None::<&str>)?;
    let interact = MenuItem::with_id(
        app,
        "interact",
        "Recover interaction (disable click-through)",
        true,
        None::<&str>,
    )?;
    let snap = MenuItem::with_id(app, "snap", "Snap to monitor corner", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let startup = CheckMenuItem::with_id(
        app,
        "startup",
        "Launch on startup",
        true,
        config.startup,
        None::<&str>,
    )?;
    let start_hidden = CheckMenuItem::with_id(
        app,
        "start_hidden",
        "Start hidden",
        true,
        config.start_hidden,
        None::<&str>,
    )?;
    let click_through = CheckMenuItem::with_id(
        app,
        "click_through",
        "Click-through mode",
        true,
        config.click_through,
        None::<&str>,
    )?;
    let toast_alerts = CheckMenuItem::with_id(
        app,
        "toast_alerts",
        "Windows alert notifications",
        true,
        config.toast_alerts,
        None::<&str>,
    )?;
    let taskbar_readings = CheckMenuItem::with_id(
        app,
        "taskbar_readings",
        "Show live taskbar readings",
        true,
        config.taskbar.enabled,
        None::<&str>,
    )?;
    let taskbar_width = MenuItem::with_id(
        app,
        "taskbar_width",
        taskbar_width_label(config.taskbar.width_dip),
        true,
        None::<&str>,
    )?;
    let separator_two = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit PTMonitor v2", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &readings,
            &show,
            &settings,
            &refresh,
            &interact,
            &snap,
            &separator,
            &startup,
            &start_hidden,
            &click_through,
            &toast_alerts,
            &taskbar_readings,
            &taskbar_width,
            &separator_two,
            &quit,
        ],
    )?;
    TrayIconBuilder::with_id(tray::TRAY_ID)
        .icon(app.default_window_icon().expect("default icon").clone())
        .tooltip("PTMonitor v2 · starting")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .build(app)?;
    Ok(TrayControls {
        readings,
        startup,
        start_hidden,
        click_through,
        toast_alerts,
        taskbar_readings,
        taskbar_width,
    })
}

fn taskbar_width_label(width_dip: u32) -> String {
    format!("Taskbar panel width: {width_dip} DIP (click to change)")
}

fn handle_menu(app: &tauri::AppHandle, id: &str) {
    let result = match id {
        "quit" => {
            app.exit(0);
            Ok(())
        }
        "toggle" => {
            toggle_dashboard(app);
            Ok(())
        }
        "refresh" => {
            app.state::<stats::AppState>().request_refresh();
            Ok(())
        }
        "interact" => {
            mutate_config(app, |c| c.click_through = false).map(|_| show_dashboard(app.clone()))
        }
        "settings" => mutate_config(app, |c| {
            c.click_through = false;
            c.expanded = true;
        })
        .map(|_| {
            show_dashboard(app.clone());
            let _ = app.emit("ptmonitor://open-settings", ());
        }),
        "snap" => {
            if let Some(window) = app.get_webview_window("main") {
                placement::snap(&window);
            }
            Ok(())
        }
        "startup" => mutate_config(app, |c| c.startup = !c.startup).map(|_| ()),
        "start_hidden" => mutate_config(app, |c| c.start_hidden = !c.start_hidden).map(|_| ()),
        "click_through" => mutate_config(app, |c| c.click_through = !c.click_through).map(|_| ()),
        "toast_alerts" => mutate_config(app, |c| c.toast_alerts = !c.toast_alerts).map(|_| ()),
        "taskbar_readings" => {
            mutate_config(app, |c| c.taskbar.enabled = !c.taskbar.enabled).map(|_| ())
        }
        // Cycles through the three supported body widths (plan Section 4).
        "taskbar_width" => mutate_config(app, |c| {
            let widths = taskbar::SUPPORTED_WIDTHS_DIP;
            let index = widths
                .iter()
                .position(|w| *w == c.taskbar.width_dip)
                .unwrap_or(0);
            c.taskbar.width_dip = widths[(index + 1) % widths.len()];
        })
        .map(|_| ()),
        _ => Ok(()),
    };
    if let Err(error) = result {
        report_error(app, error);
    }
}

pub(crate) fn report_error(app: &tauri::AppHandle, error: String) {
    eprintln!("PTMonitor v2: {error}");
    let _ = app.emit("ptmonitor://error", error);
}

fn toggle_dashboard(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            show_dashboard(app.clone());
        }
    }
}

fn mutate_config(
    app: &tauri::AppHandle,
    change: impl FnOnce(&mut Config),
) -> Result<Config, String> {
    let state = app.state::<Mutex<Config>>();
    let mut config = state
        .lock()
        .map_err(|_| "settings lock unavailable".to_string())?;
    let old = config.clone();
    let mut next = old.clone();
    change(&mut next);
    next.normalise();
    if next == old {
        return Ok(next);
    }
    if next.startup != old.startup {
        config::set_startup(next.startup)?;
    }
    let window = app
        .get_webview_window("main")
        .ok_or("dashboard unavailable")?;
    let applied = apply_window_state(&window, &next).and_then(|_| next.save());
    if let Err(error) = applied {
        let _ = apply_window_state(&window, &old);
        if next.startup != old.startup {
            let _ = config::set_startup(old.startup);
        }
        return Err(error);
    }
    *config = next.clone();
    drop(config);
    if next.taskbar != old.taskbar {
        taskbar::reconfigure(
            next.taskbar.enabled,
            &next.taskbar.monitor_device_path,
            next.taskbar.width_dip,
        );
    }
    sync_tray(app, &next);
    let _ = app.emit("ptmonitor://settings", &next);
    Ok(next)
}

fn sync_tray(app: &tauri::AppHandle, config: &Config) {
    if let Some(controls) = app.try_state::<TrayControls>() {
        let _ = controls.startup.set_checked(config.startup);
        let _ = controls.start_hidden.set_checked(config.start_hidden);
        let _ = controls.click_through.set_checked(config.click_through);
        let _ = controls.toast_alerts.set_checked(config.toast_alerts);
        let _ = controls
            .taskbar_readings
            .set_checked(config.taskbar.enabled);
        let _ = controls
            .taskbar_width
            .set_text(taskbar_width_label(config.taskbar.width_dip));
    }
}

fn apply_window_state(window: &tauri::WebviewWindow, config: &Config) -> Result<(), String> {
    let (mut width, mut height) = if config.expanded {
        EXPANDED_SIZE
    } else {
        COLLAPSED_SIZE
    };
    if let Ok(Some(monitor)) = window.current_monitor() {
        width = width.min(monitor.work_area().size.width as f64 / monitor.scale_factor());
        height = height.min(monitor.work_area().size.height as f64 / monitor.scale_factor());
    }
    let target = LogicalSize::new(width, height);
    let current = window
        .inner_size()
        .ok()
        .map(|s| s.to_logical::<f64>(window.scale_factor().unwrap_or(1.0)));
    if current != Some(target) {
        placement::resize(window, target)?;
    }
    window
        .set_ignore_cursor_events(config.click_through)
        .map_err(|e| format!("change interaction mode: {e}"))?;
    Ok(())
}

#[tauri::command]
fn get_settings(state: tauri::State<'_, Mutex<Config>>) -> Config {
    state.lock().map(|c| c.clone()).unwrap_or_default()
}

#[tauri::command]
fn update_settings(patch: SettingsPatch, app: tauri::AppHandle) -> Result<Config, String> {
    mutate_config(&app, |config| {
        if let Some(v) = patch.opacity {
            config.opacity = v;
        }
        if let Some(v) = patch.background_opacity {
            config.background_opacity = v;
        }
        if let Some(v) = patch.startup {
            config.startup = v;
        }
        if let Some(v) = patch.start_hidden {
            config.start_hidden = v;
        }
        if let Some(v) = patch.click_through {
            config.click_through = v;
        }
        if let Some(v) = patch.expanded {
            config.expanded = v;
        }
        if let Some(v) = patch.selected_adapter {
            config.selected_adapter = v;
        }
        if let Some(v) = patch.toast_alerts {
            config.toast_alerts = v;
        }
        if let Some(v) = patch.advanced_sensors {
            config.advanced_sensors = v;
        }
        if let Some(v) = patch.thresholds {
            config.thresholds = v;
        }
    })
}

#[tauri::command]
fn show_dashboard(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        placement::recover(&window, None);
        let _ = window.show();
        let _ = window.set_focus();
        let _ = app.emit("ptmonitor://resumed", ());
    }
}

#[tauri::command]
fn hide_dashboard(window: tauri::WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn set_interaction_mode(interactive: bool, app: tauri::AppHandle) -> Result<Config, String> {
    mutate_config(&app, |config| config.click_through = !interactive)
}

#[tauri::command]
fn snap_to_current_monitor(window: tauri::WebviewWindow) {
    placement::snap(&window);
}

#[tauri::command]
fn refresh_snapshot(state: tauri::State<'_, stats::AppState>) {
    state.request_refresh();
}

#[tauri::command]
fn restart_elevated(app: tauri::AppHandle) -> Result<(), String> {
    platform::launch_elevated()?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn adapter_reset_distinguishes_null_from_missing() {
        assert_eq!(
            serde_json::from_str::<SettingsPatch>(r#"{}"#)
                .unwrap()
                .selected_adapter,
            None
        );
        assert_eq!(
            serde_json::from_str::<SettingsPatch>(r#"{"selectedAdapter":null}"#)
                .unwrap()
                .selected_adapter,
            Some(None)
        );
        assert_eq!(
            serde_json::from_str::<SettingsPatch>(r#"{"selectedAdapter":"Wi-Fi"}"#)
                .unwrap()
                .selected_adapter,
            Some(Some("Wi-Fi".into()))
        );
    }
}
