//! Graphics stack: D3D11 device → DXGI composition swap chain (premultiplied alpha)
//! → DirectComposition visual on the HWND → Direct2D device context on the back buffer.
//!
//! The window has `WS_EX_NOREDIRECTIONBITMAP`, so these are its only pixels; fully
//! transparent pixels show the desktop. Presentation is dirty-only: the caller draws
//! a frame only when something changed, and nothing here runs on a frame clock.

use std::mem::ManuallyDrop;

use windows::core::{Interface, Result};
use windows::Win32::Foundation::{HMODULE, HWND};
use windows::Win32::Graphics::Direct2D::Common::{D2D1_ALPHA_MODE_PREMULTIPLIED, D2D1_PIXEL_FORMAT};
use windows::Win32::Graphics::Direct2D::{
    D2D1CreateFactory, ID2D1Bitmap1, ID2D1Device, ID2D1DeviceContext, ID2D1Factory1, ID2D1Image,
    D2D1_BITMAP_OPTIONS_CANNOT_DRAW, D2D1_BITMAP_OPTIONS_TARGET, D2D1_BITMAP_PROPERTIES1,
    D2D1_DEVICE_CONTEXT_OPTIONS_NONE, D2D1_FACTORY_TYPE_SINGLE_THREADED,
    D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE,
};
use windows::Win32::Graphics::Direct3D::{
    D3D_DRIVER_TYPE, D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP, D3D_FEATURE_LEVEL,
    D3D_FEATURE_LEVEL_10_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_11_1,
};
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
    D3D11_CREATE_DEVICE_SINGLETHREADED, D3D11_SDK_VERSION,
};
use windows::Win32::Graphics::DirectComposition::{
    DCompositionCreateDevice3, IDCompositionDesktopDevice, IDCompositionTarget,
    IDCompositionVisual2, IDCompositionVisual3,
};
use windows::Win32::Graphics::Dxgi::Common::{
    DXGI_ALPHA_MODE_PREMULTIPLIED, DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_FORMAT_UNKNOWN,
    DXGI_SAMPLE_DESC,
};
use windows::Win32::Graphics::Dxgi::{
    CreateDXGIFactory2, IDXGIDevice, IDXGIFactory2, IDXGIOutput, IDXGISurface, IDXGISwapChain1,
    DXGI_CREATE_FACTORY_FLAGS, DXGI_PRESENT, DXGI_SCALING_STRETCH, DXGI_SWAP_CHAIN_DESC1,
    DXGI_SWAP_CHAIN_FLAG, DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL, DXGI_USAGE_RENDER_TARGET_OUTPUT,
};

use crate::theme;

pub struct Gfx {
    pub d3d: ID3D11Device,
    pub dxgi_device: IDXGIDevice,
    pub swapchain: IDXGISwapChain1,
    pub dcomp: IDCompositionDesktopDevice,
    pub target: IDCompositionTarget,
    pub visual: IDCompositionVisual2,
    pub d2d_factory: ID2D1Factory1,
    pub d2d_device: ID2D1Device,
    pub ctx: ID2D1DeviceContext,
    pub width_px: u32,
    pub height_px: u32,
    pub dpi: u32,
    /// True when the WARP software rasterizer is in use (by preference or hardware fallback).
    pub warp: bool,
}

/// A frame in progress; drop-safe. Obtained from [`Gfx::begin`], finished by [`Gfx::end`].
pub struct Frame {
    bitmap: ID2D1Bitmap1,
}

fn create_d3d(driver: D3D_DRIVER_TYPE) -> Result<ID3D11Device> {
    let levels = [
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1,
        D3D_FEATURE_LEVEL_10_0,
    ];
    let mut device: Option<ID3D11Device> = None;
    let mut level = D3D_FEATURE_LEVEL::default();
    // SAFETY: out-params are valid for the duration of the call.
    unsafe {
        D3D11CreateDevice(
            None,
            driver,
            HMODULE::default(),
            D3D11_CREATE_DEVICE_BGRA_SUPPORT | D3D11_CREATE_DEVICE_SINGLETHREADED,
            Some(&levels),
            D3D11_SDK_VERSION,
            Some(&mut device),
            Some(&mut level),
            None,
        )?;
    }
    device.ok_or_else(|| windows::core::Error::from_hresult(windows::core::HRESULT(-1)))
}

