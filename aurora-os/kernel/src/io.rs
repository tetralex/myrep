//! Zugriff auf I/O-Ports (`in`/`out`-Befehle) – so spricht man auf x86
//! mit älteren Geräten wie PS/2-Controller, PIT oder serieller Schnittstelle.

use core::arch::asm;

pub unsafe fn outb(port: u16, value: u8) {
    unsafe { asm!("out dx, al", in("dx") port, in("al") value, options(nomem, nostack, preserves_flags)) };
}

pub unsafe fn inb(port: u16) -> u8 {
    let value: u8;
    unsafe { asm!("in al, dx", out("al") value, in("dx") port, options(nomem, nostack, preserves_flags)) };
    value
}
