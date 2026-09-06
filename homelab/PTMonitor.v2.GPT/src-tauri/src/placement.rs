//! Placement uses native work areas (taskbar excluded) and the window's actual physical size.
use crate::config::{Config, WindowPosition};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Manager, PhysicalPosition, WebviewWindow};

#[derive(Default)]
pub struct Placement {
    pending: Mutex<Option<(Instant, WindowPosition)>>,
    reflow: AtomicBool,
    pub stopped: Arc<AtomicBool>,
}

#[derive(Clone, Copy)]
struct Area {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

fn clamp(position: WindowPosition, size: (u32, u32), area: Area) -> WindowPosition {
    WindowPosition {
        x: (position.x as i64).clamp(
            area.x as i64,
            area.x as i64 + area.width.saturating_sub(size.0) as i64,
        ) as i32,
        y: (position.y as i64).clamp(
            area.y as i64,
            area.y as i64 + area.height.saturating_sub(size.1) as i64,
        ) as i32,
    }
}

fn area(monitor: &tauri::Monitor) -> Area {
    let work = monitor.work_area();
    Area {
        x: work.position.x,
        y: work.position.y,
        width: work.size.width,
        height: work.size.height,
    }
}

pub fn recover(window: &WebviewWindow, desired: Option<WindowPosition>) {
    let Ok(monitors) = window.available_monitors() else {
        return;
    };
    let position = desired.or_else(|| {
        window
            .outer_position()
            .ok()
            .map(|p| WindowPosition { x: p.x, y: p.y })
    });
    let Some(position) = position else {
        snap(window);
        return;
    };
    // Choose the closest work area, including disconnected/negative-coordinate monitors.
    let monitor = monitors.iter().min_by_key(|m| {
        let a = area(m);
        let p = clamp(position, (1, 1), a);
        (position.x as i64 - p.x as i64)
            .unsigned_abs()
            .saturating_add((position.y as i64 - p.y as i64).unsigned_abs())
    });
    if let (Some(monitor), Ok(mut size)) = (monitor, window.outer_size()) {
        let a = area(monitor);
        let fitted = tauri::PhysicalSize::new(size.width.min(a.width), size.height.min(a.height));
        if fitted != size {
            let _ = window.set_size(fitted);
            size = fitted;
        }
        let next = clamp(position, (size.width, size.height), a);
        if window
            .outer_position()
            .ok()
            .is_none_or(|p| p.x != next.x || p.y != next.y)
        {
            let _ = window.set_position(PhysicalPosition::new(next.x, next.y));
        }
    }
}

pub fn resize(window: &WebviewWindow, target: tauri::LogicalSize<f64>) -> Result<(), String> {
    let origin = window.outer_position().ok();
    let old_size = window.outer_size().ok();
    let monitor = window.current_monitor().ok().flatten();
    window
        .set_size(target)
        .map_err(|e| format!("resize dashboard: {e}"))?;
    if let (Some(p), Some(old), Some(m), Ok(new)) = (origin, old_size, monitor, window.outer_size())
    {
        let a = area(&m);
        let next = resize_anchor(
            WindowPosition { x: p.x, y: p.y },
            (old.width, old.height),
            (new.width, new.height),
            a,
            (32.0 * m.scale_factor()) as i64,
        );
        let _ = window.set_position(PhysicalPosition::new(next.x, next.y));
    }
    recover(window, None);
    Ok(())
}

fn resize_anchor(
    p: WindowPosition,
    old: (u32, u32),
    new: (u32, u32),
    a: Area,
    margin: i64,
) -> WindowPosition {
    let right = a.x as i64 + a.width as i64 - p.x as i64 - old.0 as i64;
    let bottom = a.y as i64 + a.height as i64 - p.y as i64 - old.1 as i64;
    clamp(
        WindowPosition {
            x: if (0..=margin).contains(&right) {
                (p.x as i64 + old.0 as i64 - new.0 as i64) as i32
            } else {
                p.x
            },
            y: if (0..=margin).contains(&bottom) {
                (p.y as i64 + old.1 as i64 - new.1 as i64) as i32
            } else {
                p.y
            },
        },
        new,
        a,
    )
}

pub fn snap(window: &WebviewWindow) {
    let monitor = window
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten());
    if let (Some(monitor), Ok(size)) = (monitor, window.outer_size()) {
        let a = area(&monitor);
        let margin = (16.0 * monitor.scale_factor()).round() as i32;
        let next = clamp(
            WindowPosition {
                x: a.x
                    .saturating_add(a.width as i32)
                    .saturating_sub(size.width as i32)
                    .saturating_sub(margin),
                y: a.y
                    .saturating_add(a.height as i32)
                    .saturating_sub(size.height as i32)
                    .saturating_sub(margin),
            },
            (size.width, size.height),
            a,
        );
        let _ = window.set_position(PhysicalPosition::new(next.x, next.y));
    }
}

