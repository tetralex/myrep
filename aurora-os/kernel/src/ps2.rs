//! PS/2-Controller (Intel 8042) mit Tastatur und Maus.
//! Port 0x60 = Daten, Port 0x64 = Status (lesen) / Befehl (schreiben).

use crate::io::{inb, outb};
use crate::serial_println;

const DATA: u16 = 0x60;
const CMD: u16 = 0x64;

fn wait_write() -> bool {
    // Status-Bit 1: Eingabepuffer des Controllers noch voll -> warten
    (0..100_000).any(|_| unsafe { inb(CMD) } & 0x02 == 0)
}

fn wait_read() -> bool {
    // Status-Bit 0: Ausgabepuffer hat ein Byte für uns
    (0..100_000).any(|_| unsafe { inb(CMD) } & 0x01 != 0)
}

fn command(c: u8) {
    wait_write();
    unsafe { outb(CMD, c) };
}

fn write_data(b: u8) {
    wait_write();
    unsafe { outb(DATA, b) };
}

fn read_data() -> Option<u8> {
    wait_read().then(|| unsafe { inb(DATA) })
}

/// Befehl an die Maus: 0xD4 sagt dem Controller „das nächste Byte ist für Port 2“
fn mouse_command(b: u8) -> bool {
    command(0xD4);
    write_data(b);
    read_data() == Some(0xFA) // 0xFA = „ACK“, verstanden
}

pub struct Ps2Info {
    pub mouse: bool,
    pub wheel: bool,
}

/// Läuft mit gesperrten Interrupts (nur Abfragen = „Polling“)
pub fn init() -> Ps2Info {
    command(0xAD); // Tastatur-Port aus
    command(0xA7); // Maus-Port aus
    while unsafe { inb(CMD) } & 0x01 != 0 {
        unsafe { inb(DATA) }; // alte Bytes verwerfen
    }

    // Konfigurationsbyte: Bit 0/1 = Interrupts für Port 1/2, Bit 4/5 = Takt aus,
    // Bit 6 = Übersetzung in Scancode-Satz 1 (den versteht unser Decoder)
    command(0x20);
    let mut config = read_data().unwrap_or(0);
    config |= 0b0100_0011;
    config &= !0b0011_0000;
    command(0x60);
    write_data(config);

    command(0xAE); // Tastatur-Port an
    command(0xA8); // Maus-Port an

    let mouse = mouse_command(0xF6); // Standardeinstellungen
    // „Magisches Klopfzeichen“ für das Scrollrad (IntelliMouse):
    // Abtastrate nacheinander auf 200, 100, 80 setzen, dann ID abfragen.
    // Antwortet die Maus mit ID 3, sendet sie ab jetzt 4-Byte-Pakete mit Rad.
    for rate in [200, 100, 80] {
        mouse_command(0xF3);
        mouse_command(rate);
    }
    mouse_command(0xF2);
    let wheel = read_data() == Some(3);
    let streaming = mouse_command(0xF4); // Datenstrom einschalten

    serial_println!("[aurora] PS/2: Maus {}, Scrollrad {}", mouse && streaming, wheel);
    Ps2Info { mouse: mouse && streaming, wheel }
}

/// Setzt Maus-Pakete (3 oder 4 Bytes) aus einzelnen Bytes zusammen
pub struct MouseParser {
    buf: [u8; 4],
    len: usize,
    packet: usize,
}

pub struct MousePacket {
    pub dx: i32,
    pub dy: i32,
    pub wheel: i32,
    pub buttons: u8, // Bit 0 = links, 1 = rechts, 2 = Mitte
}

impl MouseParser {
    pub const fn new(wheel: bool) -> Self {
        MouseParser { buf: [0; 4], len: 0, packet: if wheel { 4 } else { 3 } }
    }

    pub fn feed(&mut self, b: u8) -> Option<MousePacket> {
        // Byte 0 hat immer Bit 3 gesetzt – sonst sind wir aus dem Takt
        if self.len == 0 && b & 0x08 == 0 {
            return None;
        }
        self.buf[self.len] = b;
        self.len += 1;
        if self.len < self.packet {
            return None;
        }
        self.len = 0;
        let f = self.buf[0];
        if f & 0xC0 != 0 {
            return None; // Überlauf -> Paket verwerfen
        }
        // 9-Bit-Zahlen mit Vorzeichen: Vorzeichen-Bits stehen in Byte 0
        let dx = self.buf[1] as i32 - if f & 0x10 != 0 { 256 } else { 0 };
        let dy = self.buf[2] as i32 - if f & 0x20 != 0 { 256 } else { 0 };
        let wheel = if self.packet == 4 { (self.buf[3] as i8 as i32).clamp(-8, 7) } else { 0 };
        Some(MousePacket { dx, dy: -dy, wheel, buttons: f & 0x07 }) // PS/2: y zeigt nach oben
    }
}
