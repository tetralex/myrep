//! APIC – der moderne Interrupt-Controller.
//!
//! * **Local APIC**: einer pro CPU-Kern. Hat einen eingebauten Timer und
//!   nimmt das „End of Interrupt“ (EOI) entgegen.
//! * **I/O APIC**: verteilt Geräte-Interrupts (Tastatur, Maus …) an die Kerne.
//! * Der alte **8259 PIC** aus den 80ern muss dafür abgeschaltet werden.

use core::sync::atomic::{AtomicU64, Ordering};

use crate::acpi::Madt;
use crate::io::{inb, outb};
use crate::{memory, serial_println, time};

pub const TIMER_VECTOR: u8 = 0x20;
pub const KEYBOARD_VECTOR: u8 = 0x21;
pub const MOUSE_VECTOR: u8 = 0x2C;
pub const SPURIOUS_VECTOR: u8 = 0xFF;

// Register des Local APIC (Abstand zur Basisadresse)
const LAPIC_ID: u32 = 0x20;
const LAPIC_EOI: u32 = 0xB0;
const LAPIC_SPURIOUS: u32 = 0xF0;
const LAPIC_LVT_TIMER: u32 = 0x320;
const LAPIC_TIMER_INIT: u32 = 0x380;
const LAPIC_TIMER_CURRENT: u32 = 0x390;
const LAPIC_TIMER_DIV: u32 = 0x3E0;

static LAPIC: AtomicU64 = AtomicU64::new(0);
static IOAPIC: AtomicU64 = AtomicU64::new(0);
static IOAPIC_GSI_BASE: AtomicU64 = AtomicU64::new(0);

fn lapic_read(reg: u32) -> u32 {
    unsafe { ((LAPIC.load(Ordering::Relaxed) + reg as u64) as *const u32).read_volatile() }
}

fn lapic_write(reg: u32, v: u32) {
    unsafe { ((LAPIC.load(Ordering::Relaxed) + reg as u64) as *mut u32).write_volatile(v) }
}

/// „Fertig mit diesem Interrupt“ – ohne EOI schickt der APIC keine weiteren.
pub fn eoi() {
    lapic_write(LAPIC_EOI, 0);
}

/// Ergebnis der Initialisierung (für die Anzeige)
pub struct ApicInfo {
    pub timer_ticks_per_ms: u32,
}

pub fn init(madt: &Madt) -> ApicInfo {
    if madt.has_8259 {
        disable_pic();
    }

    let lapic = memory::map_physical(madt.lapic_addr, 4096, true).expect("Local APIC nicht mappbar");
    LAPIC.store(lapic.as_u64(), Ordering::Relaxed);
    // Bit 8 = APIC an; untere Bits = Vektor für „spurious“ (Geister-)Interrupts
    lapic_write(LAPIC_SPURIOUS, 0x100 | SPURIOUS_VECTOR as u32);

    let io = madt.ioapics.first().expect("kein I/O APIC gefunden");
    let ioapic = memory::map_physical(io.addr, 4096, true).expect("I/O APIC nicht mappbar");
    IOAPIC.store(ioapic.as_u64(), Ordering::Relaxed);
    IOAPIC_GSI_BASE.store(io.gsi_base as u64, Ordering::Relaxed);
    let max_entry = (ioapic_read(1) >> 16) & 0xFF;
    // Alle Eingänge erst einmal stummschalten (Bit 16 = maskiert)
    for i in 0..=max_entry {
        ioapic_write(0x10 + 2 * i, 1 << 16);
    }
    serial_println!(
        "[aurora] Local APIC {:#x} (ID {}), I/O APIC {:#x} mit {} Eingängen, {} CPU-Kern(e)",
        madt.lapic_addr,
        lapic_read(LAPIC_ID) >> 24,
        io.addr,
        max_entry + 1,
        madt.cpus
    );

    let ticks_per_ms = calibrate_timer();
    // Periodischer Modus (Bit 17): der Timer lädt sich nach jedem Ablauf neu
    lapic_write(LAPIC_TIMER_DIV, 0x3); // Teiler 16
    lapic_write(LAPIC_LVT_TIMER, (1 << 17) | TIMER_VECTOR as u32);
    lapic_write(LAPIC_TIMER_INIT, ticks_per_ms * 1000 / time::HZ as u32);
    ApicInfo { timer_ticks_per_ms: ticks_per_ms }
}

