//! Desktop für Meilenstein 5: Glaskarten als Compositor-Ebenen, Vektorschrift,
//! Animationen, Hell/Dunkel-Modus, Akzentfarben und verschiebbare Karten.
//!
//! Aufteilung:
//! * **Zustand** (Text, Maus, Theme …) liegt in `Desktop`.
//! * **Inhalt** jeder Ebene wird nur neu gerendert, wenn sich ihr Zustand ändert
//!   (`dirty`-Bits), und zwar in ihr eigenes `Image`.
//! * Der **Compositor** setzt daraus pro Bild nur die beschädigten Bereiche zusammen.

use alloc::collections::VecDeque;
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

use pc_keyboard::{DecodedKey, HandleControl, KeyCode, PS2Keyboard, ScancodeSet1, layouts::De105Key};

use crate::anim::{Tween, ease_in_out_cubic, ease_out_cubic};
use crate::compositor::{Compositor, Layer};
use crate::font::{self, Weight};
use crate::interrupts::{KEYBOARD_BYTES, KEYBOARD_IRQS, MOUSE_BYTES, MOUSE_IRQS};
use crate::paint::{Image, Rgba};
use crate::ps2::{MouseParser, Ps2Info};
use crate::theme::{self, ACCENTS, Palette};
use crate::{framebuffer, time};

// Ebenen-IDs
const TOPBAR: u8 = 0;
const CLOCK: u8 = 1;
const KEYS: u8 = 2;
const LOOK: u8 = 3;
const PERF: u8 = 4;
const CURSOR: u8 = 200;
const RIPPLE_BASE: u8 = 100;
const CARDS: [u8; 4] = [CLOCK, KEYS, LOOK, PERF];
/// Ebenen, die immer ganz oben bleiben
const OVERLAYS: [u8; 1] = [CURSOR];

const RIPPLE_SIZE: i32 = 80;
const RIPPLE_MS: u64 = 500;
const THEME_MS: u64 = 450;
const TITLE_ZONE: i32 = 70; // Karten lassen sich am oberen Bereich greifen

/// Klassischer Pfeil: X = Rand, . = Füllung
const CURSOR_SHAPE: [&str; 19] = [
    "X", "XX", "X.X", "X..X", "X...X", "X....X", "X.....X", "X......X", "X.......X", "X........X", "X.........X",
    "X..........X", "X......XXXXX", "X...X..X", "X..XX..X", "X.X  X..X", "XX   X..X", "X     X..X", "      XXX",
];

struct Ripple {
    id: u8,
    start: u64,
}

pub struct Desktop {
    comp: Compositor,
    w: i32,
    h: i32,
    keyboard: PS2Keyboard<De105Key, ScancodeSet1>,
    mouse: MouseParser,

    // Eingabe-Zustand
    text: String,
    last_key: String,
    mx: i32,
    my: i32,
    buttons: u8,
    drag: Option<(u8, f32, f32)>,
    ripples: Vec<Ripple>,
    next_ripple: u8,

    // Darstellung
    light: Tween,
    accent_idx: usize,
    accent_from: Rgba,
    accent_t: Tween,
    intro: Vec<(u8, f32, f32, Tween)>, // (Ebene, Ziel-x, Ziel-y, Fortschritt)

    // Leistung
    frame_times: VecDeque<f32>,
    fps: u32,
    frames_in_second: u32,
    second_start: u64,

    // was zuletzt angezeigt wurde
    shown_second: u32,
    shown_caret: bool,
    shown_fps: u32,
    dirty: u32, // Bit pro Ebene: Inhalt neu rendern
}

fn bit(id: u8) -> u32 {
    1 << (id as u32 % 32)
}

