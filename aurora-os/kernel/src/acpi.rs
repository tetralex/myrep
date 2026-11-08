//! ACPI: Tabellen, mit denen die Firmware die Hardware beschreibt.
//! Wir brauchen nur die MADT („Multiple APIC Description Table“):
//! Sie verrät, wo Local APIC und I/O APIC liegen, wie viele CPU-Kerne es
//! gibt und welche alten ISA-Interrupts (z. B. Tastatur = IRQ 1) auf welche
//! I/O-APIC-Eingänge umgeleitet sind.

use alloc::vec::Vec;
use crate::memory;

#[derive(Clone, Copy, Debug)]
pub struct IoApic {
    pub addr: u64,
    pub gsi_base: u32,
}

/// „Interrupt Source Override“: ISA-IRQ `source` kommt am Eingang `gsi` an
#[derive(Clone, Copy, Debug)]
pub struct IrqOverride {
    pub source: u8,
    pub gsi: u32,
    pub flags: u16,
}

pub struct Madt {
    pub lapic_addr: u64,
    pub has_8259: bool,
    pub cpus: usize,
    pub ioapics: Vec<IoApic>,
    pub overrides: Vec<IrqOverride>,
}

/// Bytes einer physischen Adresse lesen (ACPI-Tabellen sind nicht ausgerichtet,
/// deshalb immer `read_unaligned`)
fn read<T: Copy>(phys: u64) -> T {
    let v = memory::map_physical(phys, size_of::<T>() as u64, false).expect("ACPI nicht lesbar");
    unsafe { v.as_ptr::<T>().read_unaligned() }
}

fn table_signature(phys: u64) -> [u8; 4] {
    read(phys)
}

fn table_length(phys: u64) -> u32 {
    read(phys + 4)
}

/// `rsdp`: Adresse, die Limine liefert (je nach Protokoll-Revision physisch oder virtuell)
pub fn find_madt(rsdp: u64, hhdm: u64) -> Option<Madt> {
    let rsdp = if rsdp >= hhdm { rsdp - hhdm } else { rsdp };
    // RSDP: "RSD PTR " – zeigt auf RSDT (32-Bit-Zeiger) oder XSDT (64-Bit-Zeiger)
    if &read::<[u8; 8]>(rsdp) != b"RSD PTR " {
        return None;
    }
    let revision: u8 = read(rsdp + 15);
    let (root, entry_size) =
        if revision >= 2 { (read::<u64>(rsdp + 24), 8) } else { (read::<u32>(rsdp + 16) as u64, 4) };

    let len = table_length(root) as u64;
    let count = (len - 36) / entry_size;
    let madt = (0..count).map(|i| {
        let at = root + 36 + i * entry_size;
        if entry_size == 8 { read::<u64>(at) } else { read::<u32>(at) as u64 }
    })
    .find(|&t| &table_signature(t) == b"APIC")?;

    // MADT-Inhalt: ab Byte 36 die Local-APIC-Adresse, dann Flags, dann Einträge
    let len = table_length(madt) as u64;
    let _ = memory::map_physical(madt, len, false);
    let mut m = Madt {
        lapic_addr: read::<u32>(madt + 36) as u64,
        has_8259: read::<u32>(madt + 40) & 1 != 0,
        cpus: 0,
        ioapics: Vec::new(),
        overrides: Vec::new(),
    };
    let mut at = madt + 44;
    while at + 2 <= madt + len {
        let (kind, size): (u8, u8) = (read(at), read(at + 1));
        match kind {
            0 if read::<u32>(at + 4) & 1 != 0 => m.cpus += 1, // aktivierter CPU-Kern
            1 => m.ioapics.push(IoApic { addr: read::<u32>(at + 4) as u64, gsi_base: read(at + 8) }),
            2 => m.overrides.push(IrqOverride { source: read(at + 3), gsi: read(at + 4), flags: read(at + 8) }),
            5 => m.lapic_addr = read(at + 4),
            _ => {}
        }
        if size == 0 {
            break;
        }
        at += size as u64;
    }
    Some(m)
}
