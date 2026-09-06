//! Icon generator: renders the PTMonitor 2 tile-and-pulse icon at 8 sizes with Direct2D
//! into WIC bitmaps, encodes PNG previews, and writes `assets/icon.ico` by hand
//! (32-bpp DIB entries for 16–48 px for maximum compatibility, PNG entries for 64–256 px).
//! Also emits `assets/icon.svg` from the same geometry as a reference.
//!
//! Run from the crate root: `cargo run --release --bin make_icon`

use std::path::{Path, PathBuf};

use ptmonitor2::theme;
use windows::core::{Interface, Result, PCWSTR};
use windows::Win32::Foundation::GENERIC_WRITE;
use windows::Win32::Graphics::Direct2D::Common::{
    D2D1_ALPHA_MODE_PREMULTIPLIED, D2D1_COLOR_F, D2D1_FIGURE_BEGIN_HOLLOW, D2D1_FIGURE_END_OPEN,
    D2D1_GRADIENT_STOP, D2D1_PIXEL_FORMAT, D2D_RECT_F,
};
use windows::Win32::Graphics::Direct2D::{
    D2D1CreateFactory, ID2D1Brush, ID2D1Factory1, ID2D1RenderTarget, D2D1_CAP_STYLE_ROUND,
    D2D1_DASH_STYLE_SOLID, D2D1_ELLIPSE, D2D1_EXTEND_MODE_CLAMP, D2D1_FACTORY_TYPE_SINGLE_THREADED,
    D2D1_FEATURE_LEVEL_DEFAULT, D2D1_GAMMA_2_2, D2D1_LINEAR_GRADIENT_BRUSH_PROPERTIES,
    D2D1_LINE_JOIN_ROUND, D2D1_RENDER_TARGET_PROPERTIES, D2D1_RENDER_TARGET_TYPE_DEFAULT,
    D2D1_RENDER_TARGET_USAGE_NONE, D2D1_ROUNDED_RECT, D2D1_STROKE_STYLE_PROPERTIES1,
    D2D1_STROKE_TRANSFORM_TYPE_NORMAL,
};
use windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM;
use windows::Win32::Graphics::Imaging::{
    CLSID_WICImagingFactory, GUID_ContainerFormatPng, GUID_WICPixelFormat32bppPBGRA,
    IWICBitmap, IWICBitmapSource, IWICImagingFactory, WICBitmapCacheOnDemand,
    WICBitmapEncoderNoCache,
};
use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED};
use windows_numerics::Vector2;

const SIZES: [u32; 8] = [16, 20, 24, 32, 48, 64, 128, 256];
const PNG_ENTRY_MIN: u32 = 64;

const TILE_TOP: u32 = 0x161b2a;
const TILE_BOTTOM: u32 = 0x0e1119;
const PULSE_A: u32 = 0x3a7bd5;
const PULSE_B: u32 = 0xa78bfa;

/// Normalized pulse vertices (x, y in 0..1, y down) per size class.
fn pulse_points(size: u32) -> Vec<(f32, f32)> {
    if size <= 16 {
        vec![(0.19, 0.66), (0.42, 0.62), (0.56, 0.31), (0.80, 0.47)]
    } else if size <= 32 {
        vec![(0.17, 0.63), (0.36, 0.59), (0.48, 0.31), (0.60, 0.75), (0.83, 0.43)]
    } else {
        vec![(0.17, 0.62), (0.32, 0.60), (0.42, 0.31), (0.52, 0.78), (0.62, 0.50), (0.72, 0.56), (0.83, 0.42)]
    }
}

fn stroke_width(size: u32) -> f32 {
    let s = size as f32;
    if size <= 16 {
        2.0
    } else if size <= 32 {
        (s * 0.08).max(2.0)
    } else {
        s * 0.06
    }
}

struct Geometry {
    size: u32,
    inset: f32,
    radius: f32,
    stroke: f32,
    points: Vec<Vector2>,
    dot_r: f32,
}

fn geometry(size: u32) -> Geometry {
    let s = size as f32;
    let inset = if size >= 32 { (s / 16.0).round() } else { 0.0 };
    let stroke = stroke_width(size);
    let points = pulse_points(size).into_iter().map(|(x, y)| Vector2 { X: x * s, Y: y * s }).collect::<Vec<_>>();
    Geometry {
        size,
        inset,
        radius: (s - 2.0 * inset) * 0.20,
        stroke,
        dot_r: (stroke * 0.9).max(1.5),
        points,
    }
}

