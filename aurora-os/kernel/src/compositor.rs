//! Der Compositor setzt das Bild aus Ebenen (Layern) zusammen.
//!
//! Jede Karte, die Menüleiste und der Mauszeiger sind eigene Ebenen mit
//! eigenem Bildinhalt. Pro Bildpunkt wird von unten nach oben gestapelt:
//!
//!   Hintergrund → Schatten → Glas (verschwommener Hintergrund + Tönung)
//!               → Lichtkante → Inhalt der Ebene → nächste Ebene …
//!
//! Neu berechnet werden nur „beschädigte“ Rechtecke (Damage): Wenn sich eine
//! Karte bewegt, die alte und die neue Stelle; wenn sich ihr Inhalt ändert,
//! nur die Karte selbst. Erst das fertige Ergebnis wandert in den Framebuffer.

use alloc::vec;
use alloc::vec::Vec;
use libm::roundf;

use crate::framebuffer;
use crate::gfx::Rect;
use crate::paint::{Image, sdf_rrect};
use crate::theme::Palette;
use crate::wallpaper;

const SHADOW_PAD: i32 = 40;
const SHADOW_OFFSET_Y: i32 = 16;

pub struct Layer {
    pub id: u8,
    pub x: f32,
    pub y: f32,
    pub w: i32,
    pub h: i32,
    pub radius: f32,
    pub opacity: f32,
    pub glass: bool,
    pub shadow: bool,
    pub content: Image,
    mask: Vec<u8>,        // Form der Ebene (Deckung 0..255)
    border: Vec<u8>,      // 1-px-Lichtkante
    shadow_mask: Vec<u8>, // weicher Schatten (größer als die Ebene)
}

impl Layer {
    pub fn new(id: u8, w: i32, h: i32, radius: f32, glass: bool, shadow: bool) -> Self {
        let mut l = Layer {
            id,
            x: 0.0,
            y: 0.0,
            w,
            h,
            radius,
            opacity: 1.0,
            glass,
            shadow,
            content: Image::new(w, h),
            mask: Vec::new(),
            border: Vec::new(),
            shadow_mask: Vec::new(),
        };
        l.build_masks();
        l
    }

    /// Größe ändern (z. B. beim Ziehen am Fensterrand). Der alte Inhalt wird
    /// übernommen, bis die App ein neues Bild in der richtigen Größe liefert.
    pub fn resize(&mut self, w: i32, h: i32) {
        if w == self.w && h == self.h {
            return;
        }
        self.w = w.max(1);
        self.h = h.max(1);
        // alten Inhalt behalten, bis der neue fertig ist (kein Flackern)
        let mut content = Image::new(self.w, self.h);
        content.copy_from(&self.content);
        self.content = content;
        self.build_masks();
    }

