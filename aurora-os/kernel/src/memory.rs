//! Speicherverwaltung, Teil 1: physischer Speicher und Paging.
//!
//! Zwei Arten von Adressen:
//! * **physisch** – die echte Stelle im RAM-Chip
//! * **virtuell** – was der Code benutzt; die CPU übersetzt sie über die
//!   Page Tables (4-stufiger Baum, Seiten zu je 4 KiB) in physische Adressen.
//!
//! Limine hat bereits Page Tables eingerichtet und zusätzlich den gesamten
//! physischen Speicher ab `HHDM`-Offset eingeblendet („Higher Half Direct Map“):
//! physisch `p` ist virtuell erreichbar unter `HHDM + p`. Damit können wir
//! jede physische Seite (auch Page Tables) bequem lesen und schreiben.

use limine::memmap::{self, Entry};
use spin::{Mutex, Once};
use x86_64::registers::control::Cr3;
use x86_64::registers::model_specific::{Efer, EferFlags};
use x86_64::structures::paging::{
    FrameAllocator, FrameDeallocator, Mapper, OffsetPageTable, Page, PageTable, PageTableFlags, PhysFrame,
    Size4KiB, Translate,
};
use x86_64::{PhysAddr, VirtAddr};

use crate::serial_println;

pub const PAGE_SIZE: u64 = 4096;

static HHDM: Once<u64> = Once::new();

/// Physische Adresse -> virtuelle Adresse in der Direct Map
pub fn phys_to_virt(p: PhysAddr) -> VirtAddr {
    VirtAddr::new(p.as_u64() + HHDM.get().expect("memory::init fehlt"))
}

// ---------------------------------------------------------------------------
// Statistik über die Speicherkarte
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
pub struct MemStats {
    pub usable: u64,
    pub kernel: u64,
    pub bootloader: u64,
    pub acpi: u64,
    pub framebuffer: u64,
    pub reserved: u64,
    pub entries: usize,
}

impl MemStats {
    /// Alles, was wirklich RAM ist (ohne Geräte-Speicher und Lücken)
    pub fn ram(&self) -> u64 {
        self.usable + self.kernel + self.bootloader + self.acpi
    }
}

fn type_name(t: u64) -> &'static str {
    match t {
        memmap::MEMMAP_USABLE => "frei",
        memmap::MEMMAP_RESERVED => "reserviert",
        memmap::MEMMAP_ACPI_RECLAIMABLE => "ACPI (rückforderbar)",
        memmap::MEMMAP_ACPI_NVS => "ACPI NVS",
        memmap::MEMMAP_BAD_MEMORY => "defekt",
        memmap::MEMMAP_BOOTLOADER_RECLAIMABLE => "Bootloader (rückforderbar)",
        memmap::MEMMAP_EXECUTABLE_AND_MODULES => "Kernel + Module",
        memmap::MEMMAP_FRAMEBUFFER => "Framebuffer",
        _ => "sonstiges",
    }
}

// ---------------------------------------------------------------------------
// Frame-Allocator: verwaltet physische 4-KiB-Seiten („Frames“)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct Region {
    start: u64,
    end: u64,
}

const MAX_REGIONS: usize = 64;

/// Kombination aus zwei einfachen Techniken:
/// 1. **Bump**: neue Frames werden der Reihe nach aus den freien Bereichen
///    der Speicherkarte genommen (O(1)).
/// 2. **Free-List**: zurückgegebene Frames bilden eine verkettete Liste.
///    Der „Zeiger“ auf den nächsten freien Frame wird *im* freien Frame
///    selbst gespeichert – kostet also keinen zusätzlichen Speicher.
pub struct FrameAlloc {
    regions: [Region; MAX_REGIONS],
    count: usize,
    current: usize,
    next: u64,
    free_list: u64, // physische Adresse des ersten freien Frames, 0 = leer
    pub used: u64,
    pub total: u64,
}

