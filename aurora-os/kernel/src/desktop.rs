//! Desktop mit Fenstermanager (Meilenstein 6).
//!
//! * Jedes Fenster ist eine Compositor-Ebene; die Reihenfolge der Ebenen ist
//!   die Stapelreihenfolge (oben = zuletzt fokussiert).
//! * Fenster lassen sich verschieben, an allen Rändern in der Größe ändern,
//!   an den Bildschirmrand andocken (links/rechts = halber Bildschirm,
//!   oben = maximieren), minimieren, maximieren und schließen.
//! * Unten das Dock mit App-Symbolen, oben die Menüleiste.

use alloc::collections::VecDeque;
use alloc::format;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

use pc_keyboard::{DecodedKey, HandleControl, KeyCode, KeyState, PS2Keyboard, ScancodeSet1, layouts::De105Key};

use crate::anim::{Tween, ease_in_out_cubic, ease_out_cubic};
use crate::apps::{self, AppKind, Ctx, Notes, TITLE_H};
use crate::compositor::{Compositor, Layer};
use crate::font::{self, Weight};
use crate::interrupts::{KEYBOARD_BYTES, KEYBOARD_IRQS, MOUSE_BYTES, MOUSE_IRQS};
use crate::paint::{Image, Rgba};
use crate::ps2::{MouseParser, Ps2Info};
use crate::theme::{self, ACCENTS, Palette};
use crate::{allocator, framebuffer, time};

// Ebenen-IDs (Fenster: 10 + App-Nummer)
const PREVIEW: u8 = 1;
const TOPBAR: u8 = 2;
const DOCK: u8 = 3;
const TOOLTIP: u8 = 4;
const RIPPLE_BASE: u8 = 100;
const CURSOR: u8 = 250;
/// Alles, was immer über den Fenstern liegt
const OVERLAYS: [u8; 5] = [PREVIEW, TOPBAR, DOCK, TOOLTIP, CURSOR];

const RIPPLE_SIZE: i32 = 80;
const RIPPLE_MS: u64 = 500;
const THEME_MS: u64 = 450;
const EDGE: i32 = 6; // Greifbreite der Fensterränder

const DOCK_ICON: f32 = 48.0;
const DOCK_GAP: f32 = 14.0;
const DOCK_PAD: f32 = 14.0;

// Ränder für die Größenänderung (Bitmaske)
const LEFT: u8 = 1;
const RIGHT: u8 = 2;
const TOP: u8 = 4;
const BOTTOM: u8 = 8;

#[derive(Clone, Copy, PartialEq)]
enum WinState {
    Normal,
    Maximized,
    SnapLeft,
    SnapRight,
}

#[derive(Clone, Copy, PartialEq)]
enum Phase {
    Opening,
    Open,
    Minimizing,
    Minimized,
    Restoring,
    Closing,
}

type R = [f32; 4]; // x, y, w, h

struct Window {
    app: AppKind,
    rect: R,
    state: WinState,
    restore: R, // Größe vor Maximieren/Andocken
    geom: Option<(R, R, Tween)>,
    fade: Tween,
    phase: Phase,
    dirty: bool,
}

#[derive(Clone, Copy, PartialEq)]
enum Grab {
    None,
    Move { app: AppKind, dx: f32, dy: f32 },
    Resize { app: AppKind, edges: u8, start: R, mx: i32, my: i32 },
    Button { app: AppKind, which: u8 },
}

#[derive(Clone, Copy, PartialEq)]
enum CursorKind {
    Arrow,
    ResizeH,
    ResizeV,
    ResizeNwse,
    ResizeNesw,
}

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
    ctrl: bool,

    windows: Vec<Window>,
    focus: Option<AppKind>,
    grab: Grab,
    snap_target: Option<WinState>,
    preview_fade: Tween,
    hover_dots: Option<AppKind>,
    hover_icon: Option<usize>,
    cursor_kind: CursorKind,

    mx: i32,
    my: i32,
    buttons: u8,
    ripples: Vec<Ripple>,
    next_ripple: u8,

    notes: Notes,
    light: Tween,
    accent_idx: usize,
    accent_from: Rgba,
    accent_t: Tween,
    intro: Vec<(u8, f32, f32, Tween)>,

    frame_times: VecDeque<f32>,
    fps: u32,
    frames_in_second: u32,
    second_start: u64,
    shown_second: u32,
    shown_caret: bool,
    monitor_tick: u64,
    chrome_dirty: bool,
}