    /// Form, Lichtkante und Schatten berechnen – schnell genug, um das bei
    /// jeder Größenänderung (60-mal pro Sekunde) zu tun:
    /// * Form: innen überall voll, nur die vier Ecken brauchen die Distanzfunktion.
    /// * Schatten: ein weichgezeichnetes Rechteck ist (fast) das Produkt zweier
    ///   eindimensionaler Verläufe – für x und für y. Statt w×h Wurzeln also
    ///   nur w+h Werte und eine Multiplikation pro Pixel.
    fn build_masks(&mut self) {
        let (w, h, r) = (self.w, self.h, self.radius);
        let (wf, hf) = (w as f32, h as f32);
        self.mask = vec![255u8; (w * h) as usize];
        self.border = vec![0u8; (w * h) as usize];
        // gerade Kanten: 1 px Lichtkante
        for x in 0..w {
            self.border[x as usize] = 255;
            self.border[((h - 1) * w + x) as usize] = 255;
        }
        for y in 0..h {
            self.border[(y * w) as usize] = 255;
            self.border[(y * w + w - 1) as usize] = 255;
        }
        // Ecken genau rechnen
        let rc = (libm::ceilf(r) as i32 + 1).min(w / 2).min(h / 2);
        for (cx0, cy0) in [(0, 0), (w - rc, 0), (0, h - rc), (w - rc, h - rc)] {
            for y in cy0..cy0 + rc {
                for x in cx0..cx0 + rc {
                    let d = sdf_rrect(x as f32 + 0.5, y as f32 + 0.5, 0.0, 0.0, wf, hf, r);
                    self.mask[(y * w + x) as usize] = ((0.5 - d).clamp(0.0, 1.0) * 255.0) as u8;
                    self.border[(y * w + x) as usize] = ((1.0 - (d + 0.5).abs()).clamp(0.0, 1.0) * 255.0) as u8;
                }
            }
        }
        self.shadow_mask.clear();
        if !self.shadow {
            return;
        }
        let p = SHADOW_PAD;
        let (sw, sh) = (w + 2 * p, h + 2 * p);
        let blur = p as f32;
        let smooth = |t: f32| {
            let t = t.clamp(0.0, 1.0);
            t * t * (3.0 - 2.0 * t)
        };
        // Verlauf eines weichgezeichneten Intervalls [a, b]
        let profile = |n: i32, a: f32, b: f32| -> Vec<f32> {
            (0..n)
                .map(|i| {
                    let c = i as f32 + 0.5;
                    smooth((c - (a - blur)) / (2.0 * blur)) * smooth(((b + blur) - c) / (2.0 * blur))
                })
                .collect()
        };
        let fx = profile(sw, p as f32 + 6.0, (p + w) as f32 - 6.0);
        let fy = profile(sh, (p + SHADOW_OFFSET_Y) as f32 + 6.0, (p + SHADOW_OFFSET_Y + h) as f32 - 6.0);
        self.shadow_mask = vec![0u8; (sw * sh) as usize];
        for y in 0..sh {
            for x in 0..sw {
                let mut v = fx[x as usize] * fy[y as usize];
                // nicht unter der (halbtransparenten) Ebene selbst
                let (lx, ly) = (x - p, y - p);
                if lx >= 0 && ly >= 0 && lx < w && ly < h {
                    v *= 1.0 - self.mask[(ly * w + lx) as usize] as f32 / 255.0;
                }
                self.shadow_mask[(y * sw + x) as usize] = (v * 255.0) as u8;
            }
        }
    }

    pub fn rect(&self) -> Rect {
        Rect::new(roundf(self.x) as i32, roundf(self.y) as i32, self.w, self.h)
    }

    /// Bereich inklusive Schatten
    pub fn bounds(&self) -> Rect {
        let r = self.rect();
        if self.shadow { Rect::new(r.x - SHADOW_PAD, r.y - SHADOW_PAD, r.w + 2 * SHADOW_PAD, r.h + 2 * SHADOW_PAD) } else { r }
    }
}

pub struct Compositor {
    pub w: i32,
    pub h: i32,
    walls: [Vec<u32>; 2],
    blurs: [Vec<u32>; 2],
    back: Vec<u32>,
    /// 0.0 = dunkel … 1.0 = hell (wird beim Umschalten animiert)
    pub light: f32,
    pub palette: Palette,
    pub layers: Vec<Layer>,
    damage: Vec<Rect>,
    pub last_pixels: u64,
}

impl Compositor {
    pub fn new(w: i32, h: i32, palette: Palette) -> Self {
        let dark = wallpaper::render(w, h, false);
        let light = wallpaper::render(w, h, true);
        let blur_dark = wallpaper::blur(&dark, w, h, 18);
        let blur_light = wallpaper::blur(&light, w, h, 18);
        Compositor {
            w,
            h,
            walls: [dark, light],
            blurs: [blur_dark, blur_light],
            back: vec![0; (w * h) as usize],
            light: 0.0,
            palette,
            layers: Vec::new(),
            damage: vec![Rect::new(0, 0, w, h)],
            last_pixels: 0,
        }
    }

    pub fn layer(&mut self, id: u8) -> Option<&mut Layer> {
        self.layers.iter_mut().find(|l| l.id == id)
    }

    pub fn index_of(&self, id: u8) -> Option<usize> {
        self.layers.iter().position(|l| l.id == id)
    }

    /// Bereich als „neu zu zeichnen“ markieren
    pub fn damage(&mut self, r: Rect) {
        let Some(mut r) = clip(r, Rect::new(0, 0, self.w, self.h)) else { return };
        // Überlappende Rechtecke zusammenfassen, damit nichts doppelt gerechnet wird
        let mut i = 0;
        while i < self.damage.len() {
            if self.damage[i].intersects(&r) {
                r = union(r, self.damage.swap_remove(i));
                i = 0;
            } else {
                i += 1;
            }
        }
        self.damage.push(r);
    }

