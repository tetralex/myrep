//! Die ersten Apps: Uhr, Notizen, Einstellungen, Leistung.
//! Jede App zeichnet nur ihren Inhaltsbereich (unterhalb der Titelleiste);
//! Titelleiste, Rahmen und Schatten kommen vom Fenstermanager.

use alloc::collections::VecDeque;
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use libm::{cosf, sinf};

use crate::font::{self, Weight};
use crate::paint::{Image, Rgba};
use crate::theme::{ACCENTS, Palette};
use crate::time;

pub const TITLE_H: f32 = 40.0;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AppKind {
    Clock,
    Notes,
    Settings,
    Monitor,
}

impl AppKind {
    pub const ALL: [AppKind; 4] = [AppKind::Clock, AppKind::Notes, AppKind::Settings, AppKind::Monitor];

    pub fn title(self) -> &'static str {
        match self {
            AppKind::Clock => "Uhr",
            AppKind::Notes => "Notizen",
            AppKind::Settings => "Einstellungen",
            AppKind::Monitor => "Leistung",
        }
    }

    pub fn default_size(self) -> (i32, i32) {
        match self {
            AppKind::Clock => (420, 230),
            AppKind::Notes => (560, 380),
            AppKind::Settings => (420, 320),
            AppKind::Monitor => (440, 320),
        }
    }

    pub fn min_size(self) -> (i32, i32) {
        match self {
            AppKind::Notes => (300, 180),
            _ => (320, 200),
        }
    }

    /// Ebenen-ID des Fensters im Compositor
    pub fn layer_id(self) -> u8 {
        10 + self as u8
    }
}

/// Alles, was die Apps zum Zeichnen brauchen
pub struct Ctx<'a> {
    pub p: &'a Palette,
    pub dark_knob: f32, // 1 = dunkel (Schalterstellung, animiert)
    pub accent_idx: usize,
    pub fps: u32,
    pub frame_times: &'a VecDeque<f32>,
    pub caret_on: bool,
    pub focused: bool,
    pub notes: &'a Notes,
    pub heap: (usize, usize),
}

pub fn draw(app: AppKind, img: &mut Image, c: &Ctx) {
    match app {
        AppKind::Clock => draw_clock(img, c),
        AppKind::Notes => draw_notes(img, c),
        AppKind::Settings => draw_settings(img, c),
        AppKind::Monitor => draw_monitor(img, c),
    }
}

// ---------------------------------------------------------------------------
// Uhr – passt die Schriftgröße der Fenstergröße an
// ---------------------------------------------------------------------------

fn draw_clock(img: &mut Image, c: &Ctx) {
    let (w, h) = (img.w as f32, img.h as f32);
    let t = time::now();
    let clock = format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second);
    // Breite pro Pixel Schriftgröße messen, dann so groß wie möglich
    let cell100 = font::measure("0", 100.0, Weight::Regular) / 100.0;
    let colon100 = font::measure(":", 100.0, Weight::Regular) / 100.0;
    let per_px = 6.0 * cell100 + 2.0 * colon100 + 0.08;
    let size = ((w - 56.0) / per_px).min((h - TITLE_H - 70.0) * 1.1).clamp(20.0, 150.0);
    // in 4-px-Stufen: sonst würde jede Zwischengröße einer Animation neu gerastert
    let size = libm::floorf(size / 4.0) * 4.0;
    let (cell, colon) = (cell100 * size, colon100 * size + size * 0.04);
    let total = 6.0 * cell + 2.0 * colon;
    let mut x = (w - total) / 2.0;
    let baseline = TITLE_H + (h - TITLE_H - 40.0) / 2.0 + size * 0.36;
    for ch in clock.chars() {
        let cw = if ch == ':' { colon } else { cell };
        let mut buf = [0u8; 4];
        let txt: &str = ch.encode_utf8(&mut buf);
        let gw = font::measure(txt, size, Weight::Regular);
        let color = if ch == ':' { c.p.accent } else { c.p.text };
        img.text(x + (cw - gw) / 2.0, baseline, txt, size, Weight::Regular, color);
        x += cw;
    }
    let date = format!("{}, {}. {} {}", time::WEEKDAYS[t.weekday as usize], t.day, time::MONTHS[t.month as usize - 1], t.year);
    img.text_centered(w / 2.0, baseline + 34.0, &date, 15.0, Weight::Regular, c.p.text_muted);
}

// ---------------------------------------------------------------------------
// Notizen – kleiner Texteditor mit beweglichem Cursor
// ---------------------------------------------------------------------------

