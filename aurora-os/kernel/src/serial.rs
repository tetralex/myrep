//! Serielle Schnittstelle COM1 – unser wichtigstes Debug-Werkzeug.
//! QEMU leitet sie mit `-serial stdio` direkt ins Terminal um.
//! Funktioniert auch dann noch, wenn die Grafik kaputt ist.

use core::fmt;

use crate::io::{inb, outb};

const COM1: u16 = 0x3F8;

/// Initialisiert COM1 mit 38400 Baud, 8N1.
pub fn init() {
    unsafe {
        outb(COM1 + 1, 0x00); // Interrupts aus
        outb(COM1 + 3, 0x80); // DLAB an (Baudrate setzen)
        outb(COM1, 0x03);     // Teiler low  -> 38400 Baud
        outb(COM1 + 1, 0x00); // Teiler high
        outb(COM1 + 3, 0x03); // 8 Bit, keine Parität, 1 Stoppbit
        outb(COM1 + 2, 0xC7); // FIFO an
        outb(COM1 + 4, 0x0B); // DTR/RTS gesetzt
    }
}

fn write_byte(byte: u8) {
    unsafe {
        // Warten, bis das Senderegister leer ist
        while inb(COM1 + 5) & 0x20 == 0 {}
        outb(COM1, byte);
    }
}

pub struct Serial;

impl fmt::Write for Serial {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        for b in s.bytes() {
            if b == b'\n' {
                write_byte(b'\r');
            }
            write_byte(b);
        }
        Ok(())
    }
}

#[macro_export]
macro_rules! serial_println {
    () => { $crate::serial_print!("\n") };
    ($($arg:tt)*) => {{
        $crate::serial_print!($($arg)*);
        $crate::serial_print!("\n");
    }};
}

#[macro_export]
macro_rules! serial_print {
    ($($arg:tt)*) => {{
        use core::fmt::Write;
        let _ = write!($crate::serial::Serial, $($arg)*);
    }};
}
