//! Interaktiver Bildschirm für Meilenstein 4: Uhr, Tastatur, Maus.
//!
//! Zeichen-Strategie („Dirty Rectangles“):
//! * `scene`: alles Statische (Hintergrund, Karten, Beschriftungen) – einmal gezeichnet.
//! * `back`: Arbeitsfläche. Für jedes geänderte Rechteck wird zuerst die Szene
//!   hineinkopiert, dann die dynamischen Inhalte und der Mauszeiger darüber.
//! * Nur die fertigen Rechtecke werden in den Framebuffer kopiert.
//!   -> kein Flackern, und wir zeichnen nur, was sich wirklich ändert.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

use noto_sans_mono_bitmap::{FontWeight, RasterHeight, get_raster};
use pc_keyboard::{DecodedKey, HandleControl, KeyCode, PS2Keyboard as Keyboard, ScancodeSet1, layouts::De105Key};

use crate::framebuffer;
use crate::gfx::{Canvas, Color, Rect, Surface};
use crate::interrupts::{KEYBOARD_BYTES, KEYBOARD_IRQS, MOUSE_BYTES, MOUSE_IRQS};
use crate::ps2::{MouseParser, Ps2Info};
use crate::screens::{ACCENT, ACCENT_2, BG_BOTTOM, BG_TOP, GLASS, TEXT, TEXT_MUTED, glass_card};
use crate::time;

const R16: RasterHeight = RasterHeight::Size16;
const REG: FontWeight = FontWeight::Regular;
const BOLD: FontWeight = FontWeight::Bold;
const LINE_H: i32 = 22;

/// Klassischer Pfeil-Mauszeiger: X = Rand, . = Füllung
const CURSOR: [&str; 19] = [
    "X", "XX", "X.X", "X..X", "X...X", "X....X", "X.....X", "X......X", "X.......X", "X........X", "X.........X",
    "X..........X", "X......XXXXX", "X...X..X", "X..XX..X", "X.X  X..X", "XX   X..X", "X     X..X", "      XXX",
];
const CURSOR_RECT_W: i32 = 14;
const CURSOR_RECT_H: i32 = 22;

struct Ripple {
    x: i32,
    y: i32,
    start: u64,
}
const RIPPLE_MS: u64 = 450;
const RIPPLE_R: i32 = 30;

pub struct Desktop {
    w: i32,
    h: i32,
    scene: Surface,
    back: Surface,
    keyboard: Keyboard<De105Key, ScancodeSet1>,
    mouse_parser: MouseParser,
    ps2_wheel: bool,

    // Zustand
    text: String,
    last_key: String,
    mx: i32,
    my: i32,
    buttons: u8,
    wheel: i32,
    clicks: u32,
    ripples: Vec<Ripple>,

    // was zuletzt gezeichnet wurde (um Änderungen zu erkennen)
    shown_clock: String,
    shown_status: String,
    shown_caret: bool,
    shown_cursor: Rect,
    dirty: Vec<Rect>,
    frames: u64,

    // Layout
    clock: Rect,
    field: Rect,
    key_info: Rect,
    mouse_info: Rect,
    status: Rect,
}

impl Desktop {
    pub fn new(ps2: &Ps2Info) -> Self {
        let fb = framebuffer::canvas().expect("kein Framebuffer");
        let (w, h) = (fb.width, fb.height);
        let shift = fb.shift();

        let (kw, mw, gap, ch) = (560, 320, 24, 300);
        let kx = (w - (kw + gap + mw)) / 2;
        let mx = kx + kw + gap;
        let cy = h * 33 / 100;

        let mut d = Desktop {
            w,
            h,
            scene: Surface::new(w, h, shift),
            back: Surface::new(w, h, shift),
            keyboard: Keyboard::new(ScancodeSet1::new(), De105Key, HandleControl::Ignore),
            mouse_parser: MouseParser::new(ps2.wheel),
            ps2_wheel: ps2.wheel,
            text: String::new(),
            last_key: String::from("–"),
            mx: w / 2,
            my: h / 2,
            buttons: 0,
            wheel: 0,
            clicks: 0,
            ripples: Vec::new(),
            shown_clock: String::new(),
            shown_status: String::new(),
            shown_caret: false,
            shown_cursor: Rect::new(w / 2, h / 2, CURSOR_RECT_W, CURSOR_RECT_H),
            dirty: vec![Rect::new(0, 0, w, h)],
            frames: 0,
            clock: Rect::new((w - 600) / 2, h * 8 / 100, 600, 140),
            field: Rect::new(kx + 28, cy + 92, kw - 56, 152),
            key_info: Rect::new(kx + 28, cy + 256, kw - 56, 24),
            mouse_info: Rect::new(mx + 28, cy + 92, mw - 56, 188),
            status: Rect::new((w - 760) / 2, h - 72, 760, 40),
        };
        d.draw_scene(Rect::new(kx, cy, kw, ch), Rect::new(mx, cy, mw, ch));
        d
    }