pub struct Notes {
    pub text: String,
    pub caret: usize, // Byte-Position im Text
}

impl Notes {
    pub fn new() -> Self {
        let text = String::from("Willkommen bei AuroraOS!\n\nDas ist die Notizen-App. Tippe einfach los – Umlaute, € und @ funktionieren. Pfeiltasten, Pos1 und Ende bewegen den Cursor.");
        Notes { caret: text.len(), text }
    }

    pub fn insert(&mut self, ch: char) {
        self.text.insert(self.caret, ch);
        self.caret += ch.len_utf8();
    }

    pub fn backspace(&mut self) {
        if let Some((i, _)) = self.text[..self.caret].char_indices().next_back() {
            self.text.remove(i);
            self.caret = i;
        }
    }

    pub fn delete(&mut self) {
        if self.caret < self.text.len() {
            self.text.remove(self.caret);
        }
    }

    pub fn left(&mut self) {
        if let Some((i, _)) = self.text[..self.caret].char_indices().next_back() {
            self.caret = i;
        }
    }

    pub fn right(&mut self) {
        if let Some(ch) = self.text[self.caret..].chars().next() {
            self.caret += ch.len_utf8();
        }
    }

    pub fn home(&mut self) {
        self.caret = self.text[..self.caret].rfind('\n').map(|i| i + 1).unwrap_or(0);
    }

    pub fn end(&mut self) {
        self.caret += self.text[self.caret..].find('\n').unwrap_or(self.text.len() - self.caret);
    }
}

fn draw_notes(img: &mut Image, c: &Ctx) {
    let (w, h) = (img.w as f32, img.h as f32);
    let size = 15.0;
    let line_h = 22.0;
    let (pad, top) = (20.0, TITLE_H + 14.0);
    let max_w = w - 2.0 * pad;

    // Zeilen umbrechen; für jede Zeile merken: (Startbyte, Endbyte)
    let text = &c.notes.text;
    let mut lines: Vec<(usize, usize)> = Vec::new();
    let mut start = 0;
    let mut width = 0.0;
    for (i, ch) in text.char_indices() {
        if ch == '\n' {
            lines.push((start, i));
            start = i + 1;
            width = 0.0;
            continue;
        }
        let cw = font::measure(&text[i..i + ch.len_utf8()], size, Weight::Regular);
        if width + cw > max_w && i > start {
            // am letzten Leerzeichen umbrechen, sonst mitten im Wort
            let brk = text[start..i].rfind(' ').map(|k| start + k + 1).filter(|&k| k > start).unwrap_or(i);
            lines.push((start, brk));
            start = brk;
            width = font::measure(&text[start..i], size, Weight::Regular);
        }
        width += cw;
    }
    lines.push((start, text.len()));

    // Zeile mit dem Cursor finden und so scrollen, dass sie sichtbar ist
    let caret = c.notes.caret;
    let caret_line = lines.iter().rposition(|&(s, _)| s <= caret).unwrap_or(0);
    let visible = (((h - top - 34.0) / line_h) as usize).max(1);
    let first = (caret_line + 1).saturating_sub(visible);

    let mut y = top + 16.0;
    for (li, &(s, e)) in lines.iter().enumerate().skip(first).take(visible) {
        img.text(pad, y, &text[s..e], size, Weight::Regular, c.p.text);
        if li == caret_line && c.caret_on && c.focused {
            let cx = pad + font::measure(&text[s..caret.min(e).max(s)], size, Weight::Regular);
            img.fill_rounded(cx, y - 15.0, 2.0, 19.0, 1.0, c.p.accent);
        }
        y += line_h;
    }
    let status = format!("{} Zeichen · {} Zeilen", text.chars().count(), lines.len());
    img.text(pad, h - 14.0, &status, 12.0, Weight::Regular, c.p.text_faint);
    let hint = "Strg+W schließt · Strg+M minimiert";
    let hw = font::measure(hint, 12.0, Weight::Regular);
    img.text(w - pad - hw, h - 14.0, hint, 12.0, Weight::Regular, c.p.text_faint);
}

// ---------------------------------------------------------------------------
// Einstellungen
// ---------------------------------------------------------------------------

/// Bedienelemente der Einstellungen (Position im Fenster)
pub fn settings_toggle_rect(w: f32) -> (f32, f32, f32, f32) {
    (w - 24.0 - 52.0, TITLE_H + 22.0, 52.0, 30.0)
}

pub fn settings_swatch_center(i: usize) -> (f32, f32) {
    (24.0 + 14.0 + i as f32 * 44.0, TITLE_H + 112.0)
}