impl Desktop {
    pub fn new(ps2: &Ps2Info) -> Self {
        let fb = framebuffer::info().expect("kein Framebuffer");
        let (w, h) = (fb.width as i32, fb.height as i32);
        let accent = Rgba::hex(ACCENTS[0].1);
        let mut comp = Compositor::new(w, h, theme::palette(0.0, accent));

        // Feste Ebenen: Vorschau beim Andocken, Menüleiste, Dock, Tooltip, Mauszeiger
        let mut preview = Layer::new(PREVIEW, 100, 100, 16.0, false, false);
        preview.opacity = 0.0;
        comp.layers.push(preview);
        let mut top = Layer::new(TOPBAR, w - 32, 40, 20.0, true, true);
        top.x = 16.0;
        top.y = 12.0;
        top.opacity = 0.0;
        comp.layers.push(top);
        let n = AppKind::ALL.len() as f32;
        let dock_w = (n * DOCK_ICON + (n - 1.0) * DOCK_GAP + 2.0 * DOCK_PAD) as i32;
        let mut dock = Layer::new(DOCK, dock_w, 76, 24.0, true, true);
        dock.x = ((w - dock_w) / 2) as f32;
        dock.y = (h - 90) as f32;
        dock.opacity = 0.0;
        comp.layers.push(dock);
        let mut tip = Layer::new(TOOLTIP, 120, 30, 15.0, true, true);
        tip.opacity = 0.0;
        comp.layers.push(tip);
        let mut cursor = Layer::new(CURSOR, 24, 24, 0.0, false, false);
        draw_cursor(&mut cursor.content, CursorKind::Arrow);
        cursor.x = (w / 2) as f32;
        cursor.y = (h / 2) as f32;
        comp.layers.push(cursor);

        let now = time::ticks();
        let intro = Vec::from([
            (TOPBAR, 16.0, 12.0, Tween::new(0.0, 1.0, now + 100, 600, ease_out_cubic)),
            (DOCK, ((w - dock_w) / 2) as f32, (h - 90) as f32, Tween::new(0.0, 1.0, now + 200, 600, ease_out_cubic)),
        ]);

        let mut d = Desktop {
            comp,
            w,
            h,
            keyboard: PS2Keyboard::new(ScancodeSet1::new(), De105Key, HandleControl::Ignore),
            mouse: MouseParser::new(ps2.wheel),
            ctrl: false,
            windows: Vec::new(),
            focus: None,
            grab: Grab::None,
            snap_target: None,
            preview_fade: Tween::fixed(0.0),
            hover_dots: None,
            hover_icon: None,
            cursor_kind: CursorKind::Arrow,
            mx: w / 2,
            my: h / 2,
            buttons: 0,
            ripples: Vec::new(),
            next_ripple: 0,
            notes: Notes::new(),
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
            monitor_tick: 0,
            chrome_dirty: true,
        };
        // Startfenster
        d.open(AppKind::Clock, now + 300, Some([60.0, 84.0, 420.0, 230.0]));
        d.open(AppKind::Settings, now + 400, Some([60.0, 340.0, 420.0, 320.0]));
        d.open(AppKind::Notes, now + 500, Some([520.0, 110.0, 600.0, 420.0]));
        d
    }

    // -----------------------------------------------------------------------
    // Arbeitsfläche und Fenster-Geometrie
    // -----------------------------------------------------------------------

    /// Bereich zwischen Menüleiste und Dock
    fn work_area(&self) -> R {
        [8.0, 64.0, (self.w - 16) as f32, (self.h - 64 - 100) as f32]
    }

    fn snap_rect(&self, s: WinState) -> R {
        let [x, y, w, h] = self.work_area();
        let half = (w - 8.0) / 2.0;
        match s {
            WinState::Maximized => [x, y, w, h],
            WinState::SnapLeft => [x, y, half, h],
            WinState::SnapRight => [x + half + 8.0, y, half, h],
            WinState::Normal => [x, y, w, h],
        }
    }

    fn win(&mut self, app: AppKind) -> Option<&mut Window> {
        self.windows.iter_mut().find(|w| w.app == app)
    }

    fn win_ref(&self, app: AppKind) -> Option<&Window> {
        self.windows.iter().find(|w| w.app == app)
    }

    fn open(&mut self, app: AppKind, start: u64, at: Option<R>) {
        if let Some(w) = self.win_ref(app) {
            let phase = w.phase;
            match phase {
                Phase::Minimized | Phase::Minimizing => self.restore_win(app, start),
                _ => self.focus_win(app),
            }
            return;
        }
        let (dw, dh) = app.default_size();
        let rect = at.unwrap_or([((self.w - dw) / 2) as f32, ((self.h - dh) / 2 - 20) as f32, dw as f32, dh as f32]);
        let mut layer = Layer::new(app.layer_id(), rect[2] as i32, rect[3] as i32, 14.0, true, true);
        layer.x = rect[0];
        layer.y = rect[1] + 24.0;
        layer.opacity = 0.0;
        let pos = self.comp.layers.iter().position(|l| OVERLAYS.contains(&l.id)).unwrap_or(self.comp.layers.len());
        self.comp.layers.insert(pos, layer);
        let from = [rect[0], rect[1] + 24.0, rect[2], rect[3]];
        self.windows.push(Window {
            app,
            rect: from,
            state: WinState::Normal,
            restore: rect,
            geom: Some((from, rect, Tween::new(0.0, 1.0, start, 320, ease_out_cubic))),
            fade: Tween::new(0.0, 1.0, start, 260, ease_out_cubic),
            phase: Phase::Opening,
            dirty: true,
        });
        self.focus_win(app);
    }

    fn close(&mut self, app: AppKind, now: u64) {
        if let Some(w) = self.win(app) {
            w.fade.retarget(0.0, now, 180, ease_out_cubic);
            let r = w.rect;
            w.geom = Some((r, [r[0], r[1] + 12.0, r[2], r[3]], Tween::new(0.0, 1.0, now, 180, ease_out_cubic)));
            w.phase = Phase::Closing;
        }
        self.focus_next(app);
    }