impl Desktop {
    pub fn new(ps2: &Ps2Info) -> Self {
        let fb = framebuffer::info().expect("kein Framebuffer");
        let (w, h) = (fb.width as i32, fb.height as i32);
        let accent = Rgba::hex(ACCENTS[0].1);
        let mut comp = Compositor::new(w, h, theme::palette(0.0, accent));

        // --- Ebenen anlegen ---
        let (lw, rw, gap) = (460, 380, 24);
        let (ch, kh, lh, ph) = (200, 240, 200, 240);
        let lx = (w - (lw + gap + rw)) / 2;
        let rx = lx + lw + gap;
        let top = ((h - (ch + gap + kh)) / 2 + 24).max(76);

        let mut add = |layer: Layer, x: i32, y: i32| {
            let mut l = layer;
            l.x = x as f32;
            l.y = y as f32;
            l.opacity = 0.0; // werden eingeblendet
            comp.layers.push(l);
        };
        add(Layer::new(TOPBAR, w - 32, 44, 22.0, true, true), 16, 12);
        add(Layer::new(CLOCK, lw, ch, 24.0, true, true), lx, top);
        add(Layer::new(KEYS, lw, kh, 24.0, true, true), lx, top + ch + gap);
        add(Layer::new(LOOK, rw, lh, 24.0, true, true), rx, top);
        add(Layer::new(PERF, rw, ph, 24.0, true, true), rx, top + lh + gap);
        let mut cursor = Layer::new(CURSOR, 16, 24, 0.0, false, false);
        draw_cursor(&mut cursor.content);
        cursor.x = (w / 2) as f32;
        cursor.y = (h / 2) as f32;
        comp.layers.push(cursor);

        // Einflug-Animation: nacheinander, von unten, mit Einblenden
        let now = time::ticks();
        let mut intro = Vec::new();
        for (k, id) in [TOPBAR, CLOCK, LOOK, KEYS, PERF].iter().enumerate() {
            let l = comp.layers.iter().find(|l| l.id == *id).unwrap();
            intro.push((*id, l.x, l.y, Tween::new(0.0, 1.0, now + 150 + k as u64 * 90, 700, ease_out_cubic)));
        }

        Desktop {
            comp,
            w,
            h,
            keyboard: PS2Keyboard::new(ScancodeSet1::new(), De105Key, HandleControl::Ignore),
            mouse: MouseParser::new(ps2.wheel),
            text: String::new(),
            last_key: String::from("–"),
            mx: w / 2,
            my: h / 2,
            buttons: 0,
            drag: None,
            ripples: Vec::new(),
            next_ripple: 0,
            light: Tween::fixed(0.0),
            accent_idx: 0,
            accent_from: accent,
            accent_t: Tween::fixed(1.0),
            intro,
            frame_times: VecDeque::new(),
            fps: 0,
            frames_in_second: 0,
            second_start: now,
            shown_second: 99,
            shown_caret: false,
            shown_fps: 0,
            dirty: u32::MAX,
        }
    }

    fn accent(&self, now: u64) -> Rgba {
        self.accent_from.lerp(Rgba::hex(ACCENTS[self.accent_idx].1), self.accent_t.value(now))
    }

    // -----------------------------------------------------------------------
    // Eingaben
    // -----------------------------------------------------------------------

    fn handle_input(&mut self, now: u64) {
        while let Some(byte) = KEYBOARD_BYTES.pop() {
            if let Ok(Some(ev)) = self.keyboard.add_byte(byte) {
                if let Some(key) = self.keyboard.process_keyevent(ev) {
                    self.on_key(key, now);
                }
            }
        }
        while let Some(byte) = MOUSE_BYTES.pop() {
            if let Some(p) = self.mouse.feed(byte) {
                self.mx = (self.mx + p.dx).clamp(0, self.w - 1);
                self.my = (self.my + p.dy).clamp(0, self.h - 1);
                let pressed = p.buttons & !self.buttons;
                let released = self.buttons & !p.buttons;
                self.buttons = p.buttons;
                if pressed & 1 != 0 {
                    self.on_press(now);
                }
                if released & 1 != 0 {
                    self.drag = None;
                }
                // Scrollrad über „Darstellung“: Akzentfarbe durchschalten
                if p.wheel != 0 && self.comp.layers.iter().rev().find(|l| CARDS.contains(&l.id) && l.contains(self.mx, self.my)).map(|l| l.id) == Some(LOOK) {
                    let n = ACCENTS.len() as i32;
                    let i = (self.accent_idx as i32 + p.wheel.signum()).rem_euclid(n) as usize;
                    self.set_accent(i, now);
                }
                if let Some((id, ox, oy)) = self.drag {
                    let (x, y) = (self.mx as f32 - ox, self.my as f32 - oy);
                    self.comp.set_geometry(id, x, y, 1.0);
                }
            }
        }
    }

