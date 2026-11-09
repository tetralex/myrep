//! Vollbild-Ansichten: Startbildschirm und Fehlerbildschirm.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::framebuffer;
use crate::gfx::{Canvas, Color};
use crate::memory::MemStats;
use crate::selftest::SelfTest;
use noto_sans_mono_bitmap::{FontWeight, RasterHeight};

// Farbpalette „Aurora Dark“
pub const ACCENT: Color = Color::hex(0x5EEAD4); // Türkis
pub const ACCENT_2: Color = Color::hex(0xA78BFA); // Violett
pub const BG_TOP: Color = Color::hex(0x0B1020);
pub const BG_BOTTOM: Color = Color::hex(0x1B1036);
pub const TEXT: Color = Color::hex(0xF1F5F9);
pub const TEXT_MUTED: Color = Color::hex(0x94A3B8);
pub const GLASS: Color = Color::hex(0xFFFFFF);
pub const OK: Color = Color::hex(0x4ADE80); // Grün
pub const DANGER: Color = Color::hex(0xFB7185); // Rosé
const DANGER_2: Color = Color::hex(0xF97316); // Orange

const R: RasterHeight = RasterHeight::Size16;
const REG: FontWeight = FontWeight::Regular;
const BOLD: FontWeight = FontWeight::Bold;

/// Halbtransparente Glaskarte mit Schatten und Lichtkante
pub fn glass_card(c: &mut Canvas, x: i32, y: i32, w: i32, h: i32) {
    c.drop_shadow(x, y, w, h, 24, 40, 12, 150);
    c.rounded_rect(x, y, w, h, 24, GLASS, 22);
    c.rounded_border(x, y, w, h, 24, GLASS, 70);
}

/// Runder Logo-Kreis mit Farbverlauf und einem Buchstaben
fn logo(c: &mut Canvas, x: i32, y: i32, size: i32, top: Color, bottom: Color, letter: &str) {
    for row in 0..size {
        let color = top.mix(bottom, (row * 256 / size) as u32);
        // Kreis Zeile für Zeile: jede Zeile ist ein 1 px hoher Ausschnitt
        c.circle_row(x, y, size, row, color);
    }
    let lw = Canvas::text_width(letter, BOLD, RasterHeight::Size32);
    c.text(x + (size - lw) / 2, y + (size - 32) / 2, letter, BOLD, RasterHeight::Size32, BG_TOP);
}

/// Unten in der Karte: Verlaufsleiste
fn accent_bar(c: &mut Canvas, x: i32, y: i32, w: i32, from: Color, to: Color) {
    for i in 0..w {
        c.rounded_rect(x + i, y, 1, 4, 0, from.mix(to, (i * 256 / w) as u32), 256);
    }
}

/// Bytes menschenlesbar, mit deutschem Dezimalkomma: „511,8 MiB“
pub fn human(bytes: u64) -> String {
    const KIB: u64 = 1024;
    const MIB: u64 = 1024 * KIB;
    const GIB: u64 = 1024 * MIB;
    let (unit, div) = match bytes {
        b if b >= GIB => ("GiB", GIB),
        b if b >= MIB => ("MiB", MIB),
        b if b >= KIB => ("KiB", KIB),
        _ => return format!("{} B", bytes),
    };
    let tenths = bytes * 10 / div;
    format!("{},{} {}", tenths / 10, tenths % 10, unit)
}

