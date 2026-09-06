//! Painter: draws the [`ViewModel`] (card, header with status dot + hover gear, section
//! bands, rows with bars and sparklines, footer) with Direct2D. All geometry is in DIPs,
//! snapped to whole device pixels so hairlines stay crisp. Nothing here animates.

use windows::core::Result;
use windows::Win32::Graphics::Direct2D::Common::{D2D1_COLOR_F, D2D1_FIGURE_BEGIN_FILLED, D2D1_FIGURE_BEGIN_HOLLOW, D2D1_FIGURE_END_CLOSED, D2D1_FIGURE_END_OPEN, D2D1_GRADIENT_STOP, D2D_RECT_F};
use windows::Win32::Graphics::Direct2D::{
    ID2D1Brush, ID2D1DeviceContext, ID2D1Factory1, ID2D1StrokeStyle1, D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
    D2D1_BUFFER_PRECISION_8BPC_UNORM, D2D1_CAP_STYLE_ROUND, D2D1_COLOR_INTERPOLATION_MODE_STRAIGHT,
    D2D1_COLOR_SPACE_SRGB, D2D1_DASH_STYLE_SOLID, D2D1_DRAW_TEXT_OPTIONS_NONE, D2D1_ELLIPSE,
    D2D1_EXTEND_MODE_CLAMP, D2D1_LINEAR_GRADIENT_BRUSH_PROPERTIES, D2D1_LINE_JOIN_ROUND,
    D2D1_ROUNDED_RECT, D2D1_STROKE_STYLE_PROPERTIES1, D2D1_STROKE_TRANSFORM_TYPE_NORMAL,
};
use windows::Win32::Graphics::DirectWrite::{DWRITE_TEXT_ALIGNMENT_CENTER, DWRITE_TEXT_ALIGNMENT_LEADING, DWRITE_TEXT_ALIGNMENT_TRAILING};
use windows_numerics::Vector2;

use crate::gfx::text::{TextEngine, TextStyle, Tier};
use crate::model::{Level, RowModel, Spark, ViewModel};
use crate::theme::{self, Palette};

pub struct Styles {
    pub title: TextStyle,
    pub band: TextStyle,
    pub label: TextStyle,
    pub value: TextStyle,
    pub sub: TextStyle,
    pub footer: TextStyle,
    pub footer_right: TextStyle,
    pub gear: TextStyle,
}

impl Styles {
    pub fn new(text: &TextEngine) -> Result<Self> {
        Ok(Styles {
            title: text.style(Tier::Small, theme::FS_TITLE, 600, DWRITE_TEXT_ALIGNMENT_LEADING, theme::TRACK_TITLE, false)?,
            band: text.style(Tier::Small, theme::FS_BAND, 700, DWRITE_TEXT_ALIGNMENT_LEADING, theme::TRACK_BAND, false)?,
            label: text.style(Tier::Small, theme::FS_LABEL, 600, DWRITE_TEXT_ALIGNMENT_LEADING, theme::TRACK_LABEL, false)?,
            value: text.style(Tier::Text, theme::FS_VALUE, 600, DWRITE_TEXT_ALIGNMENT_TRAILING, 0.0, true)?,
            sub: text.style(Tier::Small, theme::FS_SUB, 500, DWRITE_TEXT_ALIGNMENT_TRAILING, 0.0, true)?,
            footer: text.style(Tier::Small, theme::FS_FOOTER, 600, DWRITE_TEXT_ALIGNMENT_LEADING, theme::TRACK_FOOTER, true)?,
            footer_right: text.style(Tier::Small, theme::FS_FOOTER, 600, DWRITE_TEXT_ALIGNMENT_TRAILING, theme::TRACK_FOOTER, true)?,
            gear: text.style(Tier::Icons, theme::FS_GEAR, 400, DWRITE_TEXT_ALIGNMENT_CENTER, 0.0, false)?,
        })
    }
}

/// Snap a DIP coordinate to the device-pixel grid.
pub fn snap(v: f32, scale: f32) -> f32 {
    (v * scale).round() / scale
}

