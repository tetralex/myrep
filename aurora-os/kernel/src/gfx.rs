//! Minimale 2D-Grafik direkt auf dem Framebuffer.
//! Alles in Ganzzahl-/Festkomma-Arithmetik: Der Kernel-Target hat SSE
//! deaktiviert, Gleitkomma wäre nur per Software-Emulation möglich.

use noto_sans_mono_bitmap::{FontWeight, RasterHeight, get_raster, get_raster_width};

#[derive(Clone, Copy)]
pub struct Color {
    pub r: u8,
    pub g: u8,
    pub b: u8,
}

impl Color {
    pub const fn hex(rgb: u32) -> Self {
        Color { r: (rgb >> 16) as u8, g: (rgb >> 8) as u8, b: rgb as u8 }
    }

    /// Lineare Mischung: t = 0..=256 (256 = vollständig `other`)
    pub fn mix(self, other: Color, t: u32) -> Color {
        let m = |a: u8, b: u8| ((a as u32 * (256 - t) + b as u32 * t) >> 8) as u8;
        Color { r: m(self.r, other.r), g: m(self.g, other.g), b: m(self.b, other.b) }
    }
}

/// Eine Zeichenfläche über dem linearen Framebuffer (32 bpp).
pub struct Canvas {
    ptr: *mut u32,
    pub width: i32,
    pub height: i32,
    stride: usize, // Pixel pro Zeile (pitch / 4)
    shift: (u8, u8, u8),
    clip: (i32, i32, i32, i32), // nur innerhalb (x0, y0, x1, y1) wird gezeichnet
}

/// Rechteck in Bildschirmkoordinaten
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Rect {
    pub const fn new(x: i32, y: i32, w: i32, h: i32) -> Self {
        Rect { x, y, w, h }
    }

    pub fn intersects(&self, o: &Rect) -> bool {
        self.x < o.x + o.w && o.x < self.x + self.w && self.y < o.y + o.h && o.y < self.y + self.h
    }
}

impl Canvas {
    /// # Safety
    /// `ptr` muss auf einen gültigen 32-bpp-Framebuffer der angegebenen Größe zeigen.
    pub unsafe fn new(ptr: *mut u32, width: u64, height: u64, pitch: u64, shift: (u8, u8, u8)) -> Self {
        let (w, h) = (width as i32, height as i32);
        Canvas { ptr, width: w, height: h, stride: (pitch / 4) as usize, shift, clip: (0, 0, w, h) }
    }

    fn pack(&self, c: Color) -> u32 {
        (c.r as u32) << self.shift.0 | (c.g as u32) << self.shift.1 | (c.b as u32) << self.shift.2
    }

    fn unpack(&self, v: u32) -> Color {
        Color { r: (v >> self.shift.0) as u8, g: (v >> self.shift.1) as u8, b: (v >> self.shift.2) as u8 }
    }

    #[inline]
    fn idx(&self, x: i32, y: i32) -> Option<usize> {
        let (x0, y0, x1, y1) = self.clip;
        (x >= x0 && y >= y0 && x < x1 && y < y1).then(|| y as usize * self.stride + x as usize)
    }

    pub fn put(&mut self, x: i32, y: i32, c: Color) {
        if let Some(i) = self.idx(x, y) {
            // volatile: der Compiler darf Schreibzugriffe auf MMIO nicht wegoptimieren
            unsafe { self.ptr.add(i).write_volatile(self.pack(c)) };
        }
    }

    /// Alpha-Blending: alpha = 0..=256
    pub fn blend(&mut self, x: i32, y: i32, c: Color, alpha: u32) {
        if alpha == 0 {
            return;
        }
        if let Some(i) = self.idx(x, y) {
            unsafe {
                let p = self.ptr.add(i);
                let bg = self.unpack(p.read_volatile());
                p.write_volatile(self.pack(bg.mix(c, alpha.min(256))));
            }
        }
    }