    fn minimize(&mut self, app: AppKind, now: u64) {
        let dock_y = (self.h - 90) as f32;
        if let Some(w) = self.win(app) {
            w.fade.retarget(0.0, now, 260, ease_in_out_cubic);
            let r = w.rect;
            // Richtung Dock „wegrutschen“
            w.geom = Some((r, [r[0], dock_y - r[3] * 0.3, r[2], r[3]], Tween::new(0.0, 1.0, now, 260, ease_in_out_cubic)));
            w.phase = Phase::Minimizing;
        }
        self.focus_next(app);
    }

    fn restore_win(&mut self, app: AppKind, now: u64) {
        let target = match self.win_ref(app) {
            Some(w) if w.state == WinState::Normal => w.restore,
            Some(w) => self.snap_rect(w.state),
            None => return,
        };
        if let Some(w) = self.win(app) {
            w.fade.retarget(1.0, now, 280, ease_out_cubic);
            let r = w.rect;
            w.geom = Some((r, target, Tween::new(0.0, 1.0, now, 280, ease_out_cubic)));
            w.phase = Phase::Restoring;
        }
        self.focus_win(app);
    }

    fn toggle_maximize(&mut self, app: AppKind, now: u64) {
        let Some(w) = self.win_ref(app) else { return };
        let (state, rect, restore) = (w.state, w.rect, w.restore);
        let (new_state, target) = if state == WinState::Normal {
            (WinState::Maximized, self.snap_rect(WinState::Maximized))
        } else {
            (WinState::Normal, restore)
        };
        if let Some(w) = self.win(app) {
            if state == WinState::Normal {
                w.restore = rect;
            }
            w.state = new_state;
            w.geom = Some((rect, target, Tween::new(0.0, 1.0, now, 260, ease_in_out_cubic)));
        }
    }

    fn focus_win(&mut self, app: AppKind) {
        let old = self.focus;
        self.focus = Some(app);
        self.comp.raise(app.layer_id(), &OVERLAYS);
        for a in [old, Some(app)].into_iter().flatten() {
            if let Some(w) = self.win(a) {
                w.dirty = true;
            }
        }
        self.chrome_dirty = true;
    }

    /// Nächstes sichtbares Fenster (von oben) fokussieren
    fn focus_next(&mut self, except: AppKind) {
        let next = self
            .comp
            .layers
            .iter()
            .rev()
            .filter_map(|l| AppKind::ALL.iter().find(|a| a.layer_id() == l.id))
            .copied()
            .find(|a| *a != except && self.win_ref(*a).is_some_and(|w| matches!(w.phase, Phase::Open | Phase::Opening | Phase::Restoring)));
        match next {
            Some(a) => self.focus_win(a),
            None => {
                self.focus = None;
                self.chrome_dirty = true;
            }
        }
        if let Some(w) = self.win(except) {
            w.dirty = true;
        }
    }

    /// Oberstes sichtbares Fenster unter dem Mauszeiger (inkl. Greifrand)
    fn window_at(&self, x: i32, y: i32) -> Option<AppKind> {
        self.comp.layers.iter().rev().find_map(|l| {
            let app = *AppKind::ALL.iter().find(|a| a.layer_id() == l.id)?;
            let w = self.win_ref(app)?;
            if !matches!(w.phase, Phase::Open | Phase::Opening | Phase::Restoring) {
                return None;
            }
            let r = l.rect();
            let inside = x >= r.x - EDGE && y >= r.y - EDGE && x < r.x + r.w + EDGE && y < r.y + r.h + EDGE;
            inside.then_some(app)
        })
    }

    fn edges_at(&self, app: AppKind, x: i32, y: i32) -> u8 {
        let Some(w) = self.win_ref(app) else { return 0 };
        let [rx, ry, rw, rh] = w.rect;
        let (x, y) = (x as f32, y as f32);
        let e = EDGE as f32;
        let corner = 14.0;
        let mut edges = 0;
        if x < rx + e {
            edges |= LEFT;
        }
        if x > rx + rw - e {
            edges |= RIGHT;
        }
        if y < ry + e {
            edges |= TOP;
        }
        if y > ry + rh - e {
            edges |= BOTTOM;
        }
        // Ecken etwas großzügiger
        if edges & (TOP | BOTTOM) != 0 && (x < rx + corner) {
            edges |= LEFT;
        }
        if edges & (TOP | BOTTOM) != 0 && (x > rx + rw - corner) {
            edges |= RIGHT;
        }
        if edges & (LEFT | RIGHT) != 0 && (y > ry + rh - corner) {
            edges |= BOTTOM;
        }
        edges
    }

    /// Welcher Fensterknopf (1 = schließen, 2 = minimieren, 3 = maximieren)?
    fn dot_at(&self, app: AppKind, x: i32, y: i32) -> u8 {
        let Some(w) = self.win_ref(app) else { return 0 };
        let (lx, ly) = (x as f32 - w.rect[0], y as f32 - w.rect[1]);
        for k in 0..3 {
            let (cx, cy) = (22.0 + k as f32 * 20.0, 20.0);
            if (lx - cx) * (lx - cx) + (ly - cy) * (ly - cy) <= 81.0 {
                return k + 1;
            }
        }
        0
    }

    fn dock_rect(&self) -> R {
        self.comp.layers.iter().find(|l| l.id == DOCK).map(|l| [l.x, l.y, l.w as f32, l.h as f32]).unwrap_or([0.0; 4])
    }