struct Wic {
    factory: IWICImagingFactory,
    d2d: ID2D1Factory1,
}

impl Wic {
    fn new() -> Result<Self> {
        // SAFETY: COM init on this thread; factory creation.
        unsafe {
            let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            let factory: IWICImagingFactory = CoCreateInstance(&CLSID_WICImagingFactory, None, CLSCTX_INPROC_SERVER)?;
            let d2d: ID2D1Factory1 = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, None)?;
            Ok(Wic { factory, d2d })
        }
    }

    fn render(&self, g: &Geometry) -> Result<IWICBitmap> {
        // SAFETY: WIC/D2D calls on owned objects; all structs are valid locals.
        unsafe {
            let bmp = self.factory.CreateBitmap(g.size, g.size, &GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnDemand)?;
            let props = D2D1_RENDER_TARGET_PROPERTIES {
                r#type: D2D1_RENDER_TARGET_TYPE_DEFAULT,
                pixelFormat: D2D1_PIXEL_FORMAT { format: DXGI_FORMAT_B8G8R8A8_UNORM, alphaMode: D2D1_ALPHA_MODE_PREMULTIPLIED },
                dpiX: 96.0,
                dpiY: 96.0,
                usage: D2D1_RENDER_TARGET_USAGE_NONE,
                minLevel: D2D1_FEATURE_LEVEL_DEFAULT,
            };
            let rt: ID2D1RenderTarget = self.d2d.CreateWicBitmapRenderTarget(&bmp, &props)?;
            rt.BeginDraw();
            rt.Clear(Some(&theme::TRANSPARENT));
            self.draw(&rt, g)?;
            rt.EndDraw(None, None)?;
            Ok(bmp)
        }
    }

    unsafe fn gradient(&self, rt: &ID2D1RenderTarget, a: u32, b: u32, from: Vector2, to: Vector2) -> Result<ID2D1Brush> {
        let stops = [
            D2D1_GRADIENT_STOP { position: 0.0, color: theme::rgb(a, 1.0) },
            D2D1_GRADIENT_STOP { position: 1.0, color: theme::rgb(b, 1.0) },
        ];
        let coll = rt.CreateGradientStopCollection(&stops, D2D1_GAMMA_2_2, D2D1_EXTEND_MODE_CLAMP)?;
        let props = D2D1_LINEAR_GRADIENT_BRUSH_PROPERTIES { startPoint: from, endPoint: to };
        Ok(rt.CreateLinearGradientBrush(&props, None, &coll)?.into())
    }

    unsafe fn solid(&self, rt: &ID2D1RenderTarget, c: D2D1_COLOR_F) -> Result<ID2D1Brush> {
        Ok(rt.CreateSolidColorBrush(&c, None)?.into())
    }

    unsafe fn draw(&self, rt: &ID2D1RenderTarget, g: &Geometry) -> Result<()> {
        let s = g.size as f32;
        // Tile
        let tile = D2D_RECT_F { left: g.inset, top: g.inset, right: s - g.inset, bottom: s - g.inset };
        let fill = self.gradient(rt, TILE_TOP, TILE_BOTTOM, Vector2 { X: 0.0, Y: tile.top }, Vector2 { X: 0.0, Y: tile.bottom })?;
        rt.FillRoundedRectangle(&D2D1_ROUNDED_RECT { rect: tile, radiusX: g.radius, radiusY: g.radius }, &fill);
        if g.size >= 24 {
            let hl = self.solid(rt, theme::white(0.08))?;
            let inner = D2D_RECT_F { left: tile.left + 0.5, top: tile.top + 0.5, right: tile.right - 0.5, bottom: tile.bottom - 0.5 };
            rt.DrawRoundedRectangle(&D2D1_ROUNDED_RECT { rect: inner, radiusX: g.radius - 0.5, radiusY: g.radius - 0.5 }, &hl, 1.0, None);
        }
        // Baseline
        if g.size >= 32 {
            let base = self.solid(rt, theme::white(0.12))?;
            let y = (s * 0.66).round() + 0.5;
            rt.DrawLine(Vector2 { X: s * 0.17, Y: y }, Vector2 { X: s * 0.83, Y: y }, &base, 1.0, None);
        }
        // Pulse
        let path = self.d2d.CreatePathGeometry()?;
        let sink = path.Open()?;
        sink.BeginFigure(g.points[0], D2D1_FIGURE_BEGIN_HOLLOW);
        sink.AddLines(&g.points[1..]);
        sink.EndFigure(D2D1_FIGURE_END_OPEN);
        sink.Close()?;
        let style = self.d2d.CreateStrokeStyle(
            &D2D1_STROKE_STYLE_PROPERTIES1 {
                startCap: D2D1_CAP_STYLE_ROUND,
                endCap: D2D1_CAP_STYLE_ROUND,
                dashCap: D2D1_CAP_STYLE_ROUND,
                lineJoin: D2D1_LINE_JOIN_ROUND,
                miterLimit: 1.0,
                dashStyle: D2D1_DASH_STYLE_SOLID,
                dashOffset: 0.0,
                transformType: D2D1_STROKE_TRANSFORM_TYPE_NORMAL,
            },
            None,
        )?;
        let first = g.points[0];
        let last = *g.points.last().unwrap();
        let pulse = self.gradient(rt, PULSE_A, PULSE_B, Vector2 { X: first.X, Y: 0.0 }, Vector2 { X: last.X, Y: 0.0 })?;
        rt.DrawGeometry(&path, &pulse, g.stroke, &style);
        // End dot with glow
        let glow = self.solid(rt, theme::rgb(theme::OK, 0.28))?;
        rt.FillEllipse(&D2D1_ELLIPSE { point: last, radiusX: g.dot_r * 2.2, radiusY: g.dot_r * 2.2 }, &glow);
        let dot = self.solid(rt, theme::rgb(theme::OK, 1.0))?;
        rt.FillEllipse(&D2D1_ELLIPSE { point: last, radiusX: g.dot_r, radiusY: g.dot_r }, &dot);
        Ok(())
    }

    fn save_png(&self, bmp: &IWICBitmap, path: &Path) -> Result<()> {
        let wide: Vec<u16> = path.as_os_str().encode_wide_nul();
        // SAFETY: WIC encoder pipeline with valid objects; the path outlives the call.
        unsafe {
            let stream = self.factory.CreateStream()?;
            stream.InitializeFromFilename(PCWSTR(wide.as_ptr()), GENERIC_WRITE.0)?;
            let encoder = self.factory.CreateEncoder(&GUID_ContainerFormatPng, std::ptr::null())?;
            encoder.Initialize(&stream, WICBitmapEncoderNoCache)?;
            let mut frame = None;
            let mut opts = None;
            encoder.CreateNewFrame(&mut frame, &mut opts)?;
            let frame = frame.unwrap();
            frame.Initialize(opts.as_ref())?;
            let src: IWICBitmapSource = bmp.cast()?;
            frame.WriteSource(&src, std::ptr::null())?;
            frame.Commit()?;
            encoder.Commit()?;
        }
        Ok(())
    }

    /// Premultiplied BGRA pixels, top-down.
    fn pixels(&self, bmp: &IWICBitmap, size: u32) -> Result<Vec<u8>> {
        let stride = size * 4;
        let mut buf = vec![0u8; (stride * size) as usize];
        // SAFETY: buffer sized for the whole bitmap.
        unsafe {
            bmp.CopyPixels(std::ptr::null(), stride, &mut buf)?;
        }
        Ok(buf)
    }
}