/// Den alten 8259 PIC auf Vektoren 0x20–0x2F verschieben (damit er nicht mit
/// CPU-Exceptions kollidiert) und dann alle Eingänge sperren.
fn disable_pic() {
    unsafe {
        outb(0x20, 0x11);
        outb(0xA0, 0x11);
        outb(0x21, 0x20);
        outb(0xA1, 0x28);
        outb(0x21, 4);
        outb(0xA1, 2);
        outb(0x21, 1);
        outb(0xA1, 1);
        outb(0x21, 0xFF);
        outb(0xA1, 0xFF);
    }
}

/// Der APIC-Timer zählt mit unbekannter Frequenz (hängt von CPU/Bus ab).
/// Deshalb messen wir 10 ms mit dem PIT – einem Uralt-Chip mit exakt
/// bekannter Frequenz von 1,193182 MHz – und zählen dabei die APIC-Ticks.
fn calibrate_timer() -> u32 {
    const PIT_HZ: u32 = 1_193_182;
    let count = (PIT_HZ / 100) as u16; // 10 ms
    unsafe {
        // PIT-Kanal 2: Gate aus, Lautsprecher aus
        outb(0x61, inb(0x61) & !0x03);
        outb(0x43, 0b1011_0000); // Kanal 2, Low/High-Byte, Modus 0
        outb(0x42, count as u8);
        outb(0x42, (count >> 8) as u8);

        lapic_write(LAPIC_TIMER_DIV, 0x3);
        lapic_write(LAPIC_LVT_TIMER, 1 << 16); // Timer-Interrupt maskiert
        // Gate an -> PIT läuft los; gleichzeitig APIC-Timer starten
        outb(0x61, inb(0x61) | 0x01);
        lapic_write(LAPIC_TIMER_INIT, u32::MAX);
        // Bit 5 von Port 0x61 geht auf 1, wenn der PIT bei 0 angekommen ist
        while inb(0x61) & 0x20 == 0 {}
        let elapsed = u32::MAX - lapic_read(LAPIC_TIMER_CURRENT);
        lapic_write(LAPIC_TIMER_INIT, 0);
        (elapsed / 10).max(1)
    }
}

fn ioapic_read(reg: u32) -> u32 {
    let base = IOAPIC.load(Ordering::Relaxed);
    unsafe {
        (base as *mut u32).write_volatile(reg); // IOREGSEL: welches Register?
        ((base + 0x10) as *const u32).read_volatile() // IOWIN: Wert
    }
}

fn ioapic_write(reg: u32, v: u32) {
    let base = IOAPIC.load(Ordering::Relaxed);
    unsafe {
        (base as *mut u32).write_volatile(reg);
        ((base + 0x10) as *mut u32).write_volatile(v);
    }
}

/// Alten ISA-IRQ (1 = Tastatur, 12 = Maus) auf einen IDT-Vektor leiten
pub fn route_isa_irq(madt: &Madt, irq: u8, vector: u8) {
    let mut gsi = irq as u32;
    let mut low = vector as u32; // Standard ISA: aktiv-high, flankengesteuert
    if let Some(o) = madt.overrides.iter().find(|o| o.source == irq) {
        gsi = o.gsi;
        if o.flags & 0b11 == 0b11 {
            low |= 1 << 13; // aktiv-low
        }
        if (o.flags >> 2) & 0b11 == 0b11 {
            low |= 1 << 15; // pegelgesteuert
        }
    }
    let entry = gsi - IOAPIC_GSI_BASE.load(Ordering::Relaxed) as u32;
    let dest = lapic_read(LAPIC_ID) >> 24; // an diesen (den ersten) CPU-Kern
    ioapic_write(0x10 + 2 * entry + 1, dest << 24);
    ioapic_write(0x10 + 2 * entry, low);
}