pub fn rect(l: f32, t: f32, r: f32, b: f32) -> D2D_RECT_F {
    D2D_RECT_F { left: l, top: t, right: r, bottom: b }
}

/// Header hit rectangles (DIP), shared with the hit-test in `app`.
pub fn gear_rect(width: f32) -> D2D_RECT_F {
    let x = width - theme::PAD_X - theme::DOT_SIZE - 10.0 - theme::GEAR_SIZE;
    let y = (theme::HEADER_H - theme::GEAR_SIZE) / 2.0;
    rect(x, y, x + theme::GEAR_SIZE, y + theme::GEAR_SIZE)
}

pub struct Painter<'a> {
    pub ctx: &'a ID2D1DeviceContext,
    pub factory: &'a ID2D1Factory1,
    pub text: &'a TextEngine,
    pub styles: &'a Styles,
    pub scale: f32,
}

impl<'a> Painter<'a> {
    fn solid(&self, color: D2D1_COLOR_F) -> Result<ID2D1Brush> {
        // SAFETY: brush creation on the owned context.
        unsafe { Ok(self.ctx.CreateSolidColorBrush(&color, None)?.into()) }
    }

    fn gradient(&self, palette: Palette, x0: f32, x1: f32, y: f32) -> Result<ID2D1Brush> {
        let (a, b) = palette.stops();
        let stops = [
            D2D1_GRADIENT_STOP { position: 0.0, color: theme::rgb(a, 1.0) },
            D2D1_GRADIENT_STOP { position: 1.0, color: theme::rgb(b, 1.0) },
        ];
        // SAFETY: brush creation on the owned context.
        unsafe {
            let coll = self.ctx.CreateGradientStopCollection(
                &stops,
                D2D1_COLOR_SPACE_SRGB,
                D2D1_COLOR_SPACE_SRGB,
                D2D1_BUFFER_PRECISION_8BPC_UNORM,
                D2D1_EXTEND_MODE_CLAMP,
                D2D1_COLOR_INTERPOLATION_MODE_STRAIGHT,
            )?;
            let props = D2D1_LINEAR_GRADIENT_BRUSH_PROPERTIES {
                startPoint: Vector2 { X: x0, Y: y },
                endPoint: Vector2 { X: x1, Y: y },
            };
            Ok(self.ctx.CreateLinearGradientBrush(&props, None, &coll)?.into())
        }
    }

    fn round_stroke(&self) -> Result<ID2D1StrokeStyle1> {
        let props = D2D1_STROKE_STYLE_PROPERTIES1 {
            startCap: D2D1_CAP_STYLE_ROUND,
            endCap: D2D1_CAP_STYLE_ROUND,
            dashCap: D2D1_CAP_STYLE_ROUND,
            lineJoin: D2D1_LINE_JOIN_ROUND,
            miterLimit: 1.0,
            dashStyle: D2D1_DASH_STYLE_SOLID,
            dashOffset: 0.0,
            transformType: D2D1_STROKE_TRANSFORM_TYPE_NORMAL,
        };
        // SAFETY: factory call with a valid struct.
        unsafe { self.factory.CreateStrokeStyle(&props, None) }
    }

    fn fill_round(&self, r: D2D_RECT_F, radius: f32, brush: &ID2D1Brush) {
        let rr = D2D1_ROUNDED_RECT { rect: r, radiusX: radius, radiusY: radius };
        // SAFETY: draw call on the owned context.
        unsafe { self.ctx.FillRoundedRectangle(&rr, brush) }
    }

    fn stroke_round(&self, r: D2D_RECT_F, radius: f32, brush: &ID2D1Brush, width: f32) {
        let rr = D2D1_ROUNDED_RECT { rect: r, radiusX: radius, radiusY: radius };
        // SAFETY: draw call on the owned context.
        unsafe { self.ctx.DrawRoundedRectangle(&rr, brush, width, None) }
    }

