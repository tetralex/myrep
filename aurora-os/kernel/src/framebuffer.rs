//! Globaler Zugriff auf den Framebuffer.
//! Exception-Handler müssen jederzeit zeichnen können – auch mitten in
//! anderem Code. Deshalb speichern wir nur die (kopierbaren) Eckdaten
//! und erzeugen bei Bedarf eine neue Canvas, statt eine Sperre (Mutex)
//! zu benutzen, die im Fehlerfall vielleicht nie wieder frei wird.

use crate::gfx::Canvas;
use spin::Once;

#[derive(Clone, Copy)]
pub struct FbInfo {
    pub addr: usize,
    pub width: u64,
    pub height: u64,
    pub pitch: u64,
    pub bpp: u16,
    pub shift: (u8, u8, u8),
}

static FB: Once<FbInfo> = Once::new();

pub fn init(info: FbInfo) {
    FB.call_once(|| info);
}

pub fn info() -> Option<FbInfo> {
    FB.get().copied()
}

/// Neue Zeichenfläche über dem Bildschirm.
/// Hinweis: Mehrere Canvases zeigen auf denselben Speicher. Das ist ok,
/// solange nur ein CPU-Kern zeichnet. Ab Meilenstein 5 (Compositor)
/// gibt es genau einen Besitzer des Bildschirms.
pub fn canvas() -> Option<Canvas> {
    let fb = FB.get()?;
    Some(unsafe { Canvas::new(fb.addr as *mut u32, fb.width, fb.height, fb.pitch, fb.shift) })
}