    /// Statischer Teil – wird nur einmal gezeichnet
    fn draw_scene(&mut self, kcard: Rect, mcard: Rect) {
        let (w, h) = (self.w, self.h);
        let c = &mut self.scene.canvas;
        c.aurora_background(BG_TOP, BG_BOTTOM, &[(w / 4, h / 3, w / 2, ACCENT, 70), (w * 3 / 4, h * 2 / 3, w / 2, ACCENT_2, 90)]);

        glass_card(c, kcard.x, kcard.y, kcard.w, kcard.h);
        c.text(kcard.x + 28, kcard.y + 24, "Tastatur", BOLD, RasterHeight::Size24, TEXT);
        c.text(kcard.x + 28, kcard.y + 58, "Deutsches Layout (QWERTZ) – tippe einfach los", REG, R16, TEXT_MUTED);
        // Textfeld: dunkle, abgerundete Mulde mit feiner Kante
        let f = self.field;
        c.rounded_rect(f.x, f.y, f.w, f.h, 12, Color::hex(0x000000), 70);
        c.rounded_border(f.x, f.y, f.w, f.h, 12, GLASS, 40);

        glass_card(c, mcard.x, mcard.y, mcard.w, mcard.h);
        c.text(mcard.x + 28, mcard.y + 24, "Maus", BOLD, RasterHeight::Size24, TEXT);
        let sub = if self.ps2_wheel { "PS/2 mit Scrollrad" } else { "PS/2 ohne Scrollrad" };
        c.text(mcard.x + 28, mcard.y + 58, sub, REG, R16, TEXT_MUTED);

        // Statusleiste: Glas-Pille
        let s = self.status;
        c.rounded_rect(s.x, s.y, s.w, s.h, s.h / 2, GLASS, 22);
        c.rounded_border(s.x, s.y, s.w, s.h, s.h / 2, GLASS, 60);
    }

    // -----------------------------------------------------------------------
    // Eingaben
    // -----------------------------------------------------------------------

    pub fn handle_input(&mut self) {
        while let Some(byte) = KEYBOARD_BYTES.pop() {
            if let Ok(Some(event)) = self.keyboard.add_byte(byte) {
                if let Some(key) = self.keyboard.process_keyevent(event) {
                    self.on_key(key);
                }
            }
        }
        while let Some(byte) = MOUSE_BYTES.pop() {
            if let Some(p) = self.mouse_parser.feed(byte) {
                self.mx = (self.mx + p.dx).clamp(0, self.w - 1);
                self.my = (self.my + p.dy).clamp(0, self.h - 1);
                self.wheel += p.wheel;
                let pressed = p.buttons & !self.buttons;
                if pressed != 0 {
                    self.clicks += 1;
                    self.ripples.push(Ripple { x: self.mx, y: self.my, start: time::ticks() });
                }
                self.buttons = p.buttons;
                self.dirty.push(self.mouse_info);
            }
        }
    }