    fn hline(&self, x0: f32, x1: f32, y: f32, brush: &ID2D1Brush) {
        let px = 1.0 / self.scale;
        let y = snap(y, self.scale) + px / 2.0;
        // SAFETY: draw call on the owned context.
        unsafe { self.ctx.DrawLine(Vector2 { X: x0, Y: y }, Vector2 { X: x1, Y: y }, brush, px, None) }
    }

    fn circle(&self, cx: f32, cy: f32, r: f32, brush: &ID2D1Brush) {
        let e = D2D1_ELLIPSE { point: Vector2 { X: cx, Y: cy }, radiusX: r, radiusY: r };
        // SAFETY: draw call on the owned context.
        unsafe { self.ctx.FillEllipse(&e, brush) }
    }

    /// Draw `s` inside `r` using `style` (alignment/centering come from the style).
    pub fn text_in(&self, style: &TextStyle, s: &str, r: D2D_RECT_F, color: D2D1_COLOR_F) -> Result<()> {
        if s.is_empty() {
            return Ok(());
        }
        let layout = self.text.layout(style, s, r.right - r.left, r.bottom - r.top)?;
        let brush = self.solid(color)?;
        // SAFETY: draw call on the owned context.
        unsafe {
            self.ctx.DrawTextLayout(
                Vector2 { X: snap(r.left, self.scale), Y: snap(r.top, self.scale) },
                &layout,
                &brush,
                D2D1_DRAW_TEXT_OPTIONS_NONE,
            );
        }
        Ok(())
    }

    /// Track + gradient fill. `frac` is 0..1; the fill width is quantized to device pixels.
    pub fn bar(&self, x: f32, y: f32, w: f32, frac: f32, palette: Palette) -> Result<()> {
        let h = theme::BAR_H;
        let r = h / 2.0;
        let x = snap(x, self.scale);
        let y = snap(y, self.scale);
        let w = snap(w, self.scale);
        let track = self.solid(theme::TRACK)?;
        self.fill_round(rect(x, y, x + w, y + h), r, &track);
        let fill_w = snap(w * frac.clamp(0.0, 1.0), self.scale);
        if fill_w >= 1.0 / self.scale {
            let brush = self.gradient(palette, x, x + w, y)?;
            self.fill_round(rect(x, y, x + fill_w.max(h), y + h), r, &brush);
        }
        Ok(())
    }

    /// High-contrast bar: outlined track, solid fill in the text color.
    pub fn bar_solid(&self, x: f32, y: f32, w: f32, frac: f32, color: D2D1_COLOR_F) -> Result<()> {
        let h = theme::BAR_H;
        let x = snap(x, self.scale);
        let y = snap(y, self.scale);
        let w = snap(w, self.scale);
        let brush = self.solid(color)?;
        self.stroke_round(rect(x, y, x + w, y + h), h / 2.0, &brush, 1.0 / self.scale);
        let fill_w = snap(w * frac.clamp(0.0, 1.0), self.scale);
        if fill_w >= 1.0 / self.scale {
            self.fill_round(rect(x, y, x + fill_w.max(h), y + h), h / 2.0, &brush);
        }
        Ok(())
    }