    fn dock_icon_at(&self, x: i32, y: i32) -> Option<usize> {
        let [dx, dy, _, dh] = self.dock_rect();
        let (lx, ly) = (x as f32 - dx, y as f32 - dy);
        if ly < 0.0 || ly > dh {
            return None;
        }
        (0..AppKind::ALL.len()).find(|&i| {
            let ix = DOCK_PAD + i as f32 * (DOCK_ICON + DOCK_GAP);
            lx >= ix - DOCK_GAP / 2.0 && lx < ix + DOCK_ICON + DOCK_GAP / 2.0
        })
    }

    // -----------------------------------------------------------------------
    // Eingaben
    // -----------------------------------------------------------------------

    fn handle_input(&mut self, now: u64) {
        while let Some(byte) = KEYBOARD_BYTES.pop() {
            if let Ok(Some(ev)) = self.keyboard.add_byte(byte) {
                if matches!(ev.code, KeyCode::LControl | KeyCode::RControl) {
                    self.ctrl = ev.state == KeyState::Down;
                }
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
                self.on_move(now);
                if released & 1 != 0 {
                    self.on_release(now);
                }
                if p.wheel != 0 && self.window_at(self.mx, self.my) == Some(AppKind::Settings) {
                    let n = ACCENTS.len() as i32;
                    self.set_accent((self.accent_idx as i32 + p.wheel.signum()).rem_euclid(n) as usize, now);
                }
            }
        }
    }

    fn spawn_ripple(&mut self, now: u64) {
        let id = RIPPLE_BASE + self.next_ripple % 50;
        self.next_ripple = self.next_ripple.wrapping_add(1);
        self.comp.remove(id);
        let mut l = Layer::new(id, RIPPLE_SIZE, RIPPLE_SIZE, 0.0, false, false);
        l.x = (self.mx - RIPPLE_SIZE / 2) as f32;
        l.y = (self.my - RIPPLE_SIZE / 2) as f32;
        let pos = self.comp.index_of(CURSOR).unwrap_or(self.comp.layers.len());
        self.comp.layers.insert(pos, l);
        self.ripples.push(Ripple { id, start: now });
    }

    fn on_press(&mut self, now: u64) {
        let (x, y) = (self.mx, self.my);
        // Dock hat Vorrang (liegt über den Fenstern)
        if let Some(i) = self.dock_icon_at(x, y) {
            self.spawn_ripple(now);
            let app = AppKind::ALL[i];
            match self.win_ref(app).map(|w| w.phase) {
                None => self.open(app, now, None),
                Some(Phase::Minimized | Phase::Minimizing) => self.restore_win(app, now),
                Some(_) if self.focus == Some(app) => self.minimize(app, now),
                Some(_) => self.focus_win(app),
            }
            return;
        }
        let Some(app) = self.window_at(x, y) else {
            self.spawn_ripple(now);
            return;
        };
        self.focus_win(app);
        let edges = self.edges_at(app, x, y);
        let dot = self.dot_at(app, x, y);
        let Some(w) = self.win_ref(app) else { return };
        let r = w.rect;
        let (lx, ly) = (x as f32 - r[0], y as f32 - r[1]);
        if edges != 0 && w.state == WinState::Normal {
            self.grab = Grab::Resize { app, edges, start: r, mx: x, my: y };
        } else if dot != 0 {
            self.grab = Grab::Button { app, which: dot };
        } else if ly < TITLE_H {
            self.grab = Grab::Move { app, dx: lx, dy: ly };
        } else {
            self.spawn_ripple(now);
            self.click_app(app, lx, ly, now);
        }
    }

    fn on_move(&mut self, now: u64) {
        let (x, y) = (self.mx, self.my);
        match self.grab {
            Grab::Move { app, dx, dy } => {
                let Some(w) = self.win_ref(app) else { return };
                let (state, rect, restore) = (w.state, w.rect, w.restore);
                let (mut dx, mut dy) = (dx, dy);
                if state != WinState::Normal {
                    // Angedocktes Fenster losreißen: alte Größe, Maus bleibt relativ an gleicher Stelle
                    let ratio = dx / rect[2];
                    dx = restore[2] * ratio;
                    dy = dy.min(TITLE_H - 4.0);
                    if let Some(w) = self.win(app) {
                        w.state = WinState::Normal;
                        w.rect = [x as f32 - dx, y as f32 - dy, restore[2], restore[3]];
                        w.geom = None;
                    }
                    self.grab = Grab::Move { app, dx, dy };
                }
                let ny = (y as f32 - dy).max(52.0);
                if let Some(w) = self.win(app) {
                    w.rect[0] = x as f32 - dx;
                    w.rect[1] = ny;
                    w.restore[0] = w.rect[0];
                    w.restore[1] = w.rect[1];
                }
                // Andock-Ziel: Maus am linken/rechten Rand oder oben
                let target = if x <= 2 {
                    Some(WinState::SnapLeft)
                } else if x >= self.w - 3 {
                    Some(WinState::SnapRight)
                } else if y <= 2 {
                    Some(WinState::Maximized)
                } else {
                    None
                };
                if target != self.snap_target {
                    self.snap_target = target;
                    if let Some(t) = target {
                        let [px, py, pw, ph] = self.snap_rect(t);
                        let p = self.comp.palette;
                        if let Some(l) = self.comp.layer(PREVIEW) {
                            l.resize(pw as i32, ph as i32);
                            l.content.clear();
                            l.content.fill_rounded(0.0, 0.0, pw, ph, 16.0, p.accent.with_alpha(50));
                            l.content.stroke_rounded(1.0, 1.0, pw - 2.0, ph - 2.0, 15.0, 2.0, p.accent.with_alpha(170));
                        }
                        self.comp.set_geometry(PREVIEW, px, py, 0.0);
                        self.comp.damage_layer(PREVIEW);
                        self.preview_fade = Tween::new(0.0, 1.0, now, 160, ease_out_cubic);
                    } else {
                        self.preview_fade.retarget(0.0, now, 120, ease_out_cubic);
                    }
                }
            }
            Grab::Resize { app, edges, start, mx, my } => {
                let (ddx, ddy) = ((x - mx) as f32, (y - my) as f32);
                let (minw, minh) = app.min_size();
                let (minw, minh) = (minw as f32, minh as f32);
                let mut r = start;
                if edges & RIGHT != 0 {
                    r[2] = (start[2] + ddx).max(minw);
                }
                if edges & BOTTOM != 0 {
                    r[3] = (start[3] + ddy).max(minh);
                }
                if edges & LEFT != 0 {
                    let w = (start[2] - ddx).max(minw);
                    r[0] = start[0] + start[2] - w;
                    r[2] = w;
                }
                if edges & TOP != 0 {
                    let h = (start[3] - ddy).max(minh);
                    r[1] = (start[1] + start[3] - h).max(52.0);
                    r[3] = start[1] + start[3] - r[1];
                }
                if let Some(w) = self.win(app) {
                    w.rect = r;
                    w.restore = r;
                }
            }
            _ => {}
        }
        self.update_hover();
    }