trait WideNul {
    fn encode_wide_nul(&self) -> Vec<u16>;
}
impl WideNul for std::ffi::OsStr {
    fn encode_wide_nul(&self) -> Vec<u16> {
        use std::os::windows::ffi::OsStrExt;
        self.encode_wide().chain(std::iter::once(0)).collect()
    }
}

/// 32-bpp BITMAPINFOHEADER icon image: XOR (straight-alpha BGRA, bottom-up) + empty AND mask.
fn dib_entry(size: u32, premul: &[u8]) -> Vec<u8> {
    let w = size as usize;
    let and_stride = w.div_ceil(32) * 4;
    let mut out = Vec::with_capacity(40 + w * w * 4 + and_stride * w);
    let put32 = |o: &mut Vec<u8>, v: u32| o.extend_from_slice(&v.to_le_bytes());
    let put16 = |o: &mut Vec<u8>, v: u16| o.extend_from_slice(&v.to_le_bytes());
    put32(&mut out, 40);
    put32(&mut out, size);
    put32(&mut out, size * 2);
    put16(&mut out, 1);
    put16(&mut out, 32);
    put32(&mut out, 0);
    put32(&mut out, (w * w * 4 + and_stride * w) as u32);
    put32(&mut out, 0);
    put32(&mut out, 0);
    put32(&mut out, 0);
    put32(&mut out, 0);
    for y in (0..w).rev() {
        for x in 0..w {
            let i = (y * w + x) * 4;
            let (b, g, r, a) = (premul[i], premul[i + 1], premul[i + 2], premul[i + 3]);
            let un = |c: u8| if a == 0 { 0 } else { ((c as u32 * 255 + a as u32 / 2) / a as u32).min(255) as u8 };
            out.extend_from_slice(&[un(b), un(g), un(r), a]);
        }
    }
    out.extend(std::iter::repeat_n(0u8, and_stride * w));
    out
}