    fn on_press(&mut self, now: u64) {
        // Klick-Welle
        let id = RIPPLE_BASE + self.next_ripple % 50;
        self.next_ripple = self.next_ripple.wrapping_add(1);
        self.comp.remove(id);
        let mut l = Layer::new(id, RIPPLE_SIZE, RIPPLE_SIZE, 0.0, false, false);
        l.x = (self.mx - RIPPLE_SIZE / 2) as f32;
        l.y = (self.my - RIPPLE_SIZE / 2) as f32;
        let pos = self.comp.index_of(CURSOR).unwrap_or(self.comp.layers.len());
        self.comp.layers.insert(pos, l);
        self.ripples.push(Ripple { id, start: now });

        // Welche Karte liegt oben unter dem Mauszeiger?
        let hit = self.comp.layers.iter().rev().find(|l| CARDS.contains(&l.id) && l.contains(self.mx, self.my));
        let Some(l) = hit else { return };
        let (id, lr) = (l.id, l.rect());
        let (lx, ly) = (self.mx - lr.x, self.my - lr.y);
        self.comp.raise(id, &OVERLAYS);

        if id == LOOK && self.click_look(lx, ly, now) {
            return; // Klick auf ein Bedienelement, kein Verschieben
        }
        if ly < TITLE_ZONE {
            self.drag = Some((id, (self.mx - lr.x) as f32, (self.my - lr.y) as f32));
        }
    }

    /// Klick in der Karte „Darstellung“. `true` = ein Bedienelement getroffen
    fn click_look(&mut self, x: i32, y: i32, now: u64) -> bool {
        let w = self.comp.layer(LOOK).map(|l| l.w).unwrap_or(0);
        // Schalter Hell/Dunkel
        if x >= w - 24 - 56 && x <= w - 24 && (78..=114).contains(&y) {
            self.toggle_theme(now);
            return true;
        }
        // Farbtupfer
        if (150..=194).contains(&y) {
            for i in 0..ACCENTS.len() {
                let cx = 24 + 14 + i as i32 * 44;
                if (x - cx).abs() <= 18 {
                    self.set_accent(i, now);
                    return true;
                }
            }
        }
        false
    }

    fn toggle_theme(&mut self, now: u64) {
        let target = if self.light.to > 0.5 { 0.0 } else { 1.0 };
        self.light.retarget(target, now, THEME_MS, ease_in_out_cubic);
    }

    fn set_accent(&mut self, i: usize, now: u64) {
        if i != self.accent_idx {
            self.accent_from = self.accent(now);
            self.accent_idx = i;
            self.accent_t = Tween::new(0.0, 1.0, now, 300, ease_out_cubic);
        }
    }

    fn on_key(&mut self, key: DecodedKey, now: u64) {
        self.last_key = match key {
            DecodedKey::Unicode('\u{8}') => {
                self.text.pop();
                "Rücktaste".into()
            }
            DecodedKey::Unicode('\n') => {
                self.text.push('\n');
                "Eingabe".into()
            }
            DecodedKey::Unicode('\t') => {
                self.text.push_str("    ");
                "Tab".into()
            }
            DecodedKey::Unicode('\u{1b}') => {
                self.text.clear();
                "Esc – Text gelöscht".into()
            }
            DecodedKey::Unicode('\u{7f}') => "Entf".into(),
            DecodedKey::Unicode(' ') => {
                self.text.push(' ');
                "Leertaste".into()
            }
            DecodedKey::Unicode(ch) => {
                self.text.push(ch);
                format!("„{}“  (U+{:04X})", ch, ch as u32)
            }
            DecodedKey::RawKey(KeyCode::F2) => {
                self.toggle_theme(now);
                "F2 – Hell/Dunkel".into()
            }
            DecodedKey::RawKey(code) => key_name(code),
        };
        self.dirty |= bit(KEYS);
    }