pub fn attach(window: &WebviewWindow) {
    let app = window.app_handle().clone();
    window.on_window_event(move |event| match event {
        tauri::WindowEvent::Moved(p) => {
            if let Ok(mut pending) = app.state::<Placement>().pending.lock() {
                *pending = Some((Instant::now(), WindowPosition { x: p.x, y: p.y }));
            }
        }
        tauri::WindowEvent::ScaleFactorChanged { .. } => {
            app.state::<Placement>()
                .reflow
                .store(true, Ordering::Relaxed);
        }
        tauri::WindowEvent::CloseRequested { api, .. } => {
            api.prevent_close();
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.hide();
            }
        }
        _ => {}
    });
    let app = window.app_handle().clone();
    std::thread::spawn(move || {
        let stopped = app.state::<Placement>().stopped.clone();
        let mut topology = String::new();
        let mut topology_tick = Instant::now();
        while !stopped.load(Ordering::Relaxed) {
            std::thread::sleep(Duration::from_millis(250));
            if app
                .state::<Placement>()
                .reflow
                .swap(false, Ordering::Relaxed)
            {
                let config = app.state::<Mutex<Config>>().lock().ok().map(|c| c.clone());
                if let (Some(config), Some(window)) = (config, app.get_webview_window("main")) {
                    let _ = crate::apply_window_state(&window, &config);
                }
            }
            let pending = {
                let state = app.state::<Placement>();
                let mut pending = state.pending.lock().unwrap();
                if pending
                    .as_ref()
                    .is_some_and(|(when, _)| when.elapsed() >= Duration::from_millis(750))
                {
                    pending.take()
                } else {
                    None
                }
            };
            if let Some((_, position)) = pending {
                if let Ok(mut cfg) = app.state::<Mutex<Config>>().lock() {
                    cfg.position = Some(position);
                    if let Err(error) = cfg.save() {
                        crate::report_error(&app, error);
                    }
                }
            }
            if topology_tick.elapsed() >= Duration::from_secs(3) {
                topology_tick = Instant::now();
                if let Some(window) = app.get_webview_window("main") {
                    if let Ok(monitors) = window.available_monitors() {
                        let next = format!("{monitors:?}");
                        if !topology.is_empty() && topology != next {
                            recover(&window, None);
                            app.state::<Placement>()
                                .reflow
                                .store(true, Ordering::Relaxed);
                        }
                        topology = next;
                    }
                }
            }
        }
    });
}

pub fn flush(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<Placement>() {
        state.stopped.store(true, Ordering::Relaxed);
        if let Ok(mut pending) = state.pending.lock() {
            if let Some((_, position)) = pending.take() {
                if let Ok(mut cfg) = app.state::<Mutex<Config>>().lock() {
                    cfg.position = Some(position);
                    let _ = cfg.save();
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn expand_then_collapse_preserves_corner_anchor() {
        let a = Area {
            x: 0,
            y: 0,
            width: 1920,
            height: 1040,
        };
        let compact = WindowPosition { x: 1592, y: 572 };
        let expanded = resize_anchor(compact, (312, 452), (580, 720), a, 32);
        assert_eq!(expanded, WindowPosition { x: 1324, y: 304 });
        assert_eq!(
            resize_anchor(expanded, (580, 720), (312, 452), a, 32),
            compact
        );
    }
    #[test]
    fn removed_monitor_and_negative_coordinates_recover() {
        let a = Area {
            x: -1920,
            y: 0,
            width: 1920,
            height: 1040,
        };
        assert_eq!(
            clamp(WindowPosition { x: 4000, y: -100 }, (468, 678), a),
            WindowPosition { x: -468, y: 0 }
        );
    }
    #[test]
    fn taskbar_and_scaled_window_are_respected() {
        let a = Area {
            x: 0,
            y: 40,
            width: 1920,
            height: 1000,
        };
        assert_eq!(
            clamp(WindowPosition { x: 1900, y: 1000 }, (780, 1080), a),
            WindowPosition { x: 1140, y: 40 }
        );
    }
}