    fn on_release(&mut self, now: u64) {
        match self.grab {
            Grab::Move { app, .. } => {
                if let Some(t) = self.snap_target.take() {
                    let target = self.snap_rect(t);
                    if let Some(w) = self.win(app) {
                        w.state = t;
                        w.geom = Some((w.rect, target, Tween::new(0.0, 1.0, now, 240, ease_out_cubic)));
                    }
                    self.preview_fade.retarget(0.0, now, 200, ease_out_cubic);
                }
            }
            Grab::Button { app, which } => {
                // Nur auslösen, wenn die Maus noch über demselben Knopf ist
                if self.window_at(self.mx, self.my) == Some(app) && self.dot_at(app, self.mx, self.my) == which {
                    match which {
                        1 => self.close(app, now),
                        2 => self.minimize(app, now),
                        _ => self.toggle_maximize(app, now),
                    }
                }
            }
            _ => {}
        }
        self.grab = Grab::None;
        self.update_hover();
    }

    /// Hover-Effekte: Symbole in den Fensterknöpfen, Tooltip im Dock, Mauszeiger-Form
    fn update_hover(&mut self) {
        let (x, y) = (self.mx, self.my);
        let icon = if self.grab == Grab::None { self.dock_icon_at(x, y) } else { None };
        if icon != self.hover_icon {
            self.hover_icon = icon;
            self.chrome_dirty = true;
        }
        let win = if icon.is_none() { self.window_at(x, y) } else { None };
        let dots = win.filter(|&a| {
            let w = self.win_ref(a).unwrap();
            let (lx, ly) = (x as f32 - w.rect[0], y as f32 - w.rect[1]);
            (10.0..76.0).contains(&lx) && (6.0..34.0).contains(&ly)
        });
        if dots != self.hover_dots {
            for a in [self.hover_dots, dots].into_iter().flatten() {
                if let Some(w) = self.win(a) {
                    w.dirty = true;
                }
            }
            self.hover_dots = dots;
        }
        let edges = match self.grab {
            Grab::Resize { edges, .. } => edges,
            Grab::None => win.filter(|&a| self.win_ref(a).is_some_and(|w| w.state == WinState::Normal)).map(|a| self.edges_at(a, x, y)).unwrap_or(0),
            _ => 0,
        };
        let kind = match edges {
            0 => CursorKind::Arrow,
            e if e == LEFT || e == RIGHT => CursorKind::ResizeH,
            e if e == TOP || e == BOTTOM => CursorKind::ResizeV,
            e if e == LEFT | TOP || e == RIGHT | BOTTOM => CursorKind::ResizeNwse,
            _ => CursorKind::ResizeNesw,
        };
        if kind != self.cursor_kind {
            self.cursor_kind = kind;
            if let Some(l) = self.comp.layer(CURSOR) {
                l.content.clear();
                draw_cursor(&mut l.content, kind);
            }
            self.comp.damage_layer(CURSOR);
        }
    }