    fn on_key(&mut self, key: DecodedKey) {
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
                "Esc (Text gelöscht)".into()
            }
            DecodedKey::Unicode('\u{7f}') => "Entf".into(),
            DecodedKey::Unicode(ch) => {
                // nur Zeichen übernehmen, die unsere Schrift auch darstellen kann
                let ok = get_raster(ch, REG, R16).is_some() || crate::gfx::glyph_fallback(ch).is_some();
                if ok {
                    self.text.push(ch);
                }
                if ch == ' ' { "Leertaste".into() } else { format!("'{}'  (U+{:04X})", ch, ch as u32) }
            }
            DecodedKey::RawKey(code) => key_name(code),
        };
        self.dirty.push(self.field);
        self.dirty.push(self.key_info);
    }

    // -----------------------------------------------------------------------
    // Pro Bild: was hat sich geändert?
    // -----------------------------------------------------------------------

    pub fn update(&mut self, now: u64) {
        let t = time::now();
        let clock = format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second);
        if clock != self.shown_clock {
            self.shown_clock = clock;
            self.dirty.push(self.clock);
        }

        let caret = (now / 530) % 2 == 0; // blinkender Textcursor
        if caret != self.shown_caret {
            self.shown_caret = caret;
            self.dirty.push(self.field);
        }

        let up = now / time::HZ;
        let status = format!(
            "Timer {} Hz · Laufzeit {:02}:{:02}:{:02} · IRQs: Tastatur {} · Maus {} · {} Bilder",
            time::HZ,
            up / 3600,
            up / 60 % 60,
            up % 60,
            KEYBOARD_IRQS.load(Ordering::Relaxed),
            MOUSE_IRQS.load(Ordering::Relaxed),
            self.frames
        );
        if status != self.shown_status && (now % 250 < 20 || self.shown_status.is_empty()) {
            self.shown_status = status;
            self.dirty.push(self.status);
        }

        // Klick-Wellen: solange sie laufen, jedes Bild neu zeichnen
        for r in &self.ripples {
            self.dirty.push(Rect::new(r.x - RIPPLE_R - 2, r.y - RIPPLE_R - 2, 2 * RIPPLE_R + 4, 2 * RIPPLE_R + 4));
        }
        self.ripples.retain(|r| now - r.start < RIPPLE_MS + 20);

        let cursor = Rect::new(self.mx - 1, self.my - 1, CURSOR_RECT_W, CURSOR_RECT_H);
        if cursor != self.shown_cursor {
            self.dirty.push(self.shown_cursor); // alte Stelle wiederherstellen
            self.dirty.push(cursor);
            self.shown_cursor = cursor;
        }
    }

    // -----------------------------------------------------------------------
    // Zeichnen
    // -----------------------------------------------------------------------

    pub fn render(&mut self, now: u64) {
        if self.dirty.is_empty() {
            return;
        }
        let Some(mut fb) = framebuffer::canvas() else { return };
        let dirty = core::mem::take(&mut self.dirty);
        for r in dirty.iter() {
            let r = *r;
            self.back.canvas.copy_from(&self.scene.canvas, r);
            self.back.canvas.set_clip(r);
            self.draw_dynamic(r, now);
            self.back.canvas.reset_clip();
            fb.copy_from(&self.back.canvas, r);
        }
        self.dirty = dirty;
        self.dirty.clear();
        self.frames += 1;
    }

    fn draw_dynamic(&mut self, r: Rect, now: u64) {
        if r.intersects(&self.clock) {
            self.draw_clock();
        }
        if r.intersects(&self.field) {
            self.draw_text_field();
        }
        if r.intersects(&self.key_info) {
            let c = &mut self.back.canvas;
            let k = self.key_info;
            let w = c.text(k.x, k.y, "Letzte Taste: ", REG, R16, TEXT_MUTED);
            c.text(k.x + w, k.y, &self.last_key, REG, R16, ACCENT);
        }
        if r.intersects(&self.mouse_info) {
            self.draw_mouse_info();
        }
        if r.intersects(&self.status) {
            let s = self.status;
            let c = &mut self.back.canvas;
            let tw = Canvas::text_width(&self.shown_status, REG, R16);
            c.text(s.x + (s.w - tw) / 2, s.y + 12, &self.shown_status, REG, R16, TEXT_MUTED);
        }
        for rip in &self.ripples {
            // Ease-out: schnell starten, sanft auslaufen
            let t = ((now - rip.start).min(RIPPLE_MS) * 256 / RIPPLE_MS) as i32;
            let inv = 256 - t;
            let radius = RIPPLE_R * (65536 - inv * inv) / 65536;
            let alpha = (220 * inv / 256) as u32;
            self.back.canvas.ring(rip.x, rip.y, radius.max(2), 3, ACCENT, alpha);
        }
        if r.intersects(&self.shown_cursor) {
            self.draw_cursor();
        }
    }

    fn draw_clock(&mut self) {
        let c = &mut self.back.canvas;
        let cr = self.clock;
        let tw = Canvas::text_width(&self.shown_clock, BOLD, RasterHeight::Size32) * 3;
        c.text_scaled(cr.x + (cr.w - tw) / 2, cr.y, &self.shown_clock, BOLD, RasterHeight::Size32, 3, TEXT);
        let t = time::now();
        let date = format!("{}, {}. {} {}", time::WEEKDAYS[t.weekday as usize], t.day, time::MONTHS[t.month as usize - 1], t.year);
        let dw = Canvas::text_width(&date, REG, RasterHeight::Size24);
        c.text(cr.x + (cr.w - dw) / 2, cr.y + 104, &date, REG, RasterHeight::Size24, TEXT_MUTED);
    }

    fn draw_text_field(&mut self) {
        let f = self.field;
        let cols = ((f.w - 24) / 8) as usize;
        let max_lines = ((f.h - 20) / LINE_H) as usize;

        // Text in Zeilen umbrechen (an '\n' und an der Feldbreite)
        let mut lines: Vec<String> = vec![String::new()];
        for ch in self.text.chars() {
            if ch == '\n' {
                lines.push(String::new());
                continue;
            }
            if lines.last().unwrap().chars().count() >= cols {
                lines.push(String::new());
            }
            lines.last_mut().unwrap().push(ch);
        }
        let first = lines.len().saturating_sub(max_lines);
        let c = &mut self.back.canvas;
        if self.text.is_empty() {
            c.text(f.x + 12, f.y + 12, "Hier erscheint dein Text …", REG, R16, Color::hex(0x64748B));
        }
        let mut y = f.y + 12;
        let mut caret_x = f.x + 12;
        for line in &lines[first..] {
            caret_x = f.x + 12 + c.text(f.x + 12, y, line, REG, R16, TEXT);
            y += LINE_H;
        }
        if self.shown_caret {
            let cy = y - LINE_H;
            c.rounded_rect(caret_x + 1, cy, 2, 18, 1, ACCENT, 256);
        }
    }

    fn draw_mouse_info(&mut self) {
        let m = self.mouse_info;
        let c = &mut self.back.canvas;
        let rows = [
            ("Position", format!("{}, {}", self.mx, self.my)),
            ("Scrollrad", format!("{:+}", self.wheel)),
            ("Klicks", format!("{}", self.clicks)),
        ];
        for (i, (label, value)) in rows.iter().enumerate() {
            let y = m.y + i as i32 * 28;
            c.text(m.x, y, label, REG, R16, TEXT_MUTED);
            c.text(m.x + 110, y, value, REG, R16, TEXT);
        }
        // Tasten als Pillen: leuchten, solange gedrückt
        let names = [("Links", 0x01u8), ("Mitte", 0x04), ("Rechts", 0x02)];
        let bw = (m.w - 16) / 3;
        for (i, (name, bit)) in names.iter().enumerate() {
            let x = m.x + i as i32 * (bw + 8);
            let y = m.y + 110;
            let pressed = self.buttons & bit != 0;
            if pressed {
                c.rounded_rect(x, y, bw, 40, 20, ACCENT, 230);
            } else {
                c.rounded_rect(x, y, bw, 40, 20, GLASS, 25);
                c.rounded_border(x, y, bw, 40, 20, GLASS, 60);
            }
            let tw = Canvas::text_width(name, BOLD, R16);
            c.text(x + (bw - tw) / 2, y + 12, name, BOLD, R16, if pressed { BG_TOP } else { TEXT });
        }
    }

    fn draw_cursor(&mut self) {
        let c = &mut self.back.canvas;
        let (x, y) = (self.mx, self.my);
        // weicher Schatten, leicht versetzt
        for (row, line) in CURSOR.iter().enumerate() {
            for (col, ch) in line.chars().enumerate() {
                if ch != ' ' {
                    c.blend(x + col as i32 + 1, y + row as i32 + 2, Color::hex(0x000000), 70);
                }
            }
        }
        for (row, line) in CURSOR.iter().enumerate() {
            for (col, ch) in line.chars().enumerate() {
                let color = match ch {
                    'X' => Color::hex(0x0B1020),
                    '.' => Color::hex(0xFFFFFF),
                    _ => continue,
                };
                c.put(x + col as i32, y + row as i32, color);
            }
        }
    }

    /// Hauptschleife: Eingaben verarbeiten, ~60 Bilder pro Sekunde zeichnen,
    /// dazwischen mit `hlt` schlafen.
    pub fn run(mut self) -> ! {
        let mut next_frame = 0;
        loop {
            self.handle_input();
            let now = time::ticks();
            if now >= next_frame {
                self.update(now);
                self.render(now);
                next_frame = now + 16; // 1000 Hz / 16 ≈ 60 FPS
            }
            x86_64::instructions::interrupts::enable_and_hlt();
        }
    }
}

/// Lesbare Namen für Tasten ohne Zeichen
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
