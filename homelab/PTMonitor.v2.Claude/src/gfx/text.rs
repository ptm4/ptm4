//! DirectWrite: font family resolution (Segoe UI Variable optical sizes with fallbacks),
//! cached text formats, per-string layouts with tabular figures and letter spacing.

use windows::core::{w, Interface, Result, BOOL, PCWSTR};
use windows::Win32::Graphics::DirectWrite::{
    DWriteCreateFactory, IDWriteFactory, IDWriteFontCollection, IDWriteRenderingParams,
    IDWriteTextFormat, IDWriteTextLayout, IDWriteTextLayout1, IDWriteTypography,
    DWRITE_FACTORY_TYPE_SHARED, DWRITE_FONT_FEATURE, DWRITE_FONT_FEATURE_TAG_TABULAR_FIGURES,
    DWRITE_FONT_STRETCH_NORMAL, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_WEIGHT,
    DWRITE_PARAGRAPH_ALIGNMENT_CENTER, DWRITE_PIXEL_GEOMETRY_FLAT, DWRITE_RENDERING_MODE_NATURAL_SYMMETRIC,
    DWRITE_TEXT_ALIGNMENT, DWRITE_TEXT_METRICS, DWRITE_TEXT_RANGE, DWRITE_WORD_WRAPPING_NO_WRAP,
};

use crate::util::wide;

/// Which optical-size family a style uses.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Tier {
    /// 8–10 DIP labels: "Segoe UI Variable Small".
    Small,
    /// 11–12 DIP values: "Segoe UI Variable Text".
    Text,
    /// Segoe Fluent Icons (gear glyph).
    Icons,
}

pub struct TextStyle {
    pub format: IDWriteTextFormat,
    pub size: f32,
    pub tracking_em: f32,
    pub tabular: bool,
}

pub struct TextEngine {
    pub factory: IDWriteFactory,
    fam_small: Vec<u16>,
    fam_text: Vec<u16>,
    fam_icons: Vec<u16>,
    typo_tabular: IDWriteTypography,
    pub resolved: (String, String, String),
}

fn family_exists(collection: &IDWriteFontCollection, name: &str) -> bool {
    let w = wide(name);
    let mut index = 0u32;
    let mut exists = BOOL(0);
    // SAFETY: out-params are valid locals; the wide string outlives the call.
    unsafe {
        collection
            .FindFamilyName(PCWSTR(w.as_ptr()), &mut index, &mut exists)
            .is_ok()
            && exists.as_bool()
    }
}

fn pick(collection: &IDWriteFontCollection, candidates: &[&str]) -> String {
    candidates
        .iter()
        .find(|c| family_exists(collection, c))
        .unwrap_or(&candidates[candidates.len() - 1])
        .to_string()
}

impl TextEngine {
    pub fn new() -> Result<Self> {
        // SAFETY: factory creation and font-collection query with valid out-params.
        unsafe {
            let factory: IDWriteFactory = DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED)?;
            let mut coll: Option<IDWriteFontCollection> = None;
            factory.GetSystemFontCollection(&mut coll, false)?;
            let coll = coll.ok_or_else(|| windows::core::Error::from_hresult(windows::core::HRESULT(-1)))?;

            let small = pick(&coll, &["Segoe UI Variable Small", "Segoe UI Variable Text", "Segoe UI"]);
            let text = pick(&coll, &["Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI"]);
            let icons = pick(&coll, &["Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol"]);

            let typo_tabular = factory.CreateTypography()?;
            typo_tabular.AddFontFeature(DWRITE_FONT_FEATURE {
                nameTag: DWRITE_FONT_FEATURE_TAG_TABULAR_FIGURES,
                parameter: 1,
            })?;

            Ok(TextEngine {
                factory,
                fam_small: wide(&small),
                fam_text: wide(&text),
                fam_icons: wide(&icons),
                typo_tabular,
                resolved: (small, text, icons),
            })
        }
    }

    fn family(&self, tier: Tier) -> PCWSTR {
        PCWSTR(match tier {
            Tier::Small => self.fam_small.as_ptr(),
            Tier::Text => self.fam_text.as_ptr(),
            Tier::Icons => self.fam_icons.as_ptr(),
        })
    }

    /// Create a cached text format. Vertical centering and no wrapping are always on.
    pub fn style(
        &self,
        tier: Tier,
        size: f32,
        weight: u32,
        align: DWRITE_TEXT_ALIGNMENT,
        tracking_em: f32,
        tabular: bool,
    ) -> Result<TextStyle> {
        // SAFETY: the family string lives as long as `self`.
        unsafe {
            let format = self.factory.CreateTextFormat(
                self.family(tier),
                None,
                DWRITE_FONT_WEIGHT(weight as i32),
                DWRITE_FONT_STYLE_NORMAL,
                DWRITE_FONT_STRETCH_NORMAL,
                size,
                w!("en-us"),
            )?;
            format.SetTextAlignment(align)?;
            format.SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER)?;
            format.SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP)?;
            Ok(TextStyle { format, size, tracking_em, tabular })
        }
    }

    /// Lay out `text` inside a `max_w` × `max_h` box (DIPs).
    pub fn layout(&self, style: &TextStyle, text: &str, max_w: f32, max_h: f32) -> Result<IDWriteTextLayout> {
        let units: Vec<u16> = text.encode_utf16().collect();
        // SAFETY: `units` outlives the call; DirectWrite copies the string.
        unsafe {
            let layout = self.factory.CreateTextLayout(&units, &style.format, max_w.max(1.0), max_h.max(1.0))?;
            let range = DWRITE_TEXT_RANGE { startPosition: 0, length: units.len() as u32 };
            if style.tabular {
                layout.SetTypography(&self.typo_tabular, range)?;
            }
            if style.tracking_em != 0.0 {
                if let Ok(l1) = layout.cast::<IDWriteTextLayout1>() {
                    l1.SetCharacterSpacing(0.0, style.tracking_em * style.size, 0.0, range)?;
                }
            }
            Ok(layout)
        }
    }

    /// (width including trailing whitespace, height) in DIPs.
    pub fn measure(layout: &IDWriteTextLayout) -> (f32, f32) {
        let mut m = DWRITE_TEXT_METRICS::default();
        // SAFETY: valid out-param.
        unsafe {
            let _ = layout.GetMetrics(&mut m);
        }
        (m.widthIncludingTrailingWhitespace, m.height)
    }

    /// Optional tuning for small grayscale text on a dark card (Spike 1 knob).
    pub fn rendering_params(&self, gamma: f32, enhanced_contrast: f32) -> Result<IDWriteRenderingParams> {
        // SAFETY: plain factory call.
        unsafe {
            self.factory.CreateCustomRenderingParams(
                gamma,
                enhanced_contrast,
                0.0,
                DWRITE_PIXEL_GEOMETRY_FLAT,
                DWRITE_RENDERING_MODE_NATURAL_SYMMETRIC,
            )
        }
    }
}