fn write_ico(path: &Path, entries: &[(u32, Vec<u8>)]) -> std::io::Result<()> {
    let mut out = Vec::new();
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes());
    out.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    let mut offset = 6 + 16 * entries.len() as u32;
    for (size, data) in entries {
        let dim = if *size >= 256 { 0u8 } else { *size as u8 };
        out.extend_from_slice(&[dim, dim, 0, 0]);
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&32u16.to_le_bytes());
        out.extend_from_slice(&(data.len() as u32).to_le_bytes());
        out.extend_from_slice(&offset.to_le_bytes());
        offset += data.len() as u32;
    }
    for (_, data) in entries {
        out.extend_from_slice(data);
    }
    std::fs::write(path, out)
}

fn svg(size: u32) -> String {
    let g = geometry(size);
    let s = size as f32;
    let pts: Vec<String> = g.points.iter().map(|p| format!("{:.2},{:.2}", p.X, p.Y)).collect();
    let last = g.points.last().unwrap();
    format!(
        r##"<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#{TILE_TOP:06x}"/><stop offset="1" stop-color="#{TILE_BOTTOM:06x}"/></linearGradient>
    <linearGradient id="pulse" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#{PULSE_A:06x}"/><stop offset="1" stop-color="#{PULSE_B:06x}"/></linearGradient>
  </defs>
  <rect x="{i}" y="{i}" width="{tw}" height="{tw}" rx="{r}" fill="url(#tile)"/>
  <rect x="{i2}" y="{i2}" width="{tw2}" height="{tw2}" rx="{r2}" fill="none" stroke="#ffffff" stroke-opacity="0.08"/>
  <line x1="{bx0}" y1="{by}" x2="{bx1}" y2="{by}" stroke="#ffffff" stroke-opacity="0.12"/>
  <polyline points="{pts}" fill="none" stroke="url(#pulse)" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{lx}" cy="{ly}" r="{gr}" fill="#{OK:06x}" fill-opacity="0.28"/>
  <circle cx="{lx}" cy="{ly}" r="{dr}" fill="#{OK:06x}"/>
</svg>
"##,
        i = g.inset,
        tw = s - 2.0 * g.inset,
        r = g.radius,
        i2 = g.inset + 0.5,
        tw2 = s - 2.0 * g.inset - 1.0,
        r2 = g.radius - 0.5,
        bx0 = s * 0.17,
        bx1 = s * 0.83,
        by = (s * 0.66).round() + 0.5,
        pts = pts.join(" "),
        sw = g.stroke,
        lx = last.X,
        ly = last.Y,
        gr = g.dot_r * 2.2,
        dr = g.dot_r,
        OK = theme::OK,
    )
}

fn main() -> Result<()> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let assets = root.join("assets");
    let preview = assets.join("preview");
    std::fs::create_dir_all(&preview).expect("create assets/preview");

    let wic = Wic::new()?;
    let mut entries: Vec<(u32, Vec<u8>)> = Vec::new();
    for &size in &SIZES {
        let g = geometry(size);
        let bmp = wic.render(&g)?;
        let png_path = preview.join(format!("icon-{size}.png"));
        wic.save_png(&bmp, &png_path)?;
        let data = if size >= PNG_ENTRY_MIN {
            std::fs::read(&png_path).expect("read png back")
        } else {
            dib_entry(size, &wic.pixels(&bmp, size)?)
        };
        println!("{size:>3} px: {} bytes ({})", data.len(), if size >= PNG_ENTRY_MIN { "png" } else { "dib" });
        entries.push((size, data));
    }
    let ico = assets.join("icon.ico");
    write_ico(&ico, &entries).expect("write icon.ico");
    std::fs::write(assets.join("icon.svg"), svg(256)).expect("write icon.svg");
    println!("wrote {} ({} bytes) + {} previews + icon.svg", ico.display(), std::fs::metadata(&ico).map(|m| m.len()).unwrap_or(0), SIZES.len());
    Ok(())
}