impl Gfx {
    /// Build the whole chain for `hwnd`. `width_px`/`height_px` are device pixels.
    /// `prefer_warp`: use the software rasterizer (default). `PTM2_WARP=1|0` overrides for experiments.
    pub fn new(hwnd: HWND, width_px: u32, height_px: u32, dpi: u32, prefer_warp: bool) -> Result<Self> {
        let force_warp = match std::env::var("PTM2_WARP").ok().as_deref() {
            Some("1") => true,
            Some("0") => false,
            _ => prefer_warp,
        };
        let (d3d, warp) = if force_warp {
            (create_d3d(D3D_DRIVER_TYPE_WARP)?, true)
        } else {
            match create_d3d(D3D_DRIVER_TYPE_HARDWARE) {
                Ok(d) => (d, false),
                Err(e) => {
                    crate::logf!("D3D11 hardware device failed ({e}); falling back to WARP");
                    (create_d3d(D3D_DRIVER_TYPE_WARP)?, true)
                }
            }
        };
        // SAFETY: COM calls on objects we own; all pointers are to live locals.
        unsafe {
            let dxgi_device: IDXGIDevice = d3d.cast()?;
            let factory: IDXGIFactory2 = CreateDXGIFactory2(DXGI_CREATE_FACTORY_FLAGS(0))?;
            let desc = DXGI_SWAP_CHAIN_DESC1 {
                Width: width_px.max(1),
                Height: height_px.max(1),
                Format: DXGI_FORMAT_B8G8R8A8_UNORM,
                Stereo: false.into(),
                SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                BufferUsage: DXGI_USAGE_RENDER_TARGET_OUTPUT,
                BufferCount: 2,
                Scaling: DXGI_SCALING_STRETCH,
                SwapEffect: DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL,
                AlphaMode: DXGI_ALPHA_MODE_PREMULTIPLIED,
                Flags: 0,
            };
            let swapchain =
                factory.CreateSwapChainForComposition(&d3d, &desc, None::<&IDXGIOutput>)?;

            let dcomp: IDCompositionDesktopDevice = DCompositionCreateDevice3(&dxgi_device)?;
            // `topmost` here is DirectComposition-internal (visual tree above the HWND's own
            // surface) and has nothing to do with the window's z-order layer setting.
            let target = dcomp.CreateTargetForHwnd(hwnd, true)?;
            let visual: IDCompositionVisual2 = dcomp.CreateVisual()?;
            visual.SetContent(&swapchain)?;
            target.SetRoot(&visual)?;
            dcomp.Commit()?;

            let d2d_factory: ID2D1Factory1 =
                D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, None)?;
            let d2d_device = d2d_factory.CreateDevice(&dxgi_device)?;
            let ctx = d2d_device.CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE)?;
            ctx.SetDpi(dpi as f32, dpi as f32);
            // ClearType needs an opaque background; on a premultiplied transparent target
            // grayscale is what Windows' own translucent surfaces use.
            ctx.SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);

            Ok(Gfx {
                d3d,
                dxgi_device,
                swapchain,
                dcomp,
                target,
                visual,
                d2d_factory,
                d2d_device,
                ctx,
                width_px,
                height_px,
                dpi,
                warp,
            })
        }
    }

    /// Start a frame: bind the back buffer as the D2D target and clear it to transparent.
    pub fn begin(&self) -> Result<Frame> {
        // SAFETY: the surface and bitmap are released with the returned Frame.
        unsafe {
            let surface: IDXGISurface = self.swapchain.GetBuffer(0)?;
            let props = D2D1_BITMAP_PROPERTIES1 {
                pixelFormat: D2D1_PIXEL_FORMAT {
                    format: DXGI_FORMAT_B8G8R8A8_UNORM,
                    alphaMode: D2D1_ALPHA_MODE_PREMULTIPLIED,
                },
                dpiX: self.dpi as f32,
                dpiY: self.dpi as f32,
                bitmapOptions: D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
                colorContext: ManuallyDrop::new(None),
            };
            let bitmap = self.ctx.CreateBitmapFromDxgiSurface(&surface, Some(&props))?;
            self.ctx.SetTarget(&bitmap);
            self.ctx.BeginDraw();
            self.ctx.Clear(Some(&theme::TRANSPARENT));
            Ok(Frame { bitmap })
        }
    }

    /// Finish the frame and present it. Any failure here means the device should be
    /// recreated by the caller (device removed / reset / hung).
    pub fn end(&self, frame: Frame) -> Result<()> {
        // SAFETY: matches the BeginDraw in `begin`; the target is unbound before Present.
        unsafe {
            let drawn = self.ctx.EndDraw(None, None);
            self.ctx.SetTarget(None::<&ID2D1Image>);
            drop(frame.bitmap);
            drawn?;
            self.swapchain.Present(1, DXGI_PRESENT(0)).ok()
        }
    }

    /// Resize the swap chain (device pixels) and update the DPI used for DIP math.
    pub fn resize(&mut self, width_px: u32, height_px: u32, dpi: u32) -> Result<()> {
        if width_px == self.width_px && height_px == self.height_px && dpi == self.dpi {
            return Ok(());
        }
        // SAFETY: no outstanding back-buffer references exist between frames.
        unsafe {
            self.ctx.SetTarget(None::<&ID2D1Image>);
            self.swapchain.ResizeBuffers(
                0,
                width_px.max(1),
                height_px.max(1),
                DXGI_FORMAT_UNKNOWN,
                DXGI_SWAP_CHAIN_FLAG(0),
            )?;
            self.ctx.SetDpi(dpi as f32, dpi as f32);
        }
        self.width_px = width_px;
        self.height_px = height_px;
        self.dpi = dpi;
        Ok(())
    }

    /// Whole-widget opacity without a redraw (DirectComposition property).
    pub fn set_opacity(&self, opacity: f32) -> Result<()> {
        // SAFETY: COM calls on owned objects.
        unsafe {
            let v3: IDCompositionVisual3 = self.visual.cast()?;
            v3.SetOpacity2(opacity.clamp(0.05, 1.0))?;
            self.dcomp.Commit()
        }
    }

    pub fn scale(&self) -> f32 {
        self.dpi as f32 / 96.0
    }

    /// Width/height in DIPs.
    pub fn size_dip(&self) -> (f32, f32) {
        (
            self.width_px as f32 / self.scale(),
            self.height_px as f32 / self.scale(),
        )
    }
}
