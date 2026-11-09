//! Vektorschrift: Inter (SIL Open Font License), gerastert mit `fontdue`.
//!
//! Eine TrueType-Schrift beschreibt jedes Zeichen als Kurven. Erst beim
//! „Rastern“ entsteht daraus ein Graustufenbild in der gewünschten Größe.
//! Weil das teuer ist, merken wir uns jedes gerasterte Zeichen (Cache).
//!
//! Wichtig: Der Fehlerbildschirm nutzt weiterhin die alte Pixelschrift –
//! diese hier braucht den Heap, und der könnte im Fehlerfall kaputt sein.

use alloc::collections::BTreeMap;
use alloc::vec::Vec;
use fontdue::{Font, FontSettings};
use libm::roundf;

use crate::paint::{Image, Rgba};
use crate::task::ThreadMutex;

static INTER_REGULAR: &[u8] = include_bytes!("../fonts/Inter-Regular.ttf");
static INTER_SEMIBOLD: &[u8] = include_bytes!("../fonts/Inter-SemiBold.ttf");

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Weight {
    Regular,
    SemiBold,
}

struct Glyph {
    xmin: i32,
    ymin: i32,
    width: i32,
    height: i32,
    advance: f32,
    bitmap: Vec<u8>,
}

struct Fonts {
    regular: Font,
    semibold: Font,
    // Schlüssel: (Schnitt, Zeichen, Größe in 1/4 Pixel)
    cache: BTreeMap<(Weight, char, u32), Glyph>,
}

// Mehrere App-Threads rastern gleichzeitig -> Sperre mit „yield“ beim Warten
static FONTS: ThreadMutex<Option<Fonts>> = ThreadMutex::new(None);

pub fn init() -> Result<usize, &'static str> {
    let load = |data: &'static [u8]| Font::from_bytes(data, FontSettings::default()).map_err(|_| "Schrift defekt");
    let regular = load(INTER_REGULAR)?;
    let semibold = load(INTER_SEMIBOLD)?;
    let glyphs = regular.glyph_count() as usize;
    *FONTS.lock() = Some(Fonts { regular, semibold, cache: BTreeMap::new() });
    Ok(glyphs)
}

impl Fonts {
    fn font(&self, w: Weight) -> &Font {
        match w {
            Weight::Regular => &self.regular,
            Weight::SemiBold => &self.semibold,
        }
    }

    fn glyph(&mut self, w: Weight, ch: char, px: f32) -> &Glyph {
        let key = (w, ch, (px * 4.0) as u32);
        if !self.cache.contains_key(&key) {
            let (m, bitmap) = self.font(w).rasterize(ch, px);
            let g = Glyph {
                xmin: m.xmin,
                ymin: m.ymin,
                width: m.width as i32,
                height: m.height as i32,
                advance: m.advance_width,
                bitmap,
            };
            self.cache.insert(key, g);
        }
        &self.cache[&key]
    }
}

/// Breite eines Textes in Pixeln
pub fn measure(s: &str, px: f32, w: Weight) -> f32 {
    let mut guard = FONTS.lock();
    let Some(f) = guard.as_mut() else { return 0.0 };
    s.chars().map(|ch| f.glyph(w, ch, px).advance).sum()
}

/// Text zeichnen. `baseline` = Grundlinie (Unterkante von Buchstaben ohne Unterlänge)
pub fn draw(img: &mut Image, x: f32, baseline: f32, s: &str, px: f32, w: Weight, c: Rgba) -> f32 {
    let mut guard = FONTS.lock();
    let Some(f) = guard.as_mut() else { return 0.0 };
    let mut pen = x;
    for ch in s.chars() {
        let g = f.glyph(w, ch, px);
        let gx = roundf(pen + g.xmin as f32) as i32;
        let gy = roundf(baseline) as i32 - g.height - g.ymin;
        for row in 0..g.height {
            for col in 0..g.width {
                let cov = g.bitmap[(row * g.width + col) as usize];
                if cov != 0 {
                    img.blend(gx + col, gy + row, c, cov as f32 / 255.0);
                }
            }
        }
        pen += g.advance;
    }
    pen - x
}

/// Anzahl der bisher gerasterten (gecachten) Zeichen
pub fn cached_glyphs() -> usize {
    FONTS.lock().as_ref().map(|f| f.cache.len()).unwrap_or(0)
}
