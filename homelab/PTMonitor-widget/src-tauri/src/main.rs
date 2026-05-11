#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod stats;

use config::Config;
use stats::AppState;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};
use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    Manager,
};

static LAST_POS_SAVE: AtomicU64 = AtomicU64::new(0);

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// Opacity is applied via CSS eval — set_opacity doesn't exist in Tauri 2.10
fn set_opacity(win: &tauri::WebviewWindow<impl tauri::Runtime>, opacity: f64) {
    let _ = win.eval(&format!(
        "document.getElementById('widget').style.opacity='{opacity}'"
    ));
}

fn main() {
    let initial_cfg = Config::load();

    tauri::Builder::default()
        .manage(Mutex::new(AppState::new()))
        .manage(Mutex::new(initial_cfg.clone()))
        .setup(move |app| {
            stats::start_gpu_poll();

            let win = app.get_webview_window("main").unwrap();

            if initial_cfg.initialized {
                let _ = win.set_position(tauri::LogicalPosition::new(initial_cfg.x, initial_cfg.y));
            } else {
                // First launch — place bottom-right, clear of taskbar
                if let Ok(Some(monitor)) = win.current_monitor() {
                    let scale = monitor.scale_factor();
                    let mw = monitor.size().width as f64 / scale;
                    let mh = monitor.size().height as f64 / scale;
                    let x = mw - 240.0 - 20.0;
                    let y = mh - 420.0 - 48.0; // 48 ≈ taskbar height
                    let _ = win.set_position(tauri::LogicalPosition::new(x, y));
                    let state = app.state::<Mutex<Config>>();
                    let mut cfg = state.lock().unwrap();
                    cfg.initialized = true;
                    cfg.x = x;
                    cfg.y = y;
                    let snap = cfg.clone();
                    drop(cfg);
                    snap.save();
                }
            }

            if initial_cfg.click_through {
                let _ = win.set_ignore_cursor_events(true);
            }
            if initial_cfg.start_hidden {
                let _ = win.hide();
            }

            // Build tray menu — CheckMenuItems toggle their own checkmark automatically
            let toggle  = MenuItem::with_id(app, "toggle", "Hide / Show", true, None::<&str>)?;
            let sep1    = PredefinedMenuItem::separator(app)?;
            let startup = CheckMenuItem::with_id(app, "startup", "Launch on Startup", true, initial_cfg.startup, None::<&str>)?;
            let hidden  = CheckMenuItem::with_id(app, "start_hidden", "Start Hidden", true, initial_cfg.start_hidden, None::<&str>)?;
            let sep2    = PredefinedMenuItem::separator(app)?;
            let ct      = CheckMenuItem::with_id(app, "click_through", "Click-Through Mode", true, initial_cfg.click_through, None::<&str>)?;
            let sep3    = PredefinedMenuItem::separator(app)?;
            let op100   = MenuItem::with_id(app, "op100", "Opacity  100%", true, None::<&str>)?;
            let op75    = MenuItem::with_id(app, "op75",  "Opacity   75%", true, None::<&str>)?;
            let op50    = MenuItem::with_id(app, "op50",  "Opacity   50%", true, None::<&str>)?;
            let op25    = MenuItem::with_id(app, "op25",  "Opacity   25%", true, None::<&str>)?;
            let op_sub  = Submenu::with_items(app, "Opacity", true, &[&op100, &op75, &op50, &op25])?;
            let sep4    = PredefinedMenuItem::separator(app)?;
            let quit    = MenuItem::with_id(app, "quit", "Quit PTMonitor", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[
                &toggle, &sep1,
                &startup, &hidden, &sep2,
                &ct, &sep3,
                &op_sub, &sep4,
                &quit,
            ])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("PTMonitor")
                .menu(&menu)
                .on_menu_event(|app, event| {
                    let state = app.state::<Mutex<Config>>();
                    match event.id.as_ref() {
                        "quit" => app.exit(0),

                        "toggle" => {
                            if let Some(w) = app.get_webview_window("main") {
                                if w.is_visible().unwrap_or(false) {
                                    let _ = w.hide();
                                } else {
                                    let _ = w.show();
                                    let _ = w.set_focus();
                                }
                            }
                        }

                        "startup" => {
                            let mut cfg = state.lock().unwrap();
                            cfg.startup = !cfg.startup;
                            config::set_startup(cfg.startup);
                            let snap = cfg.clone();
                            drop(cfg);
                            snap.save();
                        }

                        "start_hidden" => {
                            let mut cfg = state.lock().unwrap();
                            cfg.start_hidden = !cfg.start_hidden;
                            let snap = cfg.clone();
                            drop(cfg);
                            snap.save();
                        }

                        "click_through" => {
                            let mut cfg = state.lock().unwrap();
                            cfg.click_through = !cfg.click_through;
                            if let Some(w) = app.get_webview_window("main") {
                                let _ = w.set_ignore_cursor_events(cfg.click_through);
                            }
                            let snap = cfg.clone();
                            drop(cfg);
                            snap.save();
                        }

                        id @ ("op100" | "op75" | "op50" | "op25") => {
                            let opacity: f64 = match id {
                                "op100" => 1.0,
                                "op75"  => 0.75,
                                "op50"  => 0.5,
                                _       => 0.25,
                            };
                            let mut cfg = state.lock().unwrap();
                            cfg.opacity = opacity;
                            let snap = cfg.clone();
                            drop(cfg);
                            if let Some(w) = app.get_webview_window("main") {
                                set_opacity(&w, opacity);
                            }
                            snap.save();
                        }

                        _ => {}
                    }
                })
                .build(app)?;

            // Persist position on drag (debounced to 500ms)
            let app_handle = app.handle().clone();
            win.on_window_event(move |event| {
                if let tauri::WindowEvent::Moved(pos) = event {
                    let t = now_ms();
                    if t.saturating_sub(LAST_POS_SAVE.load(Ordering::Relaxed)) < 500 {
                        return;
                    }
                    LAST_POS_SAVE.store(t, Ordering::Relaxed);
                    let state = app_handle.state::<Mutex<Config>>();
                    let mut cfg = state.lock().unwrap();
                    cfg.x = pos.x as f64;
                    cfg.y = pos.y as f64;
                    let snap = cfg.clone();
                    drop(cfg);
                    snap.save();
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            stats::get_stats,
            get_opacity,
            get_config,
            toggle_setting,
            set_opacity_cmd,
            quit_app,
        ])
        .run(tauri::generate_context!())
        .expect("error running PTMonitor");
}

#[tauri::command]
fn get_opacity(state: tauri::State<'_, Mutex<Config>>) -> f64 {
    state.lock().unwrap().opacity
}

#[tauri::command]
fn get_config(state: tauri::State<'_, Mutex<Config>>) -> Config {
    state.lock().unwrap().clone()
}

#[tauri::command]
fn toggle_setting(
    key: String,
    value: bool,
    state: tauri::State<'_, Mutex<Config>>,
    window: tauri::WebviewWindow,
) {
    let mut cfg = state.lock().unwrap();
    match key.as_str() {
        "startup"      => { cfg.startup = value; config::set_startup(value); }
        "start_hidden" => { cfg.start_hidden = value; }
        "click_through" => {
            cfg.click_through = value;
            let _ = window.set_ignore_cursor_events(value);
        }
        _ => {}
    }
    let snap = cfg.clone();
    drop(cfg);
    snap.save();
}

#[tauri::command]
fn set_opacity_cmd(value: f64, state: tauri::State<'_, Mutex<Config>>, window: tauri::WebviewWindow) {
    let mut cfg = state.lock().unwrap();
    cfg.opacity = value;
    let snap = cfg.clone();
    drop(cfg);
    snap.save();
    let _ = window.eval(&format!(
        "document.getElementById('widget').style.opacity='{value}'"
    ));
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}
