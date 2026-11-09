//! Hintergrundbild, zur Laufzeit berechnet: Farbverlauf, „Polarlicht“-Bänder
//! und (im dunklen Modus) Sterne. Dazu eine stark verschwommene Kopie für
//! den Glas-Effekt der Karten.
//!
//! Pixelformat überall im Compositor: 0x00RRGGBB

use alloc::vec;
use alloc::vec::Vec;
use libm::sinf;

use crate::paint::Rgba;

pub fn render(w: i32, h: i32, light: bool) -> Vec<u32> {
    let (top, bottom, bands): (Rgba, Rgba, [(Rgba, f32, f32, f32, f32); 3]) = if light {
        (
            Rgba::hex(0xE0F2FE),
            Rgba::hex(0xF5E8FF),
            [
                // (Farbe, Höhe 0..1, Breite, Frequenz, Phase)
                (Rgba::hex(0x5EEAD4), 0.30, 0.10, 3.1, 0.0),
                (Rgba::hex(0xC4B5FD), 0.55, 0.12, 2.3, 1.7),
                (Rgba::hex(0xFDA4AF), 0.78, 0.09, 3.7, 4.1),
            ],
        )
    } else {
        (
            Rgba::hex(0x070B1A),
            Rgba::hex(0x1A0F35),
            [
                (Rgba::hex(0x14B8A6), 0.32, 0.10, 3.1, 0.0),
                (Rgba::hex(0x8B5CF6), 0.56, 0.13, 2.3, 1.7),
                (Rgba::hex(0xDB2777), 0.80, 0.08, 3.7, 4.1),
            ],
        )
    };
    let mut px = vec![0u32; (w * h) as usize];

    // Bandmitte pro Spalte vorberechnen (Sinus ist teuer)
    let mut centers = vec![[0f32; 3]; w as usize];
    for x in 0..w {
        let fx = x as f32 / w as f32;
        for (i, b) in bands.iter().enumerate() {
            centers[x as usize][i] = (b.1 + 0.07 * sinf(fx * b.3 + b.4) + 0.03 * sinf(fx * b.3 * 2.7 + b.4 * 1.3)) * h as f32;
        }
    }

    for y in 0..h {
        let base = top.lerp(bottom, y as f32 / h as f32);
        for x in 0..w {
            let (mut r, mut g, mut b) = (base.r as f32, base.g as f32, base.b as f32);
            for (i, band) in bands.iter().enumerate() {
                let d = (y as f32 - centers[x as usize][i]) / (band.2 * h as f32);
                let v = (1.0 - d * d).max(0.0);
                let v = v * v * if light { 0.55 } else { 0.42 };
                r += (band.0.r as f32 - r) * v;
                g += (band.0.g as f32 - g) * v;
                b += (band.0.b as f32 - b) * v;
            }
            px[(y * w + x) as usize] = (r as u32) << 16 | (g as u32) << 8 | b as u32;
        }
    }

    if !light {
        // Sterne: Pseudozufall (Xorshift) – jedes Mal gleich, deshalb reproduzierbar
        let mut seed: u32 = 0x1234_5678;
        let mut rnd = || {
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            seed
        };
        for _ in 0..(w * h / 2500) {
            let (x, y) = ((rnd() % w as u32) as i32, (rnd() % (h as u32 * 3 / 4)) as i32);
            let bright = 90 + rnd() % 165;
            let big = rnd() % 7 == 0;
            for (dx, dy, f) in [(0, 0, 1.0f32), (1, 0, 0.35), (-1, 0, 0.35), (0, 1, 0.35), (0, -1, 0.35)] {
                if !big && (dx != 0 || dy != 0) {
                    continue;
                }
                let (sx, sy) = (x + dx, y + dy);
                if sx < 0 || sy < 0 || sx >= w || sy >= h {
                    continue;
                }
                let i = (sy * w + sx) as usize;
                let add = (bright as f32 * f) as u32;
                let p = px[i];
                let ch = |s: u32| (((p >> s) & 0xFF) + add).min(255) << s;
                px[i] = ch(16) | ch(8) | ch(0);
            }
        }
    }
    px
}

/// Weichzeichnen: dreimal Box-Blur (Mittelwert über ein Fenster) waagrecht
/// und senkrecht ergibt fast einen Gauß-Blur – aber in O(1) pro Pixel,
/// egal wie groß der Radius ist (gleitende Summe).
pub fn blur(src: &[u32], w: i32, h: i32, radius: i32) -> Vec<u32> {
    let mut a = src.to_vec();
    let mut b = vec![0u32; src.len()];
    for _ in 0..3 {
        box_pass(&a, &mut b, w, h, radius, true);
        box_pass(&b, &mut a, w, h, radius, false);
    }
    a
}

fn box_pass(src: &[u32], dst: &mut [u32], w: i32, h: i32, r: i32, horizontal: bool) {
    let (outer, inner) = if horizontal { (h, w) } else { (w, h) };
    let idx = |o: i32, i: i32| if horizontal { (o * w + i) as usize } else { (i * w + o) as usize };
    let n = (2 * r + 1) as u32;
    for o in 0..outer {
        let mut sum = [0u32; 3];
        let get = |i: i32| src[idx(o, i.clamp(0, inner - 1))];
        for i in -r..=r {
            let p = get(i);
            sum[0] += (p >> 16) & 0xFF;
            sum[1] += (p >> 8) & 0xFF;
            sum[2] += p & 0xFF;
        }
        for i in 0..inner {
            dst[idx(o, i)] = (sum[0] / n) << 16 | (sum[1] / n) << 8 | sum[2] / n;
            let (add, sub) = (get(i + r + 1), get(i - r));
            sum[0] = sum[0] + ((add >> 16) & 0xFF) - ((sub >> 16) & 0xFF);
            sum[1] = sum[1] + ((add >> 8) & 0xFF) - ((sub >> 8) & 0xFF);
            sum[2] = sum[2] + (add & 0xFF) - (sub & 0xFF);
        }
    }
}