    fn click_app(&mut self, app: AppKind, x: f32, y: f32, now: u64) {
        if app != AppKind::Settings {
            return;
        }
        let w = self.win_ref(app).map(|w| w.rect[2]).unwrap_or(0.0);
        let (sx, sy, sw, sh) = apps::settings_toggle_rect(w);
        if x >= sx - 4.0 && x <= sx + sw + 4.0 && y >= sy - 4.0 && y <= sy + sh + 4.0 {
            self.toggle_theme(now);
            return;
        }
        for i in 0..ACCENTS.len() {
            let (cx, cy) = apps::settings_swatch_center(i);
            if (x - cx).abs() <= 18.0 && (y - cy).abs() <= 18.0 {
                self.set_accent(i, now);
            }
        }
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

    fn accent(&self, now: u64) -> Rgba {
        self.accent_from.lerp(Rgba::hex(ACCENTS[self.accent_idx].1), self.accent_t.value(now))
    }

    fn on_key(&mut self, key: DecodedKey, now: u64) {
        // Tastenkürzel für alle Fenster
        match key {
            DecodedKey::RawKey(KeyCode::F2) => return self.toggle_theme(now),
            DecodedKey::RawKey(KeyCode::F11) => {
                if let Some(a) = self.focus {
                    self.toggle_maximize(a, now);
                }
                return;
            }
            DecodedKey::Unicode('w' | 'W') if self.ctrl => {
                if let Some(a) = self.focus {
                    self.close(a, now);
                }
                return;
            }
            DecodedKey::Unicode('m' | 'M') if self.ctrl => {
                if let Some(a) = self.focus {
                    self.minimize(a, now);
                }
                return;
            }
            _ => {}
        }
        // Alles andere geht an das fokussierte Fenster – hier nur Notizen
        if self.focus != Some(AppKind::Notes) {
            return;
        }
        let n = &mut self.notes;
        match key {
            DecodedKey::Unicode('\u{8}') => n.backspace(),
            DecodedKey::Unicode('\u{7f}') => n.delete(),
            DecodedKey::Unicode('\u{1b}') => {}
            DecodedKey::Unicode('\t') => (0..4).for_each(|_| n.insert(' ')),
            DecodedKey::Unicode(ch) => n.insert(ch),
            DecodedKey::RawKey(KeyCode::ArrowLeft) => n.left(),
            DecodedKey::RawKey(KeyCode::ArrowRight) => n.right(),
            DecodedKey::RawKey(KeyCode::Home) => n.home(),
            DecodedKey::RawKey(KeyCode::End) => n.end(),
            _ => return,
        }
        self.shown_caret = true; // Cursor beim Tippen sichtbar halten
        if let Some(w) = self.win(AppKind::Notes) {
            w.dirty = true;
        }
    }

    // -----------------------------------------------------------------------
    // Pro Bild
    // -----------------------------------------------------------------------

    fn update(&mut self, now: u64) {
        let t = time::now();
        if t.second != self.shown_second {
            self.shown_second = t.second;
            self.chrome_dirty = true;
            for w in &mut self.windows {
                if matches!(w.app, AppKind::Clock | AppKind::Settings) {
                    w.dirty = true;
                }
            }
        }
        let caret = (now / 530) % 2 == 0;
        if caret != self.shown_caret {
            self.shown_caret = caret;
            if let Some(w) = self.win(AppKind::Notes) {
                w.dirty = true;
            }
        }
        // Leistung: 10-mal pro Sekunde reicht für das Diagramm
        if now / 100 != self.monitor_tick {
            self.monitor_tick = now / 100;
            if let Some(w) = self.win(AppKind::Monitor) {
                w.dirty = true;
            }
        }

        // Theme/Akzent-Animation
        let theme_anim = self.light.running(now);
        if theme_anim || self.accent_t.running(now) {
            let light = self.light.value(now);
            self.comp.palette = theme::palette(light, self.accent(now));
            self.chrome_dirty = true;
            self.windows.iter_mut().for_each(|w| w.dirty = true);
            if theme_anim || self.comp.light != light {
                self.comp.light = light;
                self.comp.damage_all();
            }
        }

        // Einflug von Menüleiste und Dock
        self.intro.retain(|(id, x, y, tw)| {
            let v = tw.value(now);
            let dy = if *id == TOPBAR { -50.0 } else { 60.0 };
            self.comp.set_geometry(*id, *x, *y + dy * (1.0 - v), v);
            tw.running(now)
        });

        // Andock-Vorschau ein-/ausblenden
        if let Some(l) = self.comp.layers.iter().find(|l| l.id == PREVIEW) {
            let (x, y) = (l.x, l.y);
            self.comp.set_geometry(PREVIEW, x, y, self.preview_fade.value(now) * 0.9);
        }

        // Fenster: Animationen fortschreiben, Ebenen anpassen
        let mut removed = Vec::new();
        for i in 0..self.windows.len() {
            let w = &mut self.windows[i];
            if let Some((from, to, tw)) = w.geom {
                let k = tw.value(now);
                for j in 0..4 {
                    w.rect[j] = from[j] + (to[j] - from[j]) * k;
                }
                if !tw.running(now) {
                    w.rect = to;
                    w.geom = None;
                }
            }
            let fading = w.fade.running(now);
            if !fading {
                w.phase = match w.phase {
                    Phase::Opening | Phase::Restoring => Phase::Open,
                    Phase::Minimizing => Phase::Minimized,
                    Phase::Closing => {
                        removed.push(w.app);
                        Phase::Closing
                    }
                    p => p,
                };
            }
            let (app, r, op) = (w.app, w.rect, w.fade.value(now));
            let resized = self.comp.set_rect(app.layer_id(), r[0], r[1], r[2] as i32, r[3] as i32, op);
            if resized {
                self.windows[i].dirty = true;
            }
        }
        for app in removed {
            self.windows.retain(|w| w.app != app);
            self.comp.remove(app.layer_id());
            self.chrome_dirty = true;
        }

        // Klick-Wellen
        let accent = self.comp.palette.accent;
        let mut done = Vec::new();
        for r in &self.ripples {
            let p = ((now - r.start) as f32 / RIPPLE_MS as f32).min(1.0);
            if let Some(l) = self.comp.layer(r.id) {
                l.content.clear();
                let c = RIPPLE_SIZE as f32 / 2.0;
                l.content.ring(c, c, 4.0 + ease_out_cubic(p) * (c - 6.0), 2.5, accent.with_alpha((230.0 * (1.0 - p)) as u8));
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

        // Mauszeiger (Resize-Pfeile haben ihren „Hotspot“ in der Mitte)
        let (ox, oy) = if self.cursor_kind == CursorKind::Arrow { (0, 0) } else { (12, 12) };
        self.comp.set_geometry(CURSOR, (self.mx - ox) as f32, (self.my - oy) as f32, 1.0);

        // Inhalte neu rendern
        let p = self.comp.palette;
        let heap = allocator::stats();
        for i in 0..self.windows.len() {
            if self.windows[i].dirty {
                self.windows[i].dirty = false;
                self.render_window(i, &p, now, heap);
            }
        }
        if self.chrome_dirty {
            self.chrome_dirty = false;
            self.render_topbar(&p);
            self.render_dock(&p, now);
        }
    }

    fn render_window(&mut self, i: usize, p: &Palette, now: u64, heap: (usize, usize)) {
        let app = self.windows[i].app;
        let id = app.layer_id();
        let Some(l) = self.comp.layer(id) else { return };
        let mut img = core::mem::replace(&mut l.content, Image::new(1, 1));
        img.clear();
        let focused = self.focus == Some(app);

        // Titelleiste: drei Punkte links, Titel in der Mitte
        let w = img.w as f32;
        let colors = [0xFF5F57, 0xFEBC2E, 0x28C840];
        for (k, c) in colors.iter().enumerate() {
            let cx = 22.0 + k as f32 * 20.0;
            let col = if focused || self.hover_dots == Some(app) { Rgba::hex(*c) } else { p.control };
            img.circle(cx, 20.0, 6.0, col);
            if self.hover_dots == Some(app) {
                let dark = Rgba::hex(0x000000).with_alpha(150);
                match k {
                    0 => {
                        img.line(cx - 2.5, 17.5, cx + 2.5, 22.5, 1.3, dark);
                        img.line(cx + 2.5, 17.5, cx - 2.5, 22.5, 1.3, dark);
                    }
                    1 => img.line(cx - 3.0, 20.0, cx + 3.0, 20.0, 1.4, dark),
                    _ => {
                        img.line(cx - 3.0, 20.0, cx + 3.0, 20.0, 1.3, dark);
                        img.line(cx, 17.0, cx, 23.0, 1.3, dark);
                    }
                }
            }
        }
        let title_col = if focused { p.text } else { p.text_muted };
        img.text_centered(w / 2.0, 25.0, app.title(), 13.0, Weight::SemiBold, title_col);
        img.line(0.0, TITLE_H - 0.5, w, TITLE_H - 0.5, 1.0, p.well_border);

        let ctx = Ctx {
            p,
            dark_knob: 1.0 - self.light.value(now),
            accent_idx: self.accent_idx,
            fps: self.fps,
            frame_times: &self.frame_times,
            caret_on: self.shown_caret,
            focused,
            notes: &self.notes,
            heap,
        };
        apps::draw(app, &mut img, &ctx);
        if let Some(l) = self.comp.layer(id) {
            l.content = img;
        }
        self.comp.damage_layer(id);
    }

    fn render_topbar(&mut self, p: &Palette) {
        let focus = self.focus;
        let fps = self.fps;
        let Some(l) = self.comp.layer(TOPBAR) else { return };
        let img = &mut l.content;
        img.clear();
        let w = img.w as f32;
        img.circle(22.0, 20.0, 5.0, p.accent);
        let tw = img.text(36.0, 25.0, "AuroraOS", 14.0, Weight::SemiBold, p.text);
        if let Some(a) = focus {
            img.text(36.0 + tw + 18.0, 25.0, a.title(), 14.0, Weight::Regular, p.text_muted);
        }
        let t = time::now();
        let center = format!(
            "{}, {}. {}   {:02}:{:02}",
            &time::WEEKDAYS[t.weekday as usize][..2],
            t.day,
            time::MONTHS[t.month as usize - 1],
            t.hour,
            t.minute
        );
        img.text_centered(w / 2.0, 25.0, &center, 14.0, Weight::SemiBold, p.text);
        let right = format!("F2 Hell/Dunkel  ·  {} FPS", fps);
        let rw = font::measure(&right, 13.0, Weight::Regular);
        img.text(w - 22.0 - rw, 25.0, &right, 13.0, Weight::Regular, p.text_muted);
        self.comp.damage_layer(TOPBAR);
    }

    fn render_dock(&mut self, p: &Palette, now: u64) {
        let open: Vec<(AppKind, bool)> = self.windows.iter().map(|w| (w.app, w.phase == Phase::Minimized)).collect();
        let hover = self.hover_icon;
        let Some(l) = self.comp.layer(DOCK) else { return };
        let img = &mut l.content;
        img.clear();
        for (i, app) in AppKind::ALL.iter().enumerate() {
            let x = DOCK_PAD + i as f32 * (DOCK_ICON + DOCK_GAP);
            let lift = if hover == Some(i) { 5.0 } else { 0.0 };
            apps::draw_icon(*app, img, x, 10.0 - lift, DOCK_ICON);
            // Punkt unter geöffneten Apps
            if let Some((_, minimized)) = open.iter().find(|(a, _)| a == app) {
                let c = if *minimized { p.text_faint } else { p.text };
                img.circle(x + DOCK_ICON / 2.0, 67.0, 2.5, c);
            }
        }
        self.comp.damage_layer(DOCK);

        // Tooltip über dem Symbol
        let [dx, dy, _, _] = self.dock_rect();
        match hover {
            Some(i) => {
                let name = AppKind::ALL[i].title();
                let tw = font::measure(name, 13.0, Weight::SemiBold) + 28.0;
                let cx = dx + DOCK_PAD + i as f32 * (DOCK_ICON + DOCK_GAP) + DOCK_ICON / 2.0;
                if let Some(l) = self.comp.layer(TOOLTIP) {
                    l.resize(tw as i32, 30);
                    l.content.clear();
                    l.content.text_centered(tw / 2.0, 20.0, name, 13.0, Weight::SemiBold, p.text);
                }
                self.comp.damage_layer(TOOLTIP);
                self.comp.set_geometry(TOOLTIP, cx - tw / 2.0, dy - 40.0, 1.0);
            }
            None => {
                if let Some(l) = self.comp.layers.iter().find(|l| l.id == TOOLTIP) {
                    let (x, y) = (l.x, l.y);
                    self.comp.set_geometry(TOOLTIP, x, y, 0.0);
                }
            }
        }
        let _ = now;
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
            if now >= start + frame * 1000 / 60 {
                let t0 = time::rdtsc();
                self.update(now);
                let pixels = self.comp.compose();
                let ms = time::micros_since(t0) as f32 / 1000.0;
                // Nur Bilder, in denen wirklich etwas gezeichnet wurde
                if pixels > 0 {
                    self.frame_times.push_back(ms);
                    if self.frame_times.len() > 100 {
                        self.frame_times.pop_front();
                    }
                }
                self.frames_in_second += 1;
                if now - self.second_start >= 1000 {
                    self.fps = self.frames_in_second;
                    self.frames_in_second = 0;
                    self.second_start = now;
                    self.chrome_dirty = true;
                    crate::serial_println!(
                        "[aurora] {} FPS, Bildzeit {:.2} ms, {} Pixel, {} Fenster, {} Zeichen im Cache, IRQs {}/{}",
                        self.fps,
                        ms,
                        self.comp.last_pixels,
                        self.windows.len(),
                        font::cached_glyphs(),
                        KEYBOARD_IRQS.load(Ordering::Relaxed),
                        MOUSE_IRQS.load(Ordering::Relaxed)
                    );
                }
                frame += 1;
                if time::ticks() > start + frame * 1000 / 60 + 50 {
                    frame = (time::ticks() - start) * 60 / 1000;
                }
            }
            x86_64::instructions::interrupts::enable_and_hlt();
        }
    }
}

/// Mauszeiger: Pfeil oder Doppelpfeil zum Ändern der Größe
fn draw_cursor(img: &mut Image, kind: CursorKind) {
    const ARROW: [&str; 19] = [
        "X", "XX", "X.X", "X..X", "X...X", "X....X", "X.....X", "X......X", "X.......X", "X........X", "X.........X",
        "X..........X", "X......XXXXX", "X...X..X", "X..XX..X", "X.X  X..X", "XX   X..X", "X     X..X", "      XXX",
    ];
    let dark = Rgba::hex(0x0B1020);
    let white = Rgba::hex(0xFFFFFF);
    if kind == CursorKind::Arrow {
        for pass in 0..2 {
            for (row, line) in ARROW.iter().enumerate() {
                for (col, ch) in line.chars().enumerate() {
                    match (pass, ch) {
                        (0, 'X' | '.') => img.blend(col as i32 + 1, row as i32 + 2, Rgba::hex(0x000000), 0.3),
                        (1, 'X') => img.blend(col as i32, row as i32, dark, 1.0),
                        (1, '.') => img.blend(col as i32, row as i32, white, 1.0),
                        _ => {}
                    }
                }
            }
        }
        return;
    }
    // Doppelpfeil durch die Mitte (12, 12)
    let (dx, dy): (f32, f32) = match kind {
        CursorKind::ResizeH => (1.0, 0.0),
        CursorKind::ResizeV => (0.0, 1.0),
        CursorKind::ResizeNwse => (0.707, 0.707),
        _ => (0.707, -0.707),
    };
    let (c, len, head) = (12.0, 8.5, 4.0);
    let (ax, ay, bx, by) = (c - dx * len, c - dy * len, c + dx * len, c + dy * len);
    for (lw, col) in [(4.0, dark), (1.8, white)] {
        img.line(ax, ay, bx, by, lw, col);
        // Pfeilspitzen: zwei kurze Linien im 45°-Winkel an jedem Ende
        for (tx, ty, s) in [(ax, ay, 1.0), (bx, by, -1.0)] {
            let (ux, uy) = (dx * s, dy * s);
            img.line(tx, ty, tx + (ux - uy) * head, ty + (uy + ux) * head, lw, col);
            img.line(tx, ty, tx + (ux + uy) * head, ty + (uy - ux) * head, lw, col);
        }
    }
}