    /// Sparkline strip: line + area fill from the ring, oldest left, newest right.
    #[allow(clippy::too_many_arguments)]
    pub fn sparkline(&self, x: f32, y: f32, w: f32, h: f32, values: &[f32], max: f32, palette: Palette) -> Result<()> {
        if values.len() < 2 {
            return Ok(());
        }
        let n = values.len();
        let step = w / (n as f32 - 1.0);
        let max = max.max(1e-6);
        let pts: Vec<Vector2> = values
            .iter()
            .enumerate()
            .map(|(i, v)| Vector2 { X: x + i as f32 * step, Y: y + h - (v / max).clamp(0.0, 1.0) * (h - 1.0) - 0.5 })
            .collect();
        let light = theme::rgb(palette.light(), 1.0);
        // SAFETY: geometry construction and draw calls on owned objects.
        unsafe {
            // Area
            let area = self.factory.CreatePathGeometry()?;
            let sink = area.Open()?;
            sink.BeginFigure(Vector2 { X: pts[0].X, Y: y + h }, D2D1_FIGURE_BEGIN_FILLED);
            sink.AddLines(&pts);
            sink.AddLines(&[Vector2 { X: pts[n - 1].X, Y: y + h }]);
            sink.EndFigure(D2D1_FIGURE_END_CLOSED);
            sink.Close()?;
            let fill = self.solid(D2D1_COLOR_F { a: 0.10, ..light })?;
            self.ctx.FillGeometry(&area, &fill, None);
            // Line
            let line = self.factory.CreatePathGeometry()?;
            let sink = line.Open()?;
            sink.BeginFigure(pts[0], D2D1_FIGURE_BEGIN_HOLLOW);
            sink.AddLines(&pts[1..]);
            sink.EndFigure(D2D1_FIGURE_END_OPEN);
            sink.Close()?;
            let stroke = self.solid(D2D1_COLOR_F { a: 0.55, ..light })?;
            let style = self.round_stroke()?;
            self.ctx.DrawGeometry(&line, &stroke, 1.0, &style);
        }
        Ok(())
    }

    fn value_color(level: Level) -> D2D1_COLOR_F {
        match level {
            Level::Normal => theme::T_VALUE,
            Level::Warn => theme::rgb(theme::WARN, 1.0),
            Level::Crit => theme::rgb(theme::CRIT, 1.0),
        }
    }

