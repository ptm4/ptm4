//! Palette and layout constants. Colors are the legacy PTMonitor palette with the
//! contrast floors raised; sizes are DIPs on an 8 px grid.

use windows::Win32::Graphics::Direct2D::Common::D2D1_COLOR_F;

/// `0xRRGGBB` + alpha to a straight-alpha D2D color.
pub const fn rgb(hex: u32, a: f32) -> D2D1_COLOR_F {
    D2D1_COLOR_F {
        r: ((hex >> 16) & 0xff) as f32 / 255.0,
        g: ((hex >> 8) & 0xff) as f32 / 255.0,
        b: (hex & 0xff) as f32 / 255.0,
        a,
    }
}

pub const fn white(a: f32) -> D2D1_COLOR_F {
    D2D1_COLOR_F { r: 1.0, g: 1.0, b: 1.0, a }
}

pub const TRANSPARENT: D2D1_COLOR_F = D2D1_COLOR_F { r: 0.0, g: 0.0, b: 0.0, a: 0.0 };

// ── Card ──────────────────────────────────────────────────────────────────────
pub const CARD_BG: u32 = 0x10121a;
pub const CARD_ALPHA_FLAT: f32 = 0.82; // no backdrop material (v1 look)
pub const CARD_ALPHA_MATERIAL: f32 = 0.50; // Acrylic/Mica behind the card
pub const CARD_BORDER: D2D1_COLOR_F = white(0.08);
pub const CARD_SHEEN: D2D1_COLOR_F = white(0.05);
pub const RULE: D2D1_COLOR_F = white(0.06);
pub const TRACK: D2D1_COLOR_F = white(0.07);

// ── Text (contrast floors raised vs v1) ───────────────────────────────────────
pub const T_TITLE: D2D1_COLOR_F = white(0.55);
pub const T_BAND: D2D1_COLOR_F = white(0.45);
pub const T_LABEL: D2D1_COLOR_F = white(0.60);
pub const T_VALUE: D2D1_COLOR_F = white(0.94);
pub const T_SUB: D2D1_COLOR_F = white(0.58);
pub const T_FOOTER: D2D1_COLOR_F = white(0.50);
pub const T_GEAR: D2D1_COLOR_F = white(0.30);
pub const T_GEAR_HOVER: D2D1_COLOR_F = white(0.85);

// ── Status / thresholds ───────────────────────────────────────────────────────
pub const OK: u32 = 0x4caf7d;
pub const WARN: u32 = 0xf0b429;
pub const CRIT: u32 = 0xe05c5c;

/// Two-stop gradient per metric (legacy CSS stops).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Palette {
    Cpu,
    Ram,
    Gpu,
    Disk,
    NetDown,
    NetUp,
}

impl Palette {
    pub const fn stops(self) -> (u32, u32) {
        match self {
            Palette::Cpu => (0x3a7bd5, 0x6fa3ef),
            Palette::Ram => (0x27ae60, 0x4caf7d),
            Palette::Gpu => (0x6d28d9, 0xa78bfa),
            Palette::Disk => (0xb45309, 0xf59e0b),
            Palette::NetDown => (0x8e44ad, 0xb06bd9),
            Palette::NetUp => (0xd35400, 0xe67e22),
        }
    }
    /// The lighter stop, used for sparkline strokes.
    pub const fn light(self) -> u32 {
        self.stops().1
    }
}

// ── Layout (DIP) ──────────────────────────────────────────────────────────────
pub const WIDTH: f32 = 256.0;
pub const RADIUS: f32 = 8.0;
pub const PAD_X: f32 = 12.0;
pub const HEADER_H: f32 = 32.0;
pub const FOOTER_H: f32 = 26.0;
pub const STATS_PAD: f32 = 10.0;
pub const ROW_H: f32 = 26.0;
pub const ROW_GAP: f32 = 8.0;
pub const BAND_H: f32 = 20.0;
pub const GROUP_GAP: f32 = 10.0;
pub const LABEL_W: f32 = 40.0;
pub const VALUE_W: f32 = 76.0;
pub const GRID_GAP: f32 = 8.0;
pub const BAR_H: f32 = 5.0;
pub const SPARK_H: f32 = 12.0;
pub const SPARK_EXTRA: f32 = 14.0; // row grows by this when a sparkline strip is shown
pub const GEAR_SIZE: f32 = 20.0;
pub const DOT_SIZE: f32 = 7.0;

// ── Typography (DIP sizes; weights are DirectWrite numeric weights) ───────────
pub const FS_TITLE: f32 = 10.0;
pub const FS_BAND: f32 = 9.0;
pub const FS_LABEL: f32 = 10.0;
pub const FS_VALUE: f32 = 12.0;
pub const FS_SUB: f32 = 10.0;
pub const FS_FOOTER: f32 = 9.0;
pub const FS_GEAR: f32 = 13.0;
pub const TRACK_TITLE: f32 = 0.16;
pub const TRACK_BAND: f32 = 0.18;
pub const TRACK_LABEL: f32 = 0.05;
pub const TRACK_FOOTER: f32 = 0.12;