    // -----------------------------------------------------------------------
    // Pro Bild: Zustand fortschreiben, geänderte Ebenen neu rendern
    // -----------------------------------------------------------------------

    fn update(&mut self, now: u64) {
        let t = time::now();
        if t.second != self.shown_second {
            self.shown_second = t.second;
            self.dirty |= bit(CLOCK) | bit(TOPBAR);
        }
        let caret = (now / 530) % 2 == 0;
        if caret != self.shown_caret {
            self.shown_caret = caret;
            self.dirty |= bit(KEYS);
        }
        if self.fps != self.shown_fps {
            self.shown_fps = self.fps;
            self.dirty |= bit(TOPBAR);
        }
        self.dirty |= bit(PERF); // Diagramm läuft ständig

        // Theme- oder Akzent-Animation: Palette neu berechnen, alles neu rendern
        let theme_anim = self.light.running(now);
        if theme_anim || self.accent_t.running(now) {
            let light = self.light.value(now);
            self.comp.palette = theme::palette(light, self.accent(now));
            self.dirty = u32::MAX;
            if theme_anim || self.comp.light != light {
                self.comp.light = light;
                self.comp.damage_all();
            }
        }

        // Einflug-Animation
        self.intro.retain(|(id, x, y, tw)| {
            let v = tw.value(now);
            let dy = if *id == TOPBAR { -60.0 } else { 40.0 };
            self.comp.set_geometry(*id, *x, *y + dy * (1.0 - v), v);
            tw.running(now)
        });

        // Klick-Wellen
        let mut done = Vec::new();
        for r in &self.ripples {
            let p = ((now - r.start) as f32 / RIPPLE_MS as f32).min(1.0);
            let accent = self.comp.palette.accent;
            if let Some(l) = self.comp.layer(r.id) {
                l.content.clear();
                let e = ease_out_cubic(p);
                let c = RIPPLE_SIZE as f32 / 2.0;
                l.content.ring(c, c, 4.0 + e * (c - 6.0), 2.5, accent.with_alpha((230.0 * (1.0 - p)) as u8));
            }
            self.comp.damage_layer(r.id);
            if p >= 1.0 {
                done.push(r.id);
            }
        }
        for id in done {
            self.comp.remove(id);
            self.ripples.retain(|r| r.id != id);
        }

        // Mauszeiger
        self.comp.set_geometry(CURSOR, self.mx as f32, self.my as f32, 1.0);

        // Inhalte neu rendern
        let p = self.comp.palette;
        for id in [TOPBAR, CLOCK, KEYS, LOOK, PERF] {
            if self.dirty & bit(id) != 0 {
                self.render_layer(id, &p, now);
                self.comp.damage_layer(id);
            }
        }
        self.dirty = 0;
    }

    fn render_layer(&mut self, id: u8, p: &Palette, now: u64) {
        // Inhalt vorübergehend herausnehmen, damit wir `self` lesen können
        let Some(l) = self.comp.layer(id) else { return };
        let mut img = core::mem::replace(&mut l.content, Image::new(1, 1));
        img.clear();
        match id {
            TOPBAR => self.draw_topbar(&mut img, p),
            CLOCK => self.draw_clock(&mut img, p),
            KEYS => self.draw_keys(&mut img, p),
            LOOK => self.draw_look(&mut img, p, now),
            PERF => self.draw_perf(&mut img, p),
            _ => {}
        }
        if let Some(l) = self.comp.layer(id) {
            l.content = img;
        }
    }