impl FrameAlloc {
    fn new(entries: &[&Entry]) -> Self {
        let mut a = FrameAlloc {
            regions: [Region { start: 0, end: 0 }; MAX_REGIONS],
            count: 0,
            current: 0,
            next: 0,
            free_list: 0,
            used: 0,
            total: 0,
        };
        for e in entries.iter().filter(|e| e.type_ == memmap::MEMMAP_USABLE) {
            // auf ganze Seiten runden; Frame 0 auslassen (0 = „leer“ in der Free-List)
            let start = e.base.next_multiple_of(PAGE_SIZE).max(PAGE_SIZE);
            let end = (e.base + e.length) & !(PAGE_SIZE - 1);
            if end > start && a.count < MAX_REGIONS {
                a.regions[a.count] = Region { start, end };
                a.total += (end - start) / PAGE_SIZE;
                a.count += 1;
            }
        }
        a.next = a.regions[0].start;
        a
    }

    pub fn alloc(&mut self) -> Option<PhysFrame> {
        // 1. zuerst wiederverwenden
        if self.free_list != 0 {
            let frame = self.free_list;
            self.free_list = unsafe { phys_to_virt(PhysAddr::new(frame)).as_ptr::<u64>().read() };
            self.used += 1;
            return Some(PhysFrame::containing_address(PhysAddr::new(frame)));
        }
        // 2. sonst den nächsten unbenutzten Frame nehmen
        while self.current < self.count {
            let r = self.regions[self.current];
            if self.next < r.end {
                let frame = self.next;
                self.next += PAGE_SIZE;
                self.used += 1;
                return Some(PhysFrame::containing_address(PhysAddr::new(frame)));
            }
            self.current += 1;
            if self.current < self.count {
                self.next = self.regions[self.current].start;
            }
        }
        None // Speicher voll
    }

    pub fn free(&mut self, frame: PhysFrame) {
        let addr = frame.start_address();
        unsafe { phys_to_virt(addr).as_mut_ptr::<u64>().write(self.free_list) };
        self.free_list = addr.as_u64();
        self.used -= 1;
    }
}

// Damit die Paging-Funktionen des x86_64-Crates unseren Allocator nutzen können
unsafe impl FrameAllocator<Size4KiB> for FrameAlloc {
    fn allocate_frame(&mut self) -> Option<PhysFrame> {
        self.alloc()
    }
}

impl FrameDeallocator<Size4KiB> for FrameAlloc {
    unsafe fn deallocate_frame(&mut self, frame: PhysFrame) {
        self.free(frame)
    }
}

pub static FRAMES: Mutex<Option<FrameAlloc>> = Mutex::new(None);
static MAPPER: Mutex<Option<OffsetPageTable<'static>>> = Mutex::new(None);

// ---------------------------------------------------------------------------
// Initialisierung und Hilfsfunktionen
// ---------------------------------------------------------------------------

pub fn init(hhdm: u64, entries: &[&Entry]) -> MemStats {
    HHDM.call_once(|| hhdm);

    // NX-Bit erlauben: Daten-Seiten können damit als „nicht ausführbar“ markiert werden
    unsafe { Efer::update(|f| f.insert(EferFlags::NO_EXECUTE_ENABLE)) };

    serial_println!("[aurora] Speicherkarte ({} Einträge):", entries.len());
    let mut s = MemStats { entries: entries.len(), ..Default::default() };
    for e in entries {
        serial_println!(
            "    {:#014x} – {:#014x}  {:>9} KiB  {}",
            e.base,
            e.base + e.length,
            e.length / 1024,
            type_name(e.type_)
        );
        match e.type_ {
            memmap::MEMMAP_USABLE => s.usable += e.length,
            memmap::MEMMAP_EXECUTABLE_AND_MODULES => s.kernel += e.length,
            memmap::MEMMAP_BOOTLOADER_RECLAIMABLE => s.bootloader += e.length,
            memmap::MEMMAP_ACPI_RECLAIMABLE | memmap::MEMMAP_ACPI_NVS => s.acpi += e.length,
            memmap::MEMMAP_FRAMEBUFFER => s.framebuffer += e.length,
            _ => s.reserved += e.length,
        }
    }

    *FRAMES.lock() = Some(FrameAlloc::new(entries));

    // CR3 enthält die physische Adresse der obersten Page Table (Level 4)
    let (l4_frame, _) = Cr3::read();
    let l4: &'static mut PageTable =
        unsafe { &mut *phys_to_virt(l4_frame.start_address()).as_mut_ptr::<PageTable>() };
    *MAPPER.lock() = Some(unsafe { OffsetPageTable::new(l4, VirtAddr::new(hhdm)) });
    s
}

