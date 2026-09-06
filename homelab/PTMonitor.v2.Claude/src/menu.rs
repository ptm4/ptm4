//! The one settings surface: a native popup menu built from `Config` every time it opens,
//! so it can never be stale. Shown by the hidden tray-owner window so the widget never
//! takes focus. Commands map to [`Cmd`].

use windows::core::Result;
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CheckMenuRadioItem, CreatePopupMenu, DestroyMenu, PostMessageW, SetForegroundWindow,
    TrackPopupMenuEx, HMENU, MF_BYCOMMAND, MF_CHECKED, MF_GRAYED, MF_POPUP, MF_SEPARATOR, MF_STRING,
    MF_UNCHECKED, TPM_LEFTALIGN, TPM_RETURNCMD, TPM_RIGHTBUTTON, TPM_TOPALIGN, WM_NULL,
};

use crate::config::Config;
use crate::gfx::backdrop::BackdropMode;
use crate::hotkey;
use crate::util::wide;
use crate::win::window::Layer;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Cmd {
    ToggleVisible,
    Layer(Layer),
    Backdrop(BackdropMode),
    Opacity(f32),
    ClickThrough,
    Sparklines,
    GameMode,
    Autostart,
    StartHidden,
    OpenSettings,
    ReloadSettings,
    About,
    Quit,
}

pub const ID_TOGGLE: u32 = 1;
pub const ID_LAYER: u32 = 10; // +0 topmost, +1 normal, +2 desktop
const ID_BACKDROP: u32 = 20; // + index in BackdropMode::ALL
pub const ID_OPACITY: u32 = 30; // + index in OPACITY_PRESETS
const ID_CLICK_THROUGH: u32 = 40;
pub const ID_SPARKLINES: u32 = 41;
const ID_GAME_MODE: u32 = 42;
pub const ID_AUTOSTART: u32 = 50;
pub const ID_START_HIDDEN: u32 = 51;
const ID_OPEN_SETTINGS: u32 = 60;
const ID_RELOAD: u32 = 61;
const ID_ABOUT: u32 = 62;
pub const ID_QUIT: u32 = 99;

pub fn cmd_from_id(id: u32) -> Option<Cmd> {
    Some(match id {
        ID_TOGGLE => Cmd::ToggleVisible,
        x if (ID_LAYER..ID_LAYER + 3).contains(&x) => Cmd::Layer([Layer::Topmost, Layer::Normal, Layer::Desktop][(x - ID_LAYER) as usize]),
        x if (ID_BACKDROP..ID_BACKDROP + 5).contains(&x) => Cmd::Backdrop(BackdropMode::ALL[(x - ID_BACKDROP) as usize]),
        x if (ID_OPACITY..ID_OPACITY + 4).contains(&x) => Cmd::Opacity(crate::config::OPACITY_PRESETS[(x - ID_OPACITY) as usize]),
        ID_CLICK_THROUGH => Cmd::ClickThrough,
        ID_SPARKLINES => Cmd::Sparklines,
        ID_GAME_MODE => Cmd::GameMode,
        ID_AUTOSTART => Cmd::Autostart,
        ID_START_HIDDEN => Cmd::StartHidden,
        ID_OPEN_SETTINGS => Cmd::OpenSettings,
        ID_RELOAD => Cmd::ReloadSettings,
        ID_ABOUT => Cmd::About,
        ID_QUIT => Cmd::Quit,
        _ => return None,
    })
}

/// Runtime facts the menu displays alongside the config.
pub struct MenuState<'a> {
    pub cfg: &'a Config,
    pub visible: bool,
    /// `None` = hotkey registered fine (or disabled); `Some(reason)` = shown greyed.
    pub hotkey_problem: Option<&'a str>,
    pub applied_backdrop: &'a str,
}

unsafe fn item(menu: HMENU, id: u32, text: &str, checked: bool, grayed: bool) -> Result<()> {
    let w = wide(text);
    let mut flags = MF_STRING | if checked { MF_CHECKED } else { MF_UNCHECKED };
    if grayed {
        flags |= MF_GRAYED;
    }
    AppendMenuW(menu, flags, id as usize, windows::core::PCWSTR(w.as_ptr()))
}

unsafe fn separator(menu: HMENU) -> Result<()> {
    AppendMenuW(menu, MF_SEPARATOR, 0, None)
}

unsafe fn submenu(menu: HMENU, text: &str, sub: HMENU) -> Result<()> {
    let w = wide(text);
    AppendMenuW(menu, MF_POPUP, sub.0 as usize, windows::core::PCWSTR(w.as_ptr()))
}

