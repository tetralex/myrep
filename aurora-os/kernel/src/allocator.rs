//! Speicherverwaltung, Teil 2: der Kernel-Heap.
//!
//! Wir reservieren einen virtuellen Adressbereich, blenden dort echte
//! physische Seiten ein und übergeben ihn einem Heap-Allocator. Ab dann
//! funktionieren `Box`, `Vec`, `String`, `BTreeMap` … aus der `alloc`-Bibliothek.

use core::alloc::{GlobalAlloc, Layout};

use linked_list_allocator::LockedHeap;
use x86_64::instructions::interrupts::without_interrupts;
use x86_64::VirtAddr;
use x86_64::structures::paging::{Page, PageTableFlags};

use crate::memory;

/// Weit weg von der Direct Map (0xffff_8000_…) und vom Kernel (0xffff_ffff_8…)
pub const HEAP_START: u64 = 0xffff_9000_0000_0000;
/// 64 MiB – genug für zwei bildschirmgroße Zeichenflächen (Szene + Arbeitsfläche)
/// auch in Full HD (je 8 MiB). Ab Meilenstein 6 wächst der Heap bei Bedarf.
pub const HEAP_SIZE: u64 = 64 * 1024 * 1024;

/// Heap mit gesperrten Interrupts: Wird ein Thread mitten in einer
/// Allokation unterbrochen, hält er die Heap-Sperre – alle anderen Threads
/// müssten warten. Mit gesperrten Interrupts kann das nicht passieren
/// (die Allokation dauert nur Mikrosekunden).
struct InterruptSafeHeap(LockedHeap);

unsafe impl GlobalAlloc for InterruptSafeHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        without_interrupts(|| unsafe { self.0.alloc(layout) })
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        without_interrupts(|| unsafe { self.0.dealloc(ptr, layout) })
    }
}

/// `#[global_allocator]` sagt Rust: Alle Heap-Anfragen gehen hierhin.
#[global_allocator]
static ALLOCATOR: InterruptSafeHeap = InterruptSafeHeap(LockedHeap::empty());

pub fn init() -> Result<(), &'static str> {
    let first = Page::containing_address(VirtAddr::new(HEAP_START));
    let last = Page::containing_address(VirtAddr::new(HEAP_START + HEAP_SIZE - 1));
    // beschreibbar, aber nicht ausführbar: Daten sollen nie als Code laufen
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    for page in Page::range_inclusive(first, last) {
        memory::map_page(page, flags)?;
    }
    without_interrupts(|| unsafe { ALLOCATOR.0.lock().init(HEAP_START as *mut u8, HEAP_SIZE as usize) });
    Ok(())
}

/// (belegte Bytes, Gesamtgröße)
pub fn stats() -> (usize, usize) {
    without_interrupts(|| {
        let heap = ALLOCATOR.0.lock();
        (heap.used(), heap.size())
    })
}