    /// Hintergrund: vertikaler Verlauf plus zwei weiche „Polarlicht“-Lichtflecken.
    pub fn aurora_background(&mut self, top: Color, bottom: Color, glows: &[(i32, i32, i32, Color, u32)]) {
        for y in 0..self.height {
            let base = top.mix(bottom, (y as u32 * 256) / self.height as u32);
            for x in 0..self.width {
                let mut c = base;
                for &(gx, gy, radius, color, strength) in glows {
                    let (dx, dy) = ((x - gx) as i64, (y - gy) as i64);
                    let d = isqrt((dx * dx + dy * dy) as u64) as i32;
                    if d < radius {
                        // quadratischer Abfall zum Rand hin -> weicher Übergang
                        let t = ((radius - d) * 256 / radius) as u32;
                        c = c.mix(color, (t * t / 256) * strength / 256);
                    }
                }
                self.put(x, y, c);
            }
        }
    }

    /// Abgerundetes Rechteck mit Kantenglättung (Anti-Aliasing).
    pub fn rounded_rect(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: Color, alpha: u32) {
        for py in y..y + h {
            for px in x..x + w {
                let cov = coverage(rr_sdf(px, py, x, y, w, h, r));
                self.blend(px, py, c, cov * alpha / 256);
            }
        }
    }

    /// Eine Pixelzeile eines geglätteten Kreises (Durchmesser `size`).
    /// Zeilenweise, damit jede Zeile ihre eigene Farbe (Verlauf) haben kann.
    pub fn circle_row(&mut self, x: i32, y: i32, size: i32, row: i32, c: Color) {
        let r = size / 2;
        for px in x..x + size {
            let cov = coverage(rr_sdf(px, y + row, x, y, size, size, r));
            self.blend(px, y + row, c, cov);
        }
    }

    /// Abgerundeter Balken aus farbigen Abschnitten (z. B. Speicheraufteilung).
    /// Sehr kleine Anteile bekommen mindestens 4 px, damit man sie sieht.
    pub fn segmented_bar(&mut self, x: i32, y: i32, w: i32, h: i32, segments: &[(u64, Color)]) {
        let total: u64 = segments.iter().map(|s| s.0).sum();
        if total == 0 {
            return;
        }
        let mut widths = [0i32; 8];
        let n = segments.len().min(8);
        for i in 0..n {
            let v = segments[i].0;
            widths[i] = if v == 0 { 0 } else { ((v as u128 * w as u128 / total as u128) as i32).max(4) };
        }
        // Rundungs-/Mindestbreiten-Differenz dem größten Abschnitt zuschlagen
        let diff = w - widths[..n].iter().sum::<i32>();
        if let Some(big) = (0..n).max_by_key(|&i| widths[i]) {
            widths[big] += diff;
        }
        let mut px = x;
        for i in 0..n {
            for col in px..px + widths[i] {
                for row in y..y + h {
                    let cov = coverage(rr_sdf(col, row, x, y, w, h, h / 2));
                    self.blend(col, row, segments[i].1, cov);
                }
            }
            px += widths[i];
        }
    }

    /// 1 px breiter, geglätteter Rand – sorgt für den „Glas“-Lichtkanten-Effekt.
    pub fn rounded_border(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: Color, alpha: u32) {
        for py in y..y + h {
            for px in x..x + w {
                let outer = coverage(rr_sdf(px, py, x, y, w, h, r));
                let inner = coverage(rr_sdf(px, py, x + 1, y + 1, w - 2, h - 2, r - 1));
                self.blend(px, py, c, outer.saturating_sub(inner) * alpha / 256);
            }
        }
    }