/// Neue physische Seite holen und an `page` einblenden
pub fn map_page(page: Page, flags: PageTableFlags) -> Result<(), &'static str> {
    let mut frames = FRAMES.lock();
    let frames = frames.as_mut().ok_or("Frame-Allocator fehlt")?;
    let frame = frames.alloc().ok_or("kein freier physischer Speicher mehr")?;
    let mut mapper = MAPPER.lock();
    let mapper = mapper.as_mut().ok_or("Mapper fehlt")?;
    unsafe { mapper.map_to(page, frame, flags, frames) }
        .map_err(|_| "Seite konnte nicht gemappt werden")?
        .flush(); // TLB (Übersetzungs-Cache der CPU) für diese Seite leeren
    Ok(())
}

/// Seite ausblenden und den physischen Frame zurückgeben
pub fn unmap_page(page: Page) -> Result<(), &'static str> {
    let mut mapper = MAPPER.lock();
    let (frame, flush) = mapper.as_mut().ok_or("Mapper fehlt")?.unmap(page).map_err(|_| "Seite war nicht gemappt")?;
    flush.flush();
    FRAMES.lock().as_mut().ok_or("Frame-Allocator fehlt")?.free(frame);
    Ok(())
}

/// Physischen Bereich (z. B. Geräte-Register oder ACPI-Tabellen) in der
/// Direct Map sichtbar machen. Limine blendet dort nur RAM ein – Geräte wie
/// der APIC liegen außerhalb und müssen von uns gemappt werden.
/// `uncached`: Geräte-Register dürfen nie im CPU-Cache landen, sonst sieht
/// das Gerät unsere Schreibzugriffe zu spät (oder gar nicht).
pub fn map_physical(phys: u64, len: u64, uncached: bool) -> Result<VirtAddr, &'static str> {
    let mut flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    if uncached {
        flags |= PageTableFlags::NO_CACHE | PageTableFlags::WRITE_THROUGH;
    }
    let start = phys & !(PAGE_SIZE - 1);
    let end = (phys + len.max(1)).next_multiple_of(PAGE_SIZE);
    for frame_addr in (start..end).step_by(PAGE_SIZE as usize) {
        let virt = phys_to_virt(PhysAddr::new(frame_addr));
        if translate(virt).is_some() {
            continue; // schon sichtbar (z. B. RAM von Limine)
        }
        let page = Page::<Size4KiB>::containing_address(virt);
        let frame = PhysFrame::containing_address(PhysAddr::new(frame_addr));
        let mut frames = FRAMES.lock();
        let mut mapper = MAPPER.lock();
        unsafe { mapper.as_mut().ok_or("Mapper fehlt")?.map_to(page, frame, flags, frames.as_mut().ok_or("Frames fehlen")?) }
            .map_err(|_| "physischer Bereich konnte nicht gemappt werden")?
            .flush();
    }
    Ok(phys_to_virt(PhysAddr::new(phys)))
}

/// Virtuelle Adresse -> physische Adresse (läuft die Page Tables per Software ab)
pub fn translate(addr: VirtAddr) -> Option<PhysAddr> {
    MAPPER.lock().as_ref()?.translate_addr(addr)
}

/// (belegte, gesamte) physische Frames
pub fn frame_stats() -> (u64, u64) {
    FRAMES.lock().as_ref().map(|f| (f.used, f.total)).unwrap_or((0, 0))
}