fn draw_settings(img: &mut Image, c: &Ctx) {
    let w = img.w as f32;
    let p = c.p;
    img.text(24.0, TITLE_H + 43.0, "Dunkler Modus", 15.0, Weight::Regular, p.text);
    let (sx, sy, sw, sh) = settings_toggle_rect(w);
    let on = c.dark_knob;
    img.fill_rounded(sx, sy, sw, sh, 15.0, p.control.lerp(p.accent, on));
    img.circle(sx + 15.0 + on * (sw - 30.0), sy + 15.0, 11.0, Rgba::hex(0xFFFFFF));

    img.text(24.0, TITLE_H + 84.0, "Akzentfarbe", 15.0, Weight::Regular, p.text);
    let name = ACCENTS[c.accent_idx].0;
    let nw = font::measure(name, 13.0, Weight::Regular);
    img.text(w - 24.0 - nw, TITLE_H + 84.0, name, 13.0, Weight::Regular, p.text_muted);
    for (i, (_, rgb)) in ACCENTS.iter().enumerate() {
        let (cx, cy) = settings_swatch_center(i);
        img.circle(cx, cy, 12.0, Rgba::hex(*rgb));
        if i == c.accent_idx {
            img.ring(cx, cy, 17.0, 2.0, p.text);
        }
    }

    img.line(24.0, TITLE_H + 146.0, w - 24.0, TITLE_H + 146.0, 1.0, p.well_border);
    img.text(24.0, TITLE_H + 174.0, "Über dieses System", 13.0, Weight::SemiBold, p.text_muted);
    let up = time::ticks() / time::HZ;
    let rows = [
        ("System", String::from("AuroraOS 0.6 · x86_64 · Rust")),
        ("Kernel-Heap", format!("{} von {} MiB belegt", c.heap.0 / (1024 * 1024), c.heap.1 / (1024 * 1024))),
        ("Laufzeit", format!("{:02}:{:02}:{:02}", up / 3600, up / 60 % 60, up % 60)),
    ];
    for (k, (label, value)) in rows.iter().enumerate() {
        let y = TITLE_H + 200.0 + k as f32 * 22.0;
        img.text(24.0, y, label, 13.0, Weight::Regular, p.text_muted);
        img.text(140.0, y, value, 13.0, Weight::Regular, p.text);
    }
}

// ---------------------------------------------------------------------------
// Leistung
// ---------------------------------------------------------------------------

fn draw_monitor(img: &mut Image, c: &Ctx) {
    let (w, h) = (img.w as f32, img.h as f32);
    let p = c.p;
    let fps = format!("{}", c.fps);
    let fw = img.text(24.0, TITLE_H + 50.0, &fps, 40.0, Weight::SemiBold, p.text);
    img.text(24.0 + fw + 6.0, TITLE_H + 50.0, "FPS", 15.0, Weight::Regular, p.text_muted);
    let last = c.frame_times.back().copied().unwrap_or(0.0);
    let avg = if c.frame_times.is_empty() { 0.0 } else { c.frame_times.iter().sum::<f32>() / c.frame_times.len() as f32 };
    let info = format!("Bildzeit {:.1} ms (Ø {:.1})", last, avg).replace('.', ",");
    let iw = font::measure(&info, 13.0, Weight::Regular);
    img.text(w - 24.0 - iw, TITLE_H + 48.0, &info, 13.0, Weight::Regular, p.text_muted);

    // Bildzeit-Diagramm, Linie bei 16,7 ms (60 FPS)
    let (gx, gy, gw, gh) = (24.0, TITLE_H + 66.0, w - 48.0, (h - TITLE_H - 150.0).max(40.0));
    let max_ms = 25.0;
    let budget_y = gy + gh - gh * (16.7 / max_ms);
    img.line(gx, budget_y, gx + gw, budget_y, 1.0, p.text_faint.with_alpha(120));
    let n = c.frame_times.len();
    if n >= 2 {
        let step = gw / 99.0;
        let pt = |i: usize, v: f32| (gx + gw - (n - 1 - i) as f32 * step, gy + gh - gh * (v.min(max_ms) / max_ms));
        // Fläche unter der Kurve: einfache Rechtecke statt geglätteter Linien
        for (i, v) in c.frame_times.iter().enumerate() {
            let (x, y) = pt(i, *v);
            img.fill_rect(x as i32, y as i32, libm::ceilf(step) as i32, (gy + gh - y) as i32, p.accent.with_alpha(40));
        }
        for i in 1..n {
            let (ax, ay) = pt(i - 1, c.frame_times[i - 1]);
            let (bx, by) = pt(i, c.frame_times[i]);
            img.line(ax, ay, bx, by, 1.8, p.accent);
        }
    }

    // Heap-Auslastung
    let y = gy + gh + 32.0;
    img.text(24.0, y, "Kernel-Heap", 13.0, Weight::Regular, p.text_muted);
    let pct = c.heap.0 as f32 / c.heap.1.max(1) as f32;
    let label = format!("{:.1} %", pct * 100.0).replace('.', ",");
    let lw = font::measure(&label, 13.0, Weight::Regular);
    img.text(w - 24.0 - lw, y, &label, 13.0, Weight::Regular, p.text);
    img.fill_rounded(24.0, y + 10.0, w - 48.0, 8.0, 4.0, p.control);
    img.fill_rounded(24.0, y + 10.0, ((w - 48.0) * pct).max(8.0), 8.0, 4.0, p.accent);
    img.text(24.0, h - 14.0, "Bildzeit nur von Bildern mit Änderungen · Linie: 16,7 ms", 12.0, Weight::Regular, p.text_faint);
}