    fn row(&self, vm: &ViewModel, row: &RowModel, y: f32, width: f32, hc: Option<(D2D1_COLOR_F, D2D1_COLOR_F)>) -> Result<()> {
        let tx = |normal: D2D1_COLOR_F| hc.map(|(_, fg)| fg).unwrap_or(normal);
        let s = self.scale;
        let rh = vm.row_height(row);
        let y0 = snap(y, s);
        let bar_x = theme::PAD_X + theme::LABEL_W + theme::GRID_GAP;
        let value_x = width - theme::PAD_X - theme::VALUE_W;
        let bar_w = value_x - theme::GRID_GAP - bar_x;

        // Label and value are centered on the whole row.
        self.text_in(&self.styles.label, &row.label, rect(theme::PAD_X, y0, theme::PAD_X + theme::LABEL_W, y0 + rh), tx(theme::T_LABEL))?;
        let vc = tx(Self::value_color(row.level));
        match &row.sub {
            Some(sub) => {
                let mid = y0 + rh / 2.0;
                self.text_in(&self.styles.value, &row.value, rect(value_x, mid - 13.0, width - theme::PAD_X, mid + 1.0), vc)?;
                self.text_in(&self.styles.sub, sub, rect(value_x, mid, width - theme::PAD_X, mid + 13.0), tx(theme::T_SUB))?;
            }
            None => self.text_in(&self.styles.value, &row.value, rect(value_x, y0, width - theme::PAD_X, y0 + rh), vc)?,
        }

        // Gauge column: optional sparkline strip above the bar.
        let mut bar_y = y0 + (theme::ROW_H - theme::BAR_H) / 2.0;
        if vm.sparklines {
            if let Some(spark) = row.spark {
                let ring = vm.ring(spark);
                let values: Vec<f32> = ring.iter().collect();
                let max = match spark {
                    Spark::Cpu | Spark::Gpu => 100.0,
                    Spark::Rx | Spark::Tx => ring.max().max(1_048_576.0),
                };
                let strip_y = y0 + 2.0;
                let clip = rect(bar_x, strip_y, bar_x + bar_w, strip_y + theme::SPARK_H);
                // SAFETY: clip push/pop pair around the strip.
                unsafe {
                    self.ctx.PushAxisAlignedClip(&clip, D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
                }
                let r = self.sparkline(bar_x, strip_y, bar_w, theme::SPARK_H, &values, max, row.palette);
                unsafe { self.ctx.PopAxisAlignedClip() };
                r?;
                bar_y = y0 + theme::SPARK_EXTRA + (theme::ROW_H - theme::BAR_H) / 2.0;
            }
        }
        match hc {
            Some((_, fg)) => self.bar_solid(bar_x, bar_y, bar_w, row.frac, fg),
            None => self.bar(bar_x, bar_y, bar_w, row.frac, row.palette),
        }
    }

    /// Draw the whole view. `material` lightens the card fill so a DWM backdrop shows.
    /// `high_contrast` = (background, text) system colors: solid card, single text color, no gradients.
    pub fn draw(&self, vm: &ViewModel, width: f32, height: f32, material: bool, hover: bool, high_contrast: Option<(D2D1_COLOR_F, D2D1_COLOR_F)>) -> Result<()> {
        let s = self.scale;
        let px = 1.0 / s;
        let hc = high_contrast;
        let tx = |normal: D2D1_COLOR_F| hc.map(|(_, fg)| fg).unwrap_or(normal);

        // Card + inner hairline
        let alpha = if material { theme::CARD_ALPHA_MATERIAL } else { theme::CARD_ALPHA_FLAT };
        let card = self.solid(hc.map(|(bg, _)| bg).unwrap_or(theme::rgb(theme::CARD_BG, alpha)))?;
        self.fill_round(rect(0.0, 0.0, width, height), theme::RADIUS, &card);
        let border = self.solid(tx(theme::CARD_BORDER))?;
        self.stroke_round(rect(px / 2.0, px / 2.0, width - px / 2.0, height - px / 2.0), theme::RADIUS - px / 2.0, &border, px);

        // Header: title, gear (hover only), status dot, rule
        let rule = self.solid(tx(theme::RULE))?;
        self.text_in(&self.styles.title, &vm.title, rect(theme::PAD_X + 2.0, 0.0, width / 2.0, theme::HEADER_H), tx(theme::T_TITLE))?;
        let dot_cx = width - theme::PAD_X - theme::DOT_SIZE / 2.0;
        let dot_cy = theme::HEADER_H / 2.0;
        let dot_color = theme::rgb(if vm.status_ok { theme::OK } else { theme::CRIT }, 1.0);
        let glow = self.solid(D2D1_COLOR_F { a: 0.18, ..dot_color })?;
        self.circle(dot_cx, dot_cy, theme::DOT_SIZE / 2.0 + 3.0, &glow);
        let dot = self.solid(dot_color)?;
        self.circle(dot_cx, dot_cy, theme::DOT_SIZE / 2.0, &dot);
        if hover {
            let g = gear_rect(width);
            let pill = self.solid(theme::white(0.09))?;
            self.fill_round(g, 4.0, &pill);
            self.text_in(&self.styles.gear, "\u{E713}", g, tx(theme::T_GEAR_HOVER))?;
        }
        // No header rule: the first section band draws one just below it.

        // Sections
        let mut y = theme::HEADER_H + theme::STATS_PAD;
        for (i, sec) in vm.sections.iter().enumerate() {
            if i > 0 {
                y += theme::GROUP_GAP;
            }
            let by = snap(y, s);
            self.hline(theme::PAD_X, width - theme::PAD_X, by, &rule);
            self.text_in(&self.styles.band, sec.name, rect(theme::PAD_X + 2.0, by + 2.0, width - theme::PAD_X, by + theme::BAND_H), tx(theme::T_BAND))?;
            y += theme::BAND_H;
            for (j, row) in sec.rows.iter().enumerate() {
                if j > 0 {
                    y += theme::ROW_GAP;
                }
                self.row(vm, row, y, width, hc)?;
                y += vm.row_height(row);
            }
        }

        // Footer
        let fy = height - theme::FOOTER_H;
        self.hline(theme::PAD_X, width - theme::PAD_X, fy, &rule);
        self.text_in(&self.styles.footer, &vm.footer_left, rect(theme::PAD_X + 2.0, fy, width * 0.6, height), tx(theme::T_FOOTER))?;
        self.text_in(&self.styles.footer_right, &vm.footer_right, rect(width * 0.4, fy, width - theme::PAD_X, height), tx(theme::T_FOOTER))?;
        Ok(())
    }
}
