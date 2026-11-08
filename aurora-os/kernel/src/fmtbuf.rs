//! Kleiner Text-Puffer auf dem Stack – wir haben noch keinen Heap.
//! Ab Meilenstein 3 können wir stattdessen `String` benutzen.

use core::fmt;

pub struct LineBuf {
    buf: [u8; 128],
    len: usize,
}

impl LineBuf {
    pub const fn new() -> Self {
        LineBuf { buf: [0; 128], len: 0 }
    }

    pub fn as_str(&self) -> &str {
        core::str::from_utf8(&self.buf[..self.len]).unwrap_or("?")
    }
}

impl fmt::Write for LineBuf {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        // Nur ganze UTF-8-Zeichen übernehmen, damit as_str() gültig bleibt
        for ch in s.chars() {
            let mut tmp = [0u8; 4];
            let enc = ch.encode_utf8(&mut tmp).as_bytes();
            if self.len + enc.len() > self.buf.len() {
                break;
            }
            self.buf[self.len..self.len + enc.len()].copy_from_slice(enc);
            self.len += enc.len();
        }
        Ok(())
    }
}

/// `format!`-Ersatz ohne Heap: `fmt!("x = {}", 5)` liefert einen LineBuf.
#[macro_export]
macro_rules! fmt {
    ($($arg:tt)*) => {{
        use core::fmt::Write;
        let mut b = $crate::fmtbuf::LineBuf::new();
        let _ = write!(b, $($arg)*);
        b
    }};
}