    /// Weicher Schlagschatten unter einem abgerundeten Rechteck (x, y, w, h).
    /// Der Schatten ist um `offset_y` nach unten versetzt und wird nur
    /// außerhalb der Karte gezeichnet – wichtig bei halbtransparentem Glas.
    pub fn drop_shadow(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, blur: i32, offset_y: i32, alpha: u32) {
        let b = blur * 256;
        let sy = y + offset_y;
        for py in sy - blur..sy + h + blur {
            for px in x - blur..x + w + blur {
                let d = rr_sdf(px, py, x, sy, w, h, r);
                // t läuft von 256 (innen) nach 0 (blur Pixel außerhalb)
                let t = ((b - d).clamp(0, 2 * b) as u32 * 128) / b as u32;
                let t = (t * t / 256).min(256);
                let outside_card = 256 - coverage(rr_sdf(px, py, x, y, w, h, r));
                self.blend(px, py, Color::hex(0x000000), t * alpha / 256 * outside_card / 256);
            }
        }
    }

    /// Text mit Kantenglättung; liefert die Breite in Pixeln zurück.
    pub fn text(&mut self, x: i32, y: i32, s: &str, weight: FontWeight, size: RasterHeight, c: Color) -> i32 {
        let mut cx = x;
        for_each_glyph(s, |ch| {
            if let Some(raster) = get_raster(ch, weight, size).or_else(|| get_raster('?', weight, size)) {
                for (row_i, row) in raster.rows().enumerate() {
                    for (col_i, &intensity) in row.iter().enumerate() {
                        self.blend(cx + col_i as i32, y + row_i as i32, c, intensity as u32);
                    }
                }
                cx += raster.width() as i32;
            }
        });
        cx - x
    }

    pub fn text_width(s: &str, weight: FontWeight, size: RasterHeight) -> i32 {
        let mut n = 0;
        for_each_glyph(s, |_| n += 1);
        n * get_raster_width(weight, size) as i32
    }
}

/// Ersatz für Zeichen, die in unserer Schrift fehlen (sie kennt nur Latin-1)
pub fn glyph_fallback(ch: char) -> Option<&'static str> {
    Some(match ch {
        '–' | '—' | '−' => "-",
        '…' => "...",
        '€' => "EUR",
        '„' | '“' | '”' => "\"",
        '‚' | '‘' | '’' => "'",
        '•' => "·",
        _ => return None,
    })
}

/// Ruft `f` für jedes darzustellende Zeichen auf (mit Ersatzzeichen)
fn for_each_glyph(s: &str, mut f: impl FnMut(char)) {
    for ch in s.chars() {
        match glyph_fallback(ch) {
            Some(rep) => rep.chars().for_each(&mut f),
            None => f(ch),
        }
    }
}

/// Signed Distance Function eines abgerundeten Rechtecks.
/// Ergebnis in 1/256 Pixel: < 0 innen, > 0 außen.
fn rr_sdf(px: i32, py: i32, x: i32, y: i32, w: i32, h: i32, r: i32) -> i32 {
    // Pixelmitte und Rechteckmitte in Festkomma (×256)
    let (fx, fy) = (px * 256 + 128, py * 256 + 128);
    let (cx, cy) = (x * 256 + w * 128, y * 256 + h * 128);
    let (hw, hh, r) = (w * 128, h * 128, r * 256);
    let qx = (fx - cx).abs() - (hw - r);
    let qy = (fy - cy).abs() - (hh - r);
    let (ox, oy) = (qx.max(0) as i64, qy.max(0) as i64);
    let outside = isqrt((ox * ox + oy * oy) as u64) as i32;
    let inside = qx.max(qy).min(0);
    outside + inside - r
}

/// Abstand -> Deckkraft (0..=256), halber Pixel Übergang
fn coverage(sdf: i32) -> u32 {
    (128 - sdf).clamp(0, 256) as u32
}

/// Ganzzahlige Quadratwurzel (Newton-Verfahren)
pub fn isqrt(n: u64) -> u64 {
    if n < 2 {
        return n;
    }
    let mut x = n;
    let mut y = (x + 1) / 2;
    while y < x {
        x = y;
        y = (x + n / x) / 2;
    }
    x
}