// ---------------------------------------------------------------------------
// App-Symbole fürs Dock (Vektorgrafik, beliebige Größe)
// ---------------------------------------------------------------------------

pub fn draw_icon(app: AppKind, img: &mut Image, x: f32, y: f32, s: f32) {
    let (top, bottom) = match app {
        AppKind::Clock => (0x334155, 0x0F172A),
        AppKind::Notes => (0xFDE68A, 0xF59E0B),
        AppKind::Settings => (0x94A3B8, 0x475569),
        AppKind::Monitor => (0x34D399, 0x059669),
    };
    img.fill_rounded_gradient(x, y, s, s, s * 0.24, Rgba::hex(top), Rgba::hex(bottom));
    img.stroke_rounded(x, y, s, s, s * 0.24, 1.0, Rgba::hex(0xFFFFFF).with_alpha(60));
    let (cx, cy) = (x + s / 2.0, y + s / 2.0);
    let white = Rgba::hex(0xFFFFFF);
    match app {
        AppKind::Clock => {
            img.circle(cx, cy, s * 0.32, white);
            let dark = Rgba::hex(0x0F172A);
            for i in 0..12 {
                let a = i as f32 * core::f32::consts::PI / 6.0;
                let (dx, dy) = (sinf(a), -cosf(a));
                img.line(cx + dx * s * 0.25, cy + dy * s * 0.25, cx + dx * s * 0.28, cy + dy * s * 0.28, 1.2, dark.with_alpha(160));
            }
            img.line(cx, cy, cx + s * 0.13, cy - s * 0.08, s * 0.05, dark);
            img.line(cx, cy, cx - s * 0.04, cy - s * 0.22, s * 0.035, dark);
            img.circle(cx, cy, s * 0.04, Rgba::hex(0xF97316));
        }
        AppKind::Notes => {
            img.fill_rounded(x + s * 0.2, y + s * 0.16, s * 0.6, s * 0.68, s * 0.07, white);
            img.fill_rounded(x + s * 0.2, y + s * 0.16, s * 0.6, s * 0.14, s * 0.07, Rgba::hex(0xFBBF24));
            for k in 0..3 {
                let ly = y + s * (0.44 + k as f32 * 0.12);
                img.line(x + s * 0.3, ly, x + s * (if k == 2 { 0.55 } else { 0.7 }), ly, s * 0.035, Rgba::hex(0x94A3B8));
            }
        }
        AppKind::Settings => {
            for i in 0..8 {
                let a = i as f32 * core::f32::consts::PI / 4.0;
                img.circle(cx + sinf(a) * s * 0.25, cy + cosf(a) * s * 0.25, s * 0.08, white);
            }
            img.circle(cx, cy, s * 0.25, white);
            img.circle(cx, cy, s * 0.1, Rgba::hex(0x64748B));
        }
        AppKind::Monitor => {
            let pts = [(0.2, 0.62), (0.36, 0.48), (0.5, 0.56), (0.64, 0.32), (0.8, 0.4)];
            for k in 1..pts.len() {
                let (a, b) = (pts[k - 1], pts[k]);
                img.line(x + s * a.0, y + s * a.1, x + s * b.0, y + s * b.1, s * 0.06, white);
            }
            img.line(x + s * 0.2, y + s * 0.76, x + s * 0.8, y + s * 0.76, s * 0.04, white.with_alpha(160));
        }
    }
}