/// Alles, was der Startbildschirm anzeigt
pub struct BootReport {
    pub info: Vec<(&'static str, String)>,
    pub mem: MemStats,
    pub tests: Vec<SelfTest>,
}

const C_FREE: Color = ACCENT;
const C_KERNEL: Color = ACCENT_2;
const C_BOOT: Color = Color::hex(0x60A5FA); // Blau
const C_ACPI: Color = Color::hex(0xFBBF24); // Bernstein
const C_USED: Color = Color::hex(0xF472B6); // Pink: von uns belegt

const ROW: i32 = 21;

/// Startbildschirm mit Systeminfos, Speicheraufteilung und Selbsttests
pub fn boot_screen(r: &BootReport) {
    let Some(mut c) = framebuffer::canvas() else { return };
    let (w, h) = (c.width, c.height);
    c.aurora_background(BG_TOP, BG_BOTTOM, &[(w / 4, h / 3, w / 2, ACCENT, 70), (w * 3 / 4, h * 2 / 3, w / 2, ACCENT_2, 90)]);

    let cw = 680.min(w - 32);
    let ch = 128 + r.info.len() as i32 * ROW + 16 + 30 + 30 + 3 * ROW + 16 + 30 + r.tests.len() as i32 * ROW + 72;
    let (cx, cy) = ((w - cw) / 2, ((h - ch) / 2).max(8));
    glass_card(&mut c, cx, cy, cw, ch);

    let (lx, ly) = (cx + 40, cy + 36);
    logo(&mut c, lx, ly, 56, ACCENT, ACCENT_2, "A");
    c.text(lx + 80, ly + 2, "AuroraOS", BOLD, RasterHeight::Size32, TEXT);
    c.text(lx + 80, ly + 36, "Meilenstein 7 · Multitasking", REG, R, ACCENT);

    let mut y = cy + 128;
    for (label, value) in &r.info {
        c.text(cx + 40, y, label, REG, R, TEXT_MUTED);
        c.text(cx + 200, y, value, REG, R, TEXT);
        y += ROW;
    }

    // --- Arbeitsspeicher ---
    y += 16;
    let m = &r.mem;
    let (used_frames, _) = crate::memory::frame_stats();
    let used = used_frames * crate::memory::PAGE_SIZE;
    c.text(cx + 40, y, "Arbeitsspeicher", BOLD, R, TEXT);
    let total = format!("{} RAM", human(m.ram()));
    c.text(cx + cw - 40 - Canvas::text_width(&total, REG, R), y, &total, REG, R, TEXT_MUTED);
    y += 30;
    c.segmented_bar(
        cx + 40,
        y,
        cw - 80,
        12,
        &[(used, C_USED), (m.kernel, C_KERNEL), (m.bootloader, C_BOOT), (m.acpi, C_ACPI), (m.usable - used, C_FREE)],
    );
    y += 30;
    let legend = [
        (C_FREE, "Frei", m.usable - used),
        (C_USED, "Von AuroraOS belegt", used),
        (C_KERNEL, "Kernel", m.kernel),
        (C_BOOT, "Bootloader", m.bootloader),
        (C_ACPI, "ACPI", m.acpi),
        (Color::hex(0x64748B), "Framebuffer", m.framebuffer),
    ];
    let col_w = (cw - 80) / 2;
    for (i, (color, label, bytes)) in legend.iter().enumerate() {
        let lx = cx + 40 + (i as i32 % 2) * col_w;
        let ly = y + (i as i32 / 2) * ROW;
        c.rounded_rect(lx + 2, ly + 4, 10, 10, 3, *color, 256);
        c.text(lx + 22, ly, label, REG, R, TEXT_MUTED);
        let v = human(*bytes);
        c.text(lx + col_w - 24 - Canvas::text_width(&v, REG, R), ly, &v, REG, R, TEXT);
    }
    y += 3 * ROW + 16;

    // --- Selbsttest ---
    let passed = r.tests.iter().filter(|t| t.ok).count();
    c.text(cx + 40, y, "Selbsttest", BOLD, R, TEXT);
    let summary = format!("{} von {} bestanden", passed, r.tests.len());
    let sc = if passed == r.tests.len() { OK } else { DANGER };
    c.text(cx + cw - 40 - Canvas::text_width(&summary, REG, R), y, &summary, REG, R, sc);
    y += 30;
    for t in &r.tests {
        c.rounded_rect(cx + 42, y + 4, 10, 10, 5, if t.ok { OK } else { DANGER }, 256);
        c.text(cx + 64, y, &t.label, REG, R, TEXT);
        y += ROW;
    }

    accent_bar(&mut c, cx + 40, cy + ch - 52, cw - 80, ACCENT, ACCENT_2);
    c.text(cx + 40, cy + ch - 36, "Absturz-Tests: im Limine-Bootmenü auswählen", REG, R, TEXT_MUTED);
}

/// Fehlerbildschirm („Aurora-Screen of Death“).
/// Benutzt bewusst **keinen Heap**: Der Fehler könnte ja gerade im Heap passiert sein.
pub fn error_screen(title: &str, description: &str, rows: &[(&str, &str)]) {
    let Some(mut c) = framebuffer::canvas() else { return };
    let (w, h) = (c.width, c.height);
    c.aurora_background(
        Color::hex(0x160A14),
        Color::hex(0x0B0B14),
        &[(w / 3, h / 4, w / 2, DANGER, 60), (w * 3 / 4, h * 3 / 4, w / 2, DANGER_2, 40)],
    );

    let cw = 680.min(w - 32);
    let ch = 190 + rows.len() as i32 * 28 + 64;
    let (cx, cy) = ((w - cw) / 2, (h - ch) / 2);
    glass_card(&mut c, cx, cy, cw, ch);

    let (lx, ly) = (cx + 40, cy + 40);
    logo(&mut c, lx, ly, 56, DANGER, DANGER_2, "!");
    c.text(lx + 80, ly + 2, "Etwas ist schiefgelaufen", BOLD, RasterHeight::Size32, TEXT);
    c.text(lx + 80, ly + 36, title, BOLD, R, DANGER);

    c.text(cx + 40, cy + 124, description, REG, R, TEXT_MUTED);
    // feine Trennlinie
    c.rounded_rect(cx + 40, cy + 160, cw - 80, 1, 0, GLASS, 40);

    let mut y = cy + 180;
    // Werte, die nicht in die Karte passen, mit „…“ abschneiden
    let max_chars = ((cw - 240) / Canvas::text_width("x", REG, R)) as usize;
    for (label, value) in rows {
        c.text(cx + 40, y, label, REG, R, TEXT_MUTED);
        if value.chars().count() > max_chars {
            let cut = value.char_indices().nth(max_chars - 1).map(|(i, _)| i).unwrap_or(value.len());
            let w = c.text(cx + 200, y, &value[..cut], REG, R, TEXT);
            c.text(cx + 200 + w, y, "…", REG, R, TEXT_MUTED);
        } else {
            c.text(cx + 200, y, value, REG, R, TEXT);
        }
        y += 28;
    }

    accent_bar(&mut c, cx + 40, cy + ch - 56, cw - 80, DANGER, DANGER_2);
    c.text(cx + 40, cy + ch - 40, "System angehalten · Details auch auf COM1", REG, R, TEXT_MUTED);
}