    pub fn damage_all(&mut self) {
        self.damage.clear();
        self.damage.push(Rect::new(0, 0, self.w, self.h));
    }

    /// Inhalt einer Ebene hat sich geändert
    pub fn damage_layer(&mut self, id: u8) {
        if let Some(i) = self.index_of(id) {
            let r = self.layers[i].rect();
            self.damage(r);
        }
    }

    /// Ebene verschieben/einblenden: alte und neue Stelle neu zeichnen
    pub fn set_geometry(&mut self, id: u8, x: f32, y: f32, opacity: f32) {
        let Some(i) = self.index_of(id) else { return };
        let l = &self.layers[i];
        if l.x == x && l.y == y && l.opacity == opacity {
            return;
        }
        let old = l.bounds();
        let l = &mut self.layers[i];
        l.x = x;
        l.y = y;
        l.opacity = opacity;
        let new = l.bounds();
        self.damage(old);
        self.damage(new);
    }

    /// Position, Größe und Deckkraft setzen. Liefert `true`, wenn sich die
    /// Größe geändert hat (dann muss der Inhalt neu gerendert werden).
    pub fn set_rect(&mut self, id: u8, x: f32, y: f32, w: i32, h: i32, opacity: f32) -> bool {
        let Some(i) = self.index_of(id) else { return false };
        let resized = self.layers[i].w != w || self.layers[i].h != h;
        if resized {
            let old = self.layers[i].bounds();
            self.layers[i].resize(w, h);
            self.damage(old);
        }
        self.set_geometry(id, x, y, opacity);
        if resized {
            let b = self.layers[i].bounds();
            self.damage(b);
        }
        resized
    }

    /// Ebene ganz nach oben holen (aber unter `below` lassen, z. B. dem Mauszeiger)
    pub fn raise(&mut self, id: u8, below: &[u8]) {
        let Some(i) = self.index_of(id) else { return };
        let layer = self.layers.remove(i);
        let pos = self.layers.iter().position(|l| below.contains(&l.id)).unwrap_or(self.layers.len());
        let r = layer.bounds();
        self.layers.insert(pos, layer);
        self.damage(r);
    }

    pub fn remove(&mut self, id: u8) {
        if let Some(i) = self.index_of(id) {
            let r = self.layers.remove(i).bounds();
            self.damage(r);
        }
    }

    /// Alle beschädigten Bereiche neu zusammensetzen und anzeigen.
    /// Liefert die Anzahl der berechneten Pixel.
    pub fn compose(&mut self) -> u64 {
        let mut damage = core::mem::take(&mut self.damage);
        // Mehr als die Hälfte beschädigt? Dann einfach alles in einem Rutsch.
        let area: i64 = damage.iter().map(|r| r.w as i64 * r.h as i64).sum();
        if area * 2 > self.w as i64 * self.h as i64 {
            damage = vec![Rect::new(0, 0, self.w, self.h)];
        }
        let mut pixels = 0;
        for r in &damage {
            self.compose_rect(*r);
            self.present(*r);
            pixels += (r.w * r.h) as u64;
        }
        damage.clear();
        self.damage = damage;
        self.last_pixels = pixels;
        pixels
    }