    // -----------------------------------------------------------------------
    // Inhalte der Ebenen
    // -----------------------------------------------------------------------

    fn draw_topbar(&self, img: &mut Image, p: &Palette) {
        let w = img.w as f32;
        img.circle(24.0, 22.0, 5.0, p.accent);
        img.text(38.0, 27.0, "AuroraOS", 15.0, Weight::SemiBold, p.text);
        let t = time::now();
        let center = format!(
            "{}, {}. {}   {:02}:{:02}",
            &time::WEEKDAYS[t.weekday as usize][..2],
            t.day,
            time::MONTHS[t.month as usize - 1],
            t.hour,
            t.minute
        );
        img.text_centered(w / 2.0, 27.0, &center, 14.0, Weight::SemiBold, p.text);
        let right = format!("Karten am Titel verschieben  ·  {} FPS", self.fps);
        let rw = font::measure(&right, 13.0, Weight::Regular);
        img.text(w - 24.0 - rw, 27.0, &right, 13.0, Weight::Regular, p.text_muted);
    }

    fn draw_clock(&self, img: &mut Image, p: &Palette) {
        card_title(img, p, "Uhr", "Mitteleuropäische Zeit");
        let t = time::now();
        let clock = format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second);
        // Ziffern in festen Zellen, damit die Uhr beim Ticken nicht „wackelt“
        let size = 64.0;
        let cell = font::measure("0", size, Weight::Regular);
        let colon = font::measure(":", size, Weight::Regular) + 4.0;
        let mut x = 24.0;
        for ch in clock.chars() {
            let cw = if ch == ':' { colon } else { cell };
            let gw = font::measure(ch.encode_utf8(&mut [0; 4]), size, Weight::Regular);
            let color = if ch == ':' { p.accent } else { p.text };
            img.text(x + (cw - gw) / 2.0, 146.0, ch.encode_utf8(&mut [0; 4]), size, Weight::Regular, color);
            x += cw;
        }
        let date = format!("{}, {}. {} {}", time::WEEKDAYS[t.weekday as usize], t.day, time::MONTHS[t.month as usize - 1], t.year);
        img.text(24.0, 180.0, &date, 15.0, Weight::Regular, p.text_muted);
    }

    fn draw_keys(&self, img: &mut Image, p: &Palette) {
        card_title(img, p, "Tastatur", "Deutsch (QWERTZ) · Esc löscht · F2 Hell/Dunkel");
        let (fx, fy, fw, fh) = (24.0, 80.0, img.w as f32 - 48.0, 116.0);
        img.fill_rounded(fx, fy, fw, fh, 12.0, p.well);
        img.stroke_rounded(fx, fy, fw, fh, 12.0, 1.0, p.well_border);

        let size = 15.0;
        let line_h = 21.0;
        let max_w = fw - 28.0;
        let max_lines = ((fh - 16.0) / line_h) as usize;
        // Zeilenumbruch: an '\n' und wenn die Zeile zu breit wird
        let mut lines: Vec<String> = Vec::from([String::new()]);
        for ch in self.text.chars() {
            if ch == '\n' {
                lines.push(String::new());
                continue;
            }
            let cur = lines.last().unwrap();
            if font::measure(cur, size, Weight::Regular) + font::measure(ch.encode_utf8(&mut [0; 4]), size, Weight::Regular) > max_w {
                lines.push(String::new());
            }
            lines.last_mut().unwrap().push(ch);
        }
        let first = lines.len().saturating_sub(max_lines);
        if self.text.is_empty() {
            img.text(fx + 14.0, fy + 26.0, "Hier erscheint dein Text …", size, Weight::Regular, p.text_faint);
        }
        let mut y = fy + 26.0;
        let mut caret_x = fx + 14.0;
        for line in &lines[first..] {
            caret_x = fx + 14.0 + img.text(fx + 14.0, y, line, size, Weight::Regular, p.text);
            y += line_h;
        }
        if self.shown_caret {
            img.fill_rounded(caret_x + 1.0, y - line_h - 14.0, 2.0, 18.0, 1.0, p.accent);
        }
        let w = img.text(24.0, 222.0, "Letzte Taste:  ", 13.0, Weight::Regular, p.text_muted);
        img.text(24.0 + w, 222.0, &self.last_key, 13.0, Weight::SemiBold, p.accent);
    }

    fn draw_look(&self, img: &mut Image, p: &Palette, now: u64) {
        card_title(img, p, "Darstellung", "Farbschema und Akzentfarbe (auch per Scrollrad)");
        let w = img.w as f32;
        img.text(24.0, 101.0, "Dunkler Modus", 15.0, Weight::Regular, p.text);
        // Schalter: Knopf gleitet mit der Theme-Animation mit
        let on = 1.0 - self.light.value(now); // 1 = dunkel
        let (sx, sy, sw, sh) = (w - 24.0 - 52.0, 80.0, 52.0, 30.0);
        img.fill_rounded(sx, sy, sw, sh, 15.0, p.control.lerp(p.accent, on));
        img.circle(sx + 15.0 + on * (sw - 30.0), sy + 15.0, 11.0, Rgba::hex(0xFFFFFF));

        img.text(24.0, 140.0, "Akzentfarbe", 15.0, Weight::Regular, p.text);
        let name = ACCENTS[self.accent_idx].0;
        let nw = font::measure(name, 13.0, Weight::Regular);
        img.text(w - 24.0 - nw, 140.0, name, 13.0, Weight::Regular, p.text_muted);
        for (i, (_, rgb)) in ACCENTS.iter().enumerate() {
            let cx = 24.0 + 14.0 + i as f32 * 44.0;
            img.circle(cx, 172.0, 12.0, Rgba::hex(*rgb));
            if i == self.accent_idx {
                img.ring(cx, 172.0, 17.0, 2.0, p.text);
            }
        }
    }

    fn draw_perf(&self, img: &mut Image, p: &Palette) {
        card_title(img, p, "Leistung", "Compositor mit SSE");
        let w = img.w as f32;
        let fps = format!("{}", self.fps);
        let fw = img.text(24.0, 118.0, &fps, 40.0, Weight::SemiBold, p.text);
        img.text(24.0 + fw + 6.0, 118.0, "FPS", 15.0, Weight::Regular, p.text_muted);
        let last = self.frame_times.back().copied().unwrap_or(0.0);
        let avg = if self.frame_times.is_empty() { 0.0 } else { self.frame_times.iter().sum::<f32>() / self.frame_times.len() as f32 };
        let info = format!("Bildzeit {:.1} ms (Ø {:.1})", last, avg).replace('.', ",");
        let iw = font::measure(&info, 13.0, Weight::Regular);
        img.text(w - 24.0 - iw, 116.0, &info, 13.0, Weight::Regular, p.text_muted);

        // Diagramm der Bildzeiten; Linie bei 16,7 ms = Grenze für 60 FPS
        let (gx, gy, gw, gh) = (24.0, 134.0, w - 48.0, 64.0);
        let max_ms = 25.0;
        let budget_y = gy + gh - gh * (16.7 / max_ms);
        img.line(gx, budget_y, gx + gw, budget_y, 1.0, p.text_faint.with_alpha(120));
        let n = self.frame_times.len();
        if n >= 2 {
            let step = gw / 99.0;
            let pt = |i: usize, v: f32| (gx + gw - (n - 1 - i) as f32 * step, gy + gh - gh * (v.min(max_ms) / max_ms));
            for (i, v) in self.frame_times.iter().enumerate() {
                let (x, y) = pt(i, *v);
                img.line(x, y, x, gy + gh, step, p.accent.with_alpha(40));
            }
            for i in 1..n {
                let (ax, ay) = pt(i - 1, self.frame_times[i - 1]);
                let (bx, by) = pt(i, self.frame_times[i]);
                img.line(ax, ay, bx, by, 1.8, p.accent);
            }
        }
        img.text(24.0, 226.0, "Linie: 16,7 ms = Grenze für 60 Bilder pro Sekunde", 12.0, Weight::Regular, p.text_faint);
    }

    // -----------------------------------------------------------------------
    // Hauptschleife
    // -----------------------------------------------------------------------

    pub fn run(mut self) -> ! {
        let mut frame: u64 = 0;
        let start = time::ticks();
        loop {
            let now = time::ticks();
            self.handle_input(now);
            // Bildtakt: 60 pro Sekunde, gleichmäßig verteilt (16 oder 17 ms)
            let due = start + frame * 1000 / 60;
            if now >= due {
                let t0 = time::rdtsc();
                self.update(now);
                self.comp.compose();
                let ms = time::micros_since(t0) as f32 / 1000.0;
                self.frame_times.push_back(ms);
                if self.frame_times.len() > 100 {
                    self.frame_times.pop_front();
                }
                self.frames_in_second += 1;
                if now - self.second_start >= 1000 {
                    self.fps = self.frames_in_second;
                    self.frames_in_second = 0;
                    self.second_start = now;
                    crate::serial_println!(
                        "[aurora] {} FPS, Bildzeit {:.2} ms, {} Pixel, {} Zeichen im Cache, IRQs {}/{}",
                        self.fps,
                        ms,
                        self.comp.last_pixels,
                        font::cached_glyphs(),
                        KEYBOARD_IRQS.load(Ordering::Relaxed),
                        MOUSE_IRQS.load(Ordering::Relaxed)
                    );
                }
                frame += 1;
                // Hinken wir mehr als ein Bild hinterher, nicht alles nachholen
                if time::ticks() > start + frame * 1000 / 60 + 50 {
                    frame = (time::ticks() - start) * 60 / 1000;
                }
            }
            x86_64::instructions::interrupts::enable_and_hlt();
        }
    }
}

