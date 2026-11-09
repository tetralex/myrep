//! Farbschema: Dunkel und Hell, dazu eine frei wählbare Akzentfarbe.
//! Beim Umschalten wird zwischen beiden Paletten weich überblendet.

use crate::paint::Rgba;

/// Auswahl an Akzentfarben (Name, Farbe)
pub const ACCENTS: [(&str, u32); 6] = [
    ("Türkis", 0x2DD4BF),
    ("Violett", 0xA78BFA),
    ("Blau", 0x60A5FA),
    ("Grün", 0x4ADE80),
    ("Orange", 0xFB923C),
    ("Rosé", 0xFB7185),
];

#[derive(Clone, Copy)]
pub struct Palette {
    pub text: Rgba,
    pub text_muted: Rgba,
    pub text_faint: Rgba,
    pub accent: Rgba,
    /// Tönung über dem verschwommenen Hintergrund der Glaskarten
    pub glass_tint: Rgba,
    /// Lichtkante der Karten
    pub border: Rgba,
    pub shadow_alpha: f32,
    /// Mulden wie das Textfeld
    pub well: Rgba,
    pub well_border: Rgba,
    pub control: Rgba,
}

const DARK: Palette = Palette {
    text: Rgba::hex(0xF1F5F9),
    text_muted: Rgba::hex(0x94A3B8),
    text_faint: Rgba::hex(0x64748B),
    accent: Rgba::hex(0x2DD4BF),
    glass_tint: Rgba::hex(0x0F172A).with_alpha(120),
    border: Rgba::hex(0xFFFFFF).with_alpha(46),
    shadow_alpha: 0.55,
    well: Rgba::hex(0x000000).with_alpha(80),
    well_border: Rgba::hex(0xFFFFFF).with_alpha(22),
    control: Rgba::hex(0xFFFFFF).with_alpha(36),
};

const LIGHT: Palette = Palette {
    text: Rgba::hex(0x0F172A),
    text_muted: Rgba::hex(0x475569),
    text_faint: Rgba::hex(0x94A3B8),
    accent: Rgba::hex(0x0D9488),
    glass_tint: Rgba::hex(0xFFFFFF).with_alpha(150),
    border: Rgba::hex(0xFFFFFF).with_alpha(170),
    shadow_alpha: 0.22,
    well: Rgba::hex(0xFFFFFF).with_alpha(150),
    well_border: Rgba::hex(0x0F172A).with_alpha(22),
    control: Rgba::hex(0x0F172A).with_alpha(28),
};

/// `light`: 0.0 = dunkel … 1.0 = hell; `accent`: gewählte Akzentfarbe
pub fn palette(light: f32, accent: Rgba) -> Palette {
    let l = |a: Rgba, b: Rgba| a.lerp(b, light);
    // Im hellen Modus wird der Akzent etwas abgedunkelt, damit Text darauf lesbar bleibt
    let accent = accent.lerp(Rgba::hex(0x000000), 0.18 * light);
    Palette {
        text: l(DARK.text, LIGHT.text),
        text_muted: l(DARK.text_muted, LIGHT.text_muted),
        text_faint: l(DARK.text_faint, LIGHT.text_faint),
        accent,
        glass_tint: l(DARK.glass_tint, LIGHT.glass_tint),
        border: l(DARK.border, LIGHT.border),
        shadow_alpha: DARK.shadow_alpha + (LIGHT.shadow_alpha - DARK.shadow_alpha) * light,
        well: l(DARK.well, LIGHT.well),
        well_border: l(DARK.well_border, LIGHT.well_border),
        control: l(DARK.control, LIGHT.control),
    }
}