    fn compose_rect(&mut self, r: Rect) {
        let w = self.w;
        let t = (self.light.clamp(0.0, 1.0) * 256.0) as u32;

        // 1) Hintergrund (beim Umschalten zwischen Hell und Dunkel überblendet)
        for y in r.y..r.y + r.h {
            let row = (y * w) as usize;
            for x in r.x..r.x + r.w {
                let i = row + x as usize;
                self.back[i] = mix(self.walls[0][i], self.walls[1][i], t);
            }
        }

        let p = self.palette;
        let tint = p.glass_tint.rgb();
        let tint_a = p.glass_tint.a as u32 + 1;
        let border = p.border.rgb();
        let border_a = p.border.a as u32;

        for l in &self.layers {
            if l.opacity <= 0.0 {
                continue;
            }
            let op = (l.opacity * 256.0) as u32;
            let lr = l.rect();

            // 2) Schatten
            if l.shadow {
                if let Some(s) = clip(r, l.bounds()) {
                    let sw = l.w + 2 * SHADOW_PAD;
                    let k = (p.shadow_alpha * 256.0) as u32 * op / 256;
                    for y in s.y..s.y + s.h {
                        for x in s.x..s.x + s.w {
                            let m = l.shadow_mask[((y - lr.y + SHADOW_PAD) * sw + (x - lr.x + SHADOW_PAD)) as usize] as u32;
                            if m != 0 {
                                let i = (y * w + x) as usize;
                                self.back[i] = mix(self.back[i], 0, m * k / 255);
                            }
                        }
                    }
                }
            }

            // 3) Glas, Lichtkante, Inhalt
            let Some(c) = clip(r, lr) else { continue };
            for y in c.y..c.y + c.h {
                for x in c.x..c.x + c.w {
                    let li = ((y - lr.y) * l.w + (x - lr.x)) as usize;
                    let m = l.mask[li] as u32;
                    if m == 0 {
                        continue;
                    }
                    let i = (y * w + x) as usize;
                    let cov = m * op / 255; // 0..256
                    let mut px = self.back[i];
                    if l.glass {
                        // „Echter“ Blur: an dieser Stelle der vorberechnete
                        // verschwommene Hintergrund, darüber eine Tönung
                        let blurred = mix(self.blurs[0][i], self.blurs[1][i], t);
                        px = mix(px, mix(blurred, tint, tint_a), cov);
                        let b = l.border[li] as u32;
                        if b != 0 {
                            px = mix(px, border, b * border_a / 255 * op / 256);
                        }
                    }
                    // Inhalt: vormultipliziertes ARGB
                    let src = l.content.px[li];
                    let a = src >> 24;
                    if a != 0 {
                        let k = cov; // Deckkraft der Ebene × Form
                        let inv = 256 - a * k / 255;
                        let ch = |s: u32| -> u32 {
                            let d = (px >> s) & 0xFF;
                            let c = (src >> s) & 0xFF;
                            ((d * inv + c * k) >> 8).min(255)
                        };
                        px = ch(16) << 16 | ch(8) << 8 | ch(0);
                    }
                    self.back[i] = px;
                }
            }
        }
    }

    /// Fertiges Rechteck in den Framebuffer kopieren
    fn present(&self, r: Rect) {
        let Some(fb) = framebuffer::info() else { return };
        let same_format = fb.shift == (16, 8, 0);
        for y in r.y..r.y + r.h {
            let src = &self.back[(y * self.w + r.x) as usize..(y * self.w + r.x + r.w) as usize];
            let dst = (fb.addr + y as usize * fb.pitch as usize + r.x as usize * 4) as *mut u32;
            unsafe {
                if same_format {
                    core::ptr::copy_nonoverlapping(src.as_ptr(), dst, r.w as usize);
                } else {
                    for (k, &p) in src.iter().enumerate() {
                        let v = ((p >> 16) & 0xFF) << fb.shift.0 | ((p >> 8) & 0xFF) << fb.shift.1 | (p & 0xFF) << fb.shift.2;
                        dst.add(k).write_volatile(v);
                    }
                }
            }
        }
    }
}

/// Zwei Farben (0x00RRGGBB) mischen, t = 0..256
#[inline]
fn mix(a: u32, b: u32, t: u32) -> u32 {
    if t == 0 {
        return a;
    }
    if t >= 256 {
        return b;
    }
    let rb = ((a & 0xFF00FF) * (256 - t) + (b & 0xFF00FF) * t) >> 8 & 0xFF00FF;
    let g = ((a & 0x00FF00) * (256 - t) + (b & 0x00FF00) * t) >> 8 & 0x00FF00;
    rb | g
}

fn clip(a: Rect, b: Rect) -> Option<Rect> {
    let x0 = a.x.max(b.x);
    let y0 = a.y.max(b.y);
    let x1 = (a.x + a.w).min(b.x + b.w);
    let y1 = (a.y + a.h).min(b.y + b.h);
    (x1 > x0 && y1 > y0).then(|| Rect::new(x0, y0, x1 - x0, y1 - y0))
}

fn union(a: Rect, b: Rect) -> Rect {
    let x0 = a.x.min(b.x);
    let y0 = a.y.min(b.y);
    let x1 = (a.x + a.w).max(b.x + b.w);
    let y1 = (a.y + a.h).max(b.y + b.h);
    Rect::new(x0, y0, x1 - x0, y1 - y0)
}