unsafe fn radio(sub: HMENU, first: u32, count: u32, selected: u32) {
    let _ = CheckMenuRadioItem(sub, first, first + count - 1, first + selected, MF_BYCOMMAND.0);
}

/// Build the menu. Caller destroys it (done by [`show`]).
pub fn build(state: &MenuState) -> Result<HMENU> {
    let cfg = state.cfg;
    // SAFETY: menu construction with static/owned strings; handles are destroyed in `show`.
    unsafe {
        let menu = CreatePopupMenu()?;
        let hk = hotkey::display(&cfg.hotkey);
        let toggle = if state.visible { "Hide" } else { "Show" };
        let label = if hk.is_empty() { toggle.to_string() } else { format!("{toggle}\t{hk}") };
        item(menu, ID_TOGGLE, &label, false, false)?;
        separator(menu)?;

        let layer = CreatePopupMenu()?;
        item(layer, ID_LAYER, "Always on top", false, false)?;
        item(layer, ID_LAYER + 1, "Normal", false, false)?;
        item(layer, ID_LAYER + 2, "Pinned to desktop", false, false)?;
        radio(layer, ID_LAYER, 3, match cfg.layer { Layer::Topmost => 0, Layer::Normal => 1, Layer::Desktop => 2 });
        submenu(menu, "Layer", layer)?;

        let backdrop = CreatePopupMenu()?;
        for (i, m) in BackdropMode::ALL.iter().enumerate() {
            let text = if *m == BackdropMode::Auto { format!("Auto  ({})", state.applied_backdrop) } else { m.label().to_string() };
            item(backdrop, ID_BACKDROP + i as u32, &text, false, false)?;
        }
        radio(backdrop, ID_BACKDROP, 5, BackdropMode::ALL.iter().position(|m| *m == cfg.backdrop).unwrap_or(0) as u32);
        submenu(menu, "Backdrop", backdrop)?;

        let opacity = CreatePopupMenu()?;
        for (i, o) in crate::config::OPACITY_PRESETS.iter().enumerate() {
            item(opacity, ID_OPACITY + i as u32, &format!("{}%", (o * 100.0).round() as u32), false, false)?;
        }
        let sel = crate::config::OPACITY_PRESETS.iter().position(|o| (o - cfg.opacity).abs() < 0.01).unwrap_or(0);
        radio(opacity, ID_OPACITY, 4, sel as u32);
        submenu(menu, "Opacity", opacity)?;
        separator(menu)?;

        item(menu, ID_CLICK_THROUGH, "Click-through", cfg.click_through, false)?;
        item(menu, ID_SPARKLINES, "Sparklines", cfg.sparklines, false)?;
        item(menu, ID_GAME_MODE, "Pause in fullscreen games", cfg.game_mode, false)?;
        separator(menu)?;
        item(menu, ID_AUTOSTART, "Launch on startup", cfg.autostart, false)?;
        item(menu, ID_START_HIDDEN, "Start hidden", cfg.start_hidden, false)?;
        separator(menu)?;
        item(menu, ID_OPEN_SETTINGS, "Open settings.json", false, false)?;
        item(menu, ID_RELOAD, "Reload settings", false, false)?;
        if let Some(problem) = state.hotkey_problem {
            item(menu, 0, &format!("Hotkey unavailable: {problem}"), false, true)?;
        }
        item(menu, ID_ABOUT, "About PTMonitor 2…", false, false)?;
        separator(menu)?;
        item(menu, ID_QUIT, "Quit PTMonitor 2", false, false)?;
        Ok(menu)
    }
}

/// Show `menu` at screen point (x, y) owned by `owner` (the hidden tray window). Blocks in the
/// menu's modal loop; returns the chosen command. Must be called with no `APP` borrow held.
pub fn show(owner: HWND, x: i32, y: i32, menu: HMENU) -> Option<Cmd> {
    // SAFETY: the classic tray-menu sequence; `menu` is destroyed here.
    unsafe {
        let _ = SetForegroundWindow(owner);
        let picked = TrackPopupMenuEx(menu, (TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_LEFTALIGN | TPM_TOPALIGN).0, x, y, owner, None);
        let _ = PostMessageW(Some(owner), WM_NULL, WPARAM(0), LPARAM(0));
        let _ = DestroyMenu(menu);
        cmd_from_id(picked.0 as u32)
    }
}
