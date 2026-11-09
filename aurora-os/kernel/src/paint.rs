//! Zeichnen mit Gleitkomma und Alphakanal (dank SSE jetzt schnell).
//!
//! `Image` speichert Pixel als **vormultipliziertes ARGB** (0xAARRGGBB):
//! Die Farbkanäle sind bereits mit Alpha multipliziert. Das macht das
//! Übereinanderlegen („source over“) einfach und schnell:
//!     Ergebnis = Quelle + Ziel × (1 − Alpha_Quelle)

use alloc::vec;
use alloc::vec::Vec;
use libm::{ceilf, floorf, sqrtf};

use crate::font::{self, Weight};

/// Farbe mit Deckkraft (nicht vormultipliziert)
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Rgba {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

impl Rgba {
    pub const fn hex(rgb: u32) -> Self {
        Rgba { r: (rgb >> 16) as u8, g: (rgb >> 8) as u8, b: rgb as u8, a: 255 }
    }

    pub const fn with_alpha(self, a: u8) -> Self {
        Rgba { a, ..self }
    }

    /// Lineare Mischung zweier Farben, t = 0.0 … 1.0
    pub fn lerp(self, o: Rgba, t: f32) -> Rgba {
        let m = |a: u8, b: u8| (a as f32 + (b as f32 - a as f32) * t + 0.5) as u8;
        Rgba { r: m(self.r, o.r), g: m(self.g, o.g), b: m(self.b, o.b), a: m(self.a, o.a) }
    }

    pub fn rgb(self) -> u32 {
        (self.r as u32) << 16 | (self.g as u32) << 8 | self.b as u32
    }
}

pub struct Image {
    pub w: i32,
    pub h: i32,
    pub px: Vec<u32>,
}

impl Image {
    pub fn new(w: i32, h: i32) -> Self {
        Image { w, h, px: vec![0; (w.max(1) * h.max(1)) as usize] }
    }

    /// Inhalt eines anders großen Bildes übernehmen (oben links ausgerichtet)
    pub fn copy_from(&mut self, src: &Image) {
        self.clear();
        let (w, h) = (self.w.min(src.w), self.h.min(src.h));
        for y in 0..h {
            let (d, s) = ((y * self.w) as usize, (y * src.w) as usize);
            self.px[d..d + w as usize].copy_from_slice(&src.px[s..s + w as usize]);
        }
    }

    pub fn clear(&mut self) {
        self.px.fill(0);
    }

    /// Ein Pixel mit Farbe `c` und Abdeckung `cov` (0..1) darüberlegen
    #[inline]
    pub fn blend(&mut self, x: i32, y: i32, c: Rgba, cov: f32) {
        if x < 0 || y < 0 || x >= self.w || y >= self.h || cov <= 0.0 {
            return;
        }
        let a = (c.a as f32 * cov.min(1.0)) as u32; // 0..255
        if a == 0 {
            return;
        }
        let i = (y * self.w + x) as usize;
        let d = self.px[i];
        let inv = 255 - a;
        let ch = |src: u8, shift: u32| -> u32 {
            let dst = (d >> shift) & 0xFF;
            (src as u32 * a + dst * inv + 127) / 255
        };
        let out_a = a + ((d >> 24) * inv + 127) / 255;
        self.px[i] = out_a << 24 | ch(c.r, 16) << 16 | ch(c.g, 8) << 8 | ch(c.b, 0);
    }

    /// Abgerundetes Rechteck, geglättet über eine Distanzfunktion
    pub fn fill_rounded(&mut self, x: f32, y: f32, w: f32, h: f32, r: f32, c: Rgba) {
        let (x0, y0) = (floorf(x) as i32, floorf(y) as i32);
        let (x1, y1) = (ceilf(x + w) as i32, ceilf(y + h) as i32);
        for py in y0.max(0)..y1.min(self.h) {
            for px in x0.max(0)..x1.min(self.w) {
                let d = sdf_rrect(px as f32 + 0.5, py as f32 + 0.5, x, y, w, h, r);
                self.blend(px, py, c, 0.5 - d);
            }
        }
    }

    /// Einfaches Rechteck ohne Kantenglättung – schnell, z. B. für Diagrammflächen
    pub fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: Rgba) {
        for py in y.max(0)..(y + h).min(self.h) {
            for px in x.max(0)..(x + w).min(self.w) {
                self.blend(px, py, c, 1.0);
            }
        }
    }

    /// Abgerundetes Rechteck mit senkrechtem Farbverlauf (für App-Symbole)
    pub fn fill_rounded_gradient(&mut self, x: f32, y: f32, w: f32, h: f32, r: f32, top: Rgba, bottom: Rgba) {
        let (x0, y0) = (floorf(x) as i32, floorf(y) as i32);
        let (x1, y1) = (ceilf(x + w) as i32, ceilf(y + h) as i32);
        for py in y0.max(0)..y1.min(self.h) {
            let c = top.lerp(bottom, ((py as f32 - y) / h).clamp(0.0, 1.0));
            for px in x0.max(0)..x1.min(self.w) {
                let d = sdf_rrect(px as f32 + 0.5, py as f32 + 0.5, x, y, w, h, r);
                self.blend(px, py, c, 0.5 - d);
            }
        }
    }

    /// Umriss eines abgerundeten Rechtecks mit Linienbreite `lw`
    pub fn stroke_rounded(&mut self, x: f32, y: f32, w: f32, h: f32, r: f32, lw: f32, c: Rgba) {
        let (x0, y0) = (floorf(x) as i32 - 1, floorf(y) as i32 - 1);
        let (x1, y1) = (ceilf(x + w) as i32 + 1, ceilf(y + h) as i32 + 1);
        for py in y0.max(0)..y1.min(self.h) {
            for px in x0.max(0)..x1.min(self.w) {
                let d = sdf_rrect(px as f32 + 0.5, py as f32 + 0.5, x, y, w, h, r);
                // Abstand zur Mittellinie des Rands
                let cov = (lw * 0.5 + 0.5 - (d + lw * 0.5).abs()).clamp(0.0, 1.0);
                self.blend(px, py, c, cov);
            }
        }
    }

    pub fn circle(&mut self, cx: f32, cy: f32, r: f32, c: Rgba) {
        self.fill_rounded(cx - r, cy - r, 2.0 * r, 2.0 * r, r, c);
    }

    pub fn ring(&mut self, cx: f32, cy: f32, r: f32, lw: f32, c: Rgba) {
        self.stroke_rounded(cx - r, cy - r, 2.0 * r, 2.0 * r, r, lw, c);
    }

    /// Geglättete Linie (für Diagramme)
    pub fn line(&mut self, ax: f32, ay: f32, bx: f32, by: f32, lw: f32, c: Rgba) {
        let pad = lw + 1.0;
        let (x0, x1) = ((ax.min(bx) - pad) as i32, (ax.max(bx) + pad) as i32);
        let (y0, y1) = ((ay.min(by) - pad) as i32, (ay.max(by) + pad) as i32);
        let (dx, dy) = (bx - ax, by - ay);
        let len2 = (dx * dx + dy * dy).max(1e-6);
        for py in y0.max(0)..=y1.min(self.h - 1) {
            for px in x0.max(0)..=x1.min(self.w - 1) {
                let (qx, qy) = (px as f32 + 0.5 - ax, py as f32 + 0.5 - ay);
                let t = ((qx * dx + qy * dy) / len2).clamp(0.0, 1.0);
                let (ex, ey) = (qx - dx * t, qy - dy * t);
                let d = sqrtf(ex * ex + ey * ey);
                self.blend(px, py, c, lw * 0.5 + 0.5 - d);
            }
        }
    }

    /// Text mit Grundlinie bei `baseline`; liefert die Breite zurück
    pub fn text(&mut self, x: f32, baseline: f32, s: &str, px: f32, weight: Weight, c: Rgba) -> f32 {
        font::draw(self, x, baseline, s, px, weight, c)
    }

    /// Text horizontal zentriert um `cx`
    pub fn text_centered(&mut self, cx: f32, baseline: f32, s: &str, px: f32, weight: Weight, c: Rgba) {
        let w = font::measure(s, px, weight);
        self.text(cx - w / 2.0, baseline, s, px, weight, c);
    }
}

/// Signed Distance Function eines abgerundeten Rechtecks (in Pixeln):
/// negativ = innen, positiv = außen
pub fn sdf_rrect(px: f32, py: f32, x: f32, y: f32, w: f32, h: f32, r: f32) -> f32 {
    let (hw, hh) = (w * 0.5, h * 0.5);
    let r = r.min(hw).min(hh);
    let qx = (px - (x + hw)).abs() - (hw - r);
    let qy = (py - (y + hh)).abs() - (hh - r);
    let (ox, oy) = (qx.max(0.0), qy.max(0.0));
    sqrtf(ox * ox + oy * oy) + qx.max(qy).min(0.0) - r
}