/// Überschrift und Untertitel einer Karte
fn card_title(img: &mut Image, p: &Palette, title: &str, subtitle: &str) {
    img.text(24.0, 38.0, title, 18.0, Weight::SemiBold, p.text);
    img.text(24.0, 58.0, subtitle, 13.0, Weight::Regular, p.text_muted);
}

/// Mauszeiger mit weichem Schatten
fn draw_cursor(img: &mut Image) {
    for (row, line) in CURSOR_SHAPE.iter().enumerate() {
        for (col, ch) in line.chars().enumerate() {
            if ch != ' ' {
                img.blend(col as i32 + 1, row as i32 + 2, Rgba::hex(0x000000), 0.3);
            }
        }
    }
    for (row, line) in CURSOR_SHAPE.iter().enumerate() {
        for (col, ch) in line.chars().enumerate() {
            let c = match ch {
                'X' => Rgba::hex(0x0B1020),
                '.' => Rgba::hex(0xFFFFFF),
                _ => continue,
            };
            img.blend(col as i32, row as i32, c, 1.0);
        }
    }
}

fn key_name(code: KeyCode) -> String {
    let name = match code {
        KeyCode::ArrowUp => "Pfeil hoch",
        KeyCode::ArrowDown => "Pfeil runter",
        KeyCode::ArrowLeft => "Pfeil links",
        KeyCode::ArrowRight => "Pfeil rechts",
        KeyCode::LShift | KeyCode::RShift => "Umschalt",
        KeyCode::LControl | KeyCode::RControl => "Strg",
        KeyCode::LAlt => "Alt",
        KeyCode::RAltGr => "AltGr",
        KeyCode::LWin | KeyCode::RWin => "Windows-Taste",
        KeyCode::CapsLock => "Feststelltaste",
        KeyCode::Home => "Pos1",
        KeyCode::End => "Ende",
        KeyCode::PageUp => "Bild hoch",
        KeyCode::PageDown => "Bild runter",
        KeyCode::Insert => "Einfg",
        other => return format!("{:?}", other),
    };
    name.into()
}
